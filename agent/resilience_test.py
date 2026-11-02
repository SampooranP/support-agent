"""Failure-handling tests for the agent loop, with injected failures (no Claude calls).

Uses the real Supabase tables and MCP server, with a fake Claude client that always errors,
so it's fast, free and deterministic. From the repo root:
    python -m agent.resilience_test

Checks:
  1. A tool that crashes still gets a tool_result, so the conversation stays usable.
  2. A turn that ends on an unanswered tool_use is repaired before saving.
  3. A resume that crashes while running an approved refund leaves it approved and the
     conversation paused, so it can be retried; the retry refunds exactly once.
  4. A Claude error during a turn is reported once, before a single "done".
  5. An approval that already executed is reported as done, not re-run or called rejected.
  6. Malformed IDs are "not found", not a database error.
  7. Only one risky call per reply is held for approval; a second gets an error to retry later.
"""

import asyncio
import sys
from types import SimpleNamespace

from mcp import Client

from agent import store
from agent.loop import INTERRUPTED, ONE_AT_A_TIME, Agent, _close_dangling_tool_uses
from agent.tools import Toolbox
from ingestion.config import REPO_ROOT, supabase_client

sys.path.insert(0, str(REPO_ROOT / "mcp-server"))
import server  # noqa: E402  (the MCP server, connected in-process)

failures = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global failures
    failures += not ok
    print(f"{'PASS' if ok else 'FAIL'}  {name}{f'  ({detail})' if detail else ''}")


class FailingClaude:
    """Stands in for AsyncAnthropic: every model call fails, like an overloaded API."""

    class _Stream:
        async def __aenter__(self):
            raise ConnectionError("simulated: Claude API unavailable")

        async def __aexit__(self, *exc):
            return False

    def __init__(self):
        self.beta = SimpleNamespace(messages=SimpleNamespace(stream=lambda **_: FailingClaude._Stream()))


class FlakyToolbox(Toolbox):
    """A Toolbox whose run() raises on the first `failures` calls, then works normally."""

    def __init__(self, inner: Toolbox, failures: int):
        self.__dict__.update(inner.__dict__)
        self.remaining_failures = failures
        self.run_calls = 0

    async def run(self, *args, **kwargs):
        self.run_calls += 1
        if self.remaining_failures > 0:
            self.remaining_failures -= 1
            raise ConnectionError("simulated: database connection reset")
        return await super().run(*args, **kwargs)


class Events:
    def __init__(self):
        self.items: list[dict] = []

    async def __call__(self, event: dict) -> None:
        self.items.append(event)

    def types(self) -> list[str]:
        return [e["type"] for e in self.items]


def new_conversation(email: str = "maya.chen@example.com") -> dict:
    return store.get_conversation(store.create_conversation(email)["id"])


async def main() -> None:
    supabase_client().rpc("reset_demo_data").execute()
    print("demo data reset")

    async with Client(server.mcp) as mcp:
        toolbox = await Toolbox.connect(mcp)

        # 1. A crashing tool still gets a result.
        flaky = FlakyToolbox(toolbox, failures=1)
        agent = Agent(FailingClaude(), flaky)
        conversation = new_conversation()
        tool_use = SimpleNamespace(id="toolu_1", name="search_knowledge_base", input={"query": "refunds"})
        events = Events()
        results, awaiting = await agent._run_tools(conversation, [tool_use], events)
        result = results.get("toolu_1") or {}
        check("crashing tool -> error tool_result", result.get("is_error") is True and result.get("content") == INTERRUPTED)
        check("crashing tool -> step marked as error", events.items[-1] == {"type": "tool", "name": "search_knowledge_base", "status": "error"})

        # 2. A dangling tool_use is answered before saving.
        conversation["messages"] = [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": [{"type": "tool_use", "id": "toolu_2", "name": "get_customer", "input": {}}]},
        ]
        _close_dangling_tool_uses(conversation)
        last = conversation["messages"][-1]
        check("dangling tool_use repaired", last["role"] == "user" and last["content"][0]["tool_use_id"] == "toolu_2")

        # 3. A resume that crashes mid-refund can be retried, and refunds exactly once.
        conversation = new_conversation()
        tool_use_id = "toolu_refund"
        approval = store.create_approval(conversation["id"], tool_use_id, "issue_refund",
                                         {"order_number": "1042", "amount": 10.0, "reason": "test"}, "Refund 10.00 USD")
        store.decide_approval(approval["id"], True, "tester", None)
        conversation.update(
            status="awaiting_approval",
            messages=[
                {"role": "user", "content": "My tent arrived damaged."},
                {"role": "assistant", "content": [{"type": "tool_use", "id": tool_use_id, "name": "issue_refund",
                                                   "input": {"order_number": "1042", "amount": 10.0, "reason": "test"}}]},
            ],
            pending_turn={"order": [tool_use_id], "results": {tool_use_id: None}, "awaiting": [tool_use_id]},
        )
        store.save_conversation(conversation)

        flaky = FlakyToolbox(toolbox, failures=1)
        agent = Agent(FailingClaude(), flaky)
        try:
            await agent.resume_after_decisions(store.get_conversation(conversation["id"]))
            crashed = False
        except ConnectionError:
            crashed = True
        check("crashing resume raises for the caller to retry", crashed)
        check("approval still approved after the crash", store.get_approval(approval["id"])["status"] == "approved")
        check("conversation still paused after the crash", store.get_conversation(conversation["id"])["status"] == "awaiting_approval")

        # Retry: the refund runs, then Claude errors (4.); the error is reported once, before one "done".
        events = Events()
        resumed = await agent.resume_after_decisions(store.get_conversation(conversation["id"]), events)
        refunds = supabase_client().table("refunds").select("amount").eq("approval_id", approval["id"]).execute().data
        check("retry resumes and refunds exactly once", resumed and len(refunds) == 1, f"{len(refunds)} refund(s)")
        check("approval marked executed", store.get_approval(approval["id"])["status"] == "executed")
        types = events.types()
        check("Claude error reported once, then one done", types.count("done") == 1 and types[-1] == "done"
              and types.count("error") == 1 and types.index("error") < types.index("done"), " > ".join(types))
        saved = store.get_conversation(conversation["id"])
        last = saved["messages"][-1]
        check("conversation unpaused with the refund result saved",
              saved["status"] == "active" and last["role"] == "user" and "complete" in last["content"][0]["content"])

        # 5. Re-resolving an executed approval reports it done without running it again.
        calls_before = flaky.run_calls
        outcome = await agent._approval_outcome(store.get_approval(approval["id"]), saved, Events())
        check("executed approval reported as done, not re-run",
              not outcome.is_error and "complete" in outcome.content and flaky.run_calls == calls_before)
        rejected = {**store.get_approval(approval["id"]), "status": "rejected", "reviewer_note": "no"}
        outcome = await agent._approval_outcome(rejected, saved, Events())
        check("rejected approval reported as rejected", outcome.is_error and "rejected" in outcome.content)

        # 7. Two risky calls in one reply: only the first is held; the second is sent back to wait.
        conversation = new_conversation()
        refund = SimpleNamespace(id="toolu_r", name="issue_refund",
                                 input={"order_number": "1042", "amount": 10.0, "reason": "test"})
        email = SimpleNamespace(id="toolu_e", name="send_email",
                                input={"subject": "Your refund", "body": "Your refund has been issued."})
        results, awaiting = await agent._run_tools(conversation, [refund, email], Events())
        held = store.list_approvals(None, conversation["id"])
        check("second risky call in a reply isn't requested", awaiting == ["toolu_r"] and len(held) == 1
              and results["toolu_e"]["is_error"] and results["toolu_e"]["content"] == ONE_AT_A_TIME,
              f"awaiting {awaiting}, {len(held)} approval(s)")

    # 6. Malformed IDs.
    check("malformed conversation id -> None", store.get_conversation("not-a-uuid") is None)
    check("malformed approval id -> None", store.get_approval("abc") is None)

    print(f"\n{'All resilience checks passed.' if not failures else f'{failures} check(s) failed.'}")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    asyncio.run(main())
