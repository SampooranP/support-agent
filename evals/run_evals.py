"""Run the eval suite against the real agent and grade every conversation.

From the repo root:
    python -m evals.run_evals                      # all cases, 1 rep, variant "baseline"
    python -m evals.run_evals --only rewards-balance,ship-to-uk
    python -m evals.run_evals --reps 2 --variant v1
    python -m evals.run_evals --selftest           # grader checks only (oracle, null, judge negatives)

The runner drives the same Agent class the API uses, with the real MCP server, Supabase and
Claude. It resets the demo data first, so don't run it against a database with real data
(reset_demo_data refuses in that case anyway).

Output (the layout the eval report builder reads), under evals/runs/<variant>/:
    results.jsonl            one row per (case, rep), written as each case finishes
    traces/<id>_rep<k>.json  the full conversation, including every tool call and result
    errors.jsonl             attempts that produced nothing gradable (timeouts, API errors, ...)
    summary.json, summary.md the headline numbers

Harness gate: the run refuses to start if the eval code or cases changed since they were last
approved. After reviewing a change, approve it once with --approve-harness.
"""

import argparse
import asyncio
import hashlib
import json
import math
import statistics
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

import anthropic
import yaml
from mcp import Client, StdioServerParameters

from agent import store
from agent.loop import MODEL, Agent
from agent.pricing import cost_usd, usage_dict
from agent.prompts import system_prompt
from agent.store import in_thread
from agent.tools import Toolbox
from agent.tracing import Tracer
from evals.grading import Outcome, grade_action, grade_safety
from evals.judge import judge
from ingestion.config import REPO_ROOT, require_env, supabase_client

EVALS = REPO_ROOT / "evals"
FLOW = EVALS / "runs"
CASES = EVALS / "cases.yaml"
HARNESS_FILES = [Path(__file__), EVALS / "grading.py", EVALS / "judge.py", EVALS / "selftest.py", CASES]
HARNESS_SHA = FLOW / "harness.json"
MCP_SERVER = REPO_ROOT / "mcp-server" / "server.py"
METRICS = ["pass", "action", "safety", "grounded", "quality"]
VALID_TOOLS = {"search_knowledge_base", "get_order", "get_customer", "create_ticket", "issue_refund", "send_email"}


# ---------------------------------------------------------------- cases


def load_cases(path: Path = CASES) -> list[dict]:
    """Load the cases and check them (tier-1 audit): unique ids, known customers, tools and fields."""
    cases = yaml.safe_load(path.read_text(encoding="utf-8"))
    customers = {c["email"] for c in store.list_demo_customers()}
    errors, seen = [], set()
    for case in cases:
        cid = case.get("id", "?")
        if cid in seen:
            errors.append(f"{cid}: duplicate id")
        seen.add(cid)
        if case.get("customer") not in customers:
            errors.append(f"{cid}: unknown customer {case.get('customer')}")
        if not case.get("turns"):
            errors.append(f"{cid}: no turns")
        expect = case.get("expect", {})
        for tool in expect.get("tools", []):
            if tool not in VALID_TOOLS:
                errors.append(f"{cid}: unknown tool {tool}")
        approval = expect.get("approval", "none")
        if approval not in ("none", "any") and not (isinstance(approval, dict) and approval.get("tool") in VALID_TOOLS):
            errors.append(f"{cid}: bad approval expectation {approval!r}")
        if expect.get("decision") not in (None, "approve", "reject"):
            errors.append(f"{cid}: decision must be approve or reject")
    if errors:
        raise SystemExit("Invalid cases:\n  " + "\n  ".join(errors))
    return cases


# ---------------------------------------------------------------- harness gate


def harness_sha() -> str:
    digest = hashlib.sha256()
    for path in HARNESS_FILES:
        digest.update(path.name.encode())
        digest.update(path.read_bytes().replace(b"\r\n", b"\n"))  # same sha on Windows and Linux checkouts
    return digest.hexdigest()


def check_harness(approve: bool) -> None:
    current = harness_sha()
    if approve:
        FLOW.mkdir(parents=True, exist_ok=True)
        HARNESS_SHA.write_text(json.dumps({"sha": current, "files": [p.name for p in HARNESS_FILES]}, indent=2) + "\n")
        print("Harness approved.")
        return
    approved = json.loads(HARNESS_SHA.read_text())["sha"] if HARNESS_SHA.exists() else None
    if approved != current:
        print("The eval code or cases changed since they were last approved (evals/runs/harness.json).\n"
              "Review the change, then run once with --approve-harness.", file=sys.stderr)
        sys.exit(2)


# ---------------------------------------------------------------- running a case


class CaseError(Exception):
    """An attempt that produced nothing gradable. Goes to errors.jsonl, never into the scores."""

    def __init__(self, kind: str, message: str, calls: list[dict] | None = None):
        super().__init__(message)
        self.kind = kind
        self.calls = calls or []


@dataclass
class Collector:
    """Collects one agent turn's stream events, like the chat UI would."""

    events: list[dict] = field(default_factory=list)
    text_parts: list[str] = field(default_factory=list)

    async def __call__(self, event: dict) -> None:
        self.events.append(event)
        if event["type"] == "text":
            self.text_parts.append(event["delta"])
        elif event["type"] == "retry":
            self.text_parts.clear()  # the client discards a retried call's partial text

    @property
    def text(self) -> str:
        return "".join(self.text_parts).strip()

    def of(self, kind: str) -> list[dict]:
        return [e for e in self.events if e["type"] == kind]


async def run_case(agent: Agent, case: dict) -> dict:
    """Run one case's conversation through the agent and return what happened."""
    expect = case.get("expect", {})
    created = await in_thread(store.create_conversation, case["customer"])
    conversation = await in_thread(store.get_conversation, created["id"])
    customer = await in_thread(store.get_customer_by_email, case["customer"])

    turns: list[Collector] = []
    for text in case["turns"]:
        if conversation["status"] == "awaiting_approval":
            break  # the chat blocks new messages while a request is under review
        collector = Collector()
        await agent.handle_user_message(conversation, text, collector)
        turns.append(collector)

    followup = None
    if expect.get("decision") and conversation["status"] == "awaiting_approval":
        pending = [a for a in await in_thread(store.list_approvals, ["pending"], conversation["id"])]
        for approval in pending:
            await in_thread(store.decide_approval, approval["id"], expect["decision"] == "approve",
                            "eval-supervisor", expect.get("note"))
        followup = Collector()
        conversation = await in_thread(store.get_conversation, conversation["id"])
        await agent.resume_after_decisions(conversation, followup)

    collectors = turns + ([followup] if followup else [])
    calls = [e for c in collectors for e in c.of("model_call")]
    errors = [e["message"] for c in collectors for e in c.of("error")]
    refused = any(call["stop_reason"] == "refusal" for call in calls)
    if errors and not refused:
        raise CaseError("serving_error", "; ".join(errors), calls)
    wrong_model = sorted({call["model"] for call in calls if call["model"] != MODEL})
    if wrong_model:
        raise CaseError("model_mismatch", f"served by {wrong_model}, expected {MODEL}", calls)

    conversation = await in_thread(store.get_conversation, conversation["id"])
    approvals = list(reversed(await in_thread(store.list_approvals, None, conversation["id"])))
    tickets = (await in_thread(
        lambda: supabase_client().table("tickets").select("*").eq("conversation_id", conversation["id"]).execute()
    )).data
    tools_called = [b["name"] for m in conversation["messages"] if m["role"] == "assistant"
                    and isinstance(m["content"], list) for b in m["content"] if b["type"] == "tool_use"]
    outcome = Outcome(
        customer=customer,
        tools_called=tools_called,
        approvals=approvals,
        tickets=tickets,
        replies=[t.text for t in turns],
        followup_replies=[followup.text] if followup else [],
        executed_tools={a["tool_name"] for a in approvals if a["status"] == "executed"},
    )
    return {"conversation": conversation, "customer": customer, "outcome": outcome, "calls": calls,
            "refused": refused, "approvals": approvals}


def build_trace(conversation: dict, customer: dict, approvals: list[dict]) -> list[dict]:
    """The conversation in the report's trace format: system, user, assistant, tool_call, tool_result."""
    trace = [{"role": "system", "content": system_prompt(customer["name"], customer["email"])}]
    answered = set()
    for message in conversation["messages"]:
        content = message["content"]
        if isinstance(content, str):
            trace.append({"role": message["role"], "content": content})
            continue
        for block in content:
            if block["type"] == "text" and block["text"].strip():
                trace.append({"role": "assistant", "content": block["text"]})
            elif block["type"] == "tool_use":
                trace.append({"role": "tool_call", "name": block["name"], "content": json.dumps(block["input"], indent=2)})
            elif block["type"] == "tool_result":
                answered.add(block["tool_use_id"])
                trace.append({"role": "tool_result", "content": _result_text(block["content"])})
    # A request still waiting for review has no tool_result yet; say so, so the transcript reads correctly.
    for approval in approvals:
        if approval["tool_use_id"] not in answered:
            trace.append({"role": "tool_result",
                          "content": f"(held for supervisor review: {approval['summary']}; status {approval['status']})"})
    return trace


def _result_text(content) -> str:
    if isinstance(content, str):
        return content
    parts = []
    for block in content:
        if block.get("type") == "search_result":
            body = "\n".join(c.get("text", "") for c in block.get("content", []))
            parts.append(f"[{block.get('title')}]\n{body}")
        elif block.get("type") == "text":
            parts.append(block["text"])
    return "\n\n".join(parts)


# ---------------------------------------------------------------- grading and output


def sum_usage(calls: list[dict]) -> dict[str, int]:
    total = {k: 0 for k in usage_dict({})}
    for call in calls:
        for k, v in call["usage"].items():
            total[k] += v
    return total


async def grade_and_write(case: dict, rep: int, result: dict, judge_client, out: Path, wall_s: float) -> dict:
    outcome: Outcome = result["outcome"]
    expect = case.get("expect", {})
    trace = build_trace(result["conversation"], result["customer"], result["approvals"])
    (out / "traces").mkdir(parents=True, exist_ok=True)
    (out / "traces" / f"{case['id']}_rep{rep}.json").write_text(json.dumps(trace, indent=2), encoding="utf-8")

    calls = result["calls"]
    truncated = any(call["stop_reason"] == "max_tokens" for call in calls)
    action_ok, action_why = grade_action(expect, outcome)
    safety_ok, safety_why = grade_safety(expect, outcome)
    try:
        verdict, judge_response = await judge(judge_client, trace, case.get("rubric", []))
    except Exception as e:
        raise CaseError("grader_error", f"judge failed: {e}", calls) from e
    grade = {
        "action": float(action_ok),
        "safety": float(safety_ok),
        "grounded": float(verdict.grounded),
        "quality": float(verdict.quality),
    }
    grade = {"pass": float(all(grade.values())), **grade}
    agent_usage = sum_usage(calls)
    agent_cost = sum(cost_usd(call["model"], call["usage"]) or 0 for call in calls)
    judge_cost = cost_usd(judge_response.model, judge_response.usage) or 0
    row = {
        "prompt_id": case["id"],
        "prompt": "\n\n".join(case["turns"]),
        "tags": case.get("tags", []),
        "rep": rep,
        "status": "truncated" if truncated else "ok",
        "stop_reason": calls[-1]["stop_reason"] if calls else None,
        "grade": {} if truncated else grade,
        "explanation": {
            "action": action_why,
            "safety": safety_why,
            "grounded": verdict.grounded_reason,
            "quality": verdict.quality_reason,
        },
        "model": MODEL,
        "usage": agent_usage,
        "judge_model": judge_response.model,
        "judge_usage": usage_dict(judge_response.usage),
        "cost_usd": round(agent_cost + judge_cost, 5),
        "latency_s": round(sum(call["latency_s"] for call in calls), 2),
        "tool_calls": len(outcome.tools_called),
        "refused": int(result["refused"]),
        "meta": {
            "conversation_id": result["conversation"]["id"],
            "wall_s": round(wall_s, 1),
            "model_calls": len(calls),
            "agent_cost_usd": round(agent_cost, 5),
            "judge_cost_usd": round(judge_cost, 5),
            "approvals": [a["summary"] for a in outcome.approvals],
            "tickets": [t["ticket_number"] for t in outcome.tickets],
        },
    }
    return row


def append_jsonl(path: Path, row: dict) -> None:
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row) + "\n")


def done_keys(out: Path) -> set[tuple[str, int]]:
    path = out / "results.jsonl"
    if not path.exists():
        return set()
    return {(r["prompt_id"], r["rep"]) for r in map(json.loads, path.read_text(encoding="utf-8").splitlines()) if r}


def wilson(passes: float, n: int) -> tuple[float, float]:
    """95% confidence interval for a pass rate."""
    if n == 0:
        return 0.0, 0.0
    z, p = 1.96, passes / n
    center = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return max(0.0, center - half), min(1.0, center + half)


def summarize(out: Path, variant: str) -> dict:
    rows = [json.loads(line) for line in (out / "results.jsonl").read_text(encoding="utf-8").splitlines() if line]
    errors_path = out / "errors.jsonl"
    errors = [json.loads(line) for line in errors_path.read_text(encoding="utf-8").splitlines() if line] if errors_path.exists() else []
    ok = [r for r in rows if r["status"] == "ok"]
    summary = {"variant": variant, "cases": len({r["prompt_id"] for r in rows}), "rows": len(rows),
               "ok_rows": len(ok), "truncated": len(rows) - len(ok), "errors": len(errors), "metrics": {}}
    for metric in METRICS:
        passes = sum(r["grade"][metric] for r in ok)
        low, high = wilson(passes, len(ok))
        summary["metrics"][metric] = {"rate": passes / len(ok) if ok else 0, "ci95": [low, high]}
    summary["cost_usd_total"] = round(sum(r["cost_usd"] for r in rows), 4)
    summary["cost_usd_median"] = round(statistics.median(r["cost_usd"] for r in rows), 4) if rows else 0
    summary["latency_s_median"] = round(statistics.median(r["latency_s"] for r in rows), 1) if rows else 0
    summary["refusals"] = sum(r["refused"] for r in rows)
    summary["failing"] = sorted({r["prompt_id"] for r in ok if r["grade"]["pass"] < 1})
    (out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")

    labels = {"pass": "Pass (all checks)", "action": "Right action", "safety": "Safety",
              "grounded": "Grounded", "quality": "Quality"}
    lines = [f"### Eval results: `{variant}`", "",
             f"{summary['ok_rows']} graded conversations across {summary['cases']} cases"
             f" ({summary['truncated']} truncated, {summary['errors']} errors).", "",
             "| Metric | Score | 95% CI |", "|---|---|---|"]
    for metric in METRICS:
        m = summary["metrics"][metric]
        lines.append(f"| {labels[metric]} | {m['rate']:.0%} | {m['ci95'][0]:.0%}-{m['ci95'][1]:.0%} |")
    lines += ["", f"Cost: ${summary['cost_usd_total']:.2f} total, ${summary['cost_usd_median']:.3f} median per conversation"
              f" (agent + judge). Median model latency {summary['latency_s_median']} s. Refusals: {summary['refusals']}."]
    if summary["failing"]:
        lines += ["", "Failing: " + ", ".join(f"`{c}`" for c in summary["failing"])]
    (out / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return summary


# ---------------------------------------------------------------- main


async def main_async(args) -> None:
    cases = load_cases()
    if args.only:
        wanted = set(args.only.split(","))
        cases = [c for c in cases if c["id"] in wanted]
        missing = wanted - {c["id"] for c in cases}
        if missing:
            raise SystemExit(f"Unknown case ids: {', '.join(sorted(missing))}")

    out = FLOW / args.variant
    out.mkdir(parents=True, exist_ok=True)
    done = done_keys(out)
    todo = [(c, rep) for c in cases for rep in range(args.reps) if (c["id"], rep) not in done]
    print(f"{len(todo)} attempt(s) to run ({len(done)} already done) -> {out.relative_to(REPO_ROOT)}")
    if not todo:
        print(json.dumps(summarize(out, args.variant)["metrics"], indent=2))
        return

    agent_client = anthropic.AsyncAnthropic(api_key=require_env("ANTHROPIC_API_KEY"), max_retries=4)
    judge_client = anthropic.AsyncAnthropic(api_key=require_env("ANTHROPIC_API_KEY"), max_retries=4)
    await in_thread(lambda: supabase_client().rpc("reset_demo_data").execute())

    async with Client(StdioServerParameters(command=sys.executable, args=[str(MCP_SERVER)])) as mcp:
        agent = Agent(agent_client, await Toolbox.connect(mcp), Tracer())
        limit = asyncio.Semaphore(args.concurrency)

        async def attempt(case: dict, rep: int) -> None:
            started = time.monotonic()
            try:
                result = await asyncio.wait_for(run_case(agent, case), timeout=args.timeout_s)
                row = await grade_and_write(case, rep, result, judge_client, out, time.monotonic() - started)
                append_jsonl(out / "results.jsonl", row)
                verdict = "PASS" if row["grade"].get("pass") else ("TRUNC" if row["status"] != "ok" else "FAIL")
                print(f"{verdict:5} {case['id']} (rep {rep}) ${row['cost_usd']:.3f} {row['meta']['wall_s']}s")
            except Exception as e:
                kind = "timeout" if isinstance(e, TimeoutError) else getattr(e, "kind", "harness_error")
                calls = getattr(e, "calls", [])
                append_jsonl(out / "errors.jsonl", {
                    "prompt_id": case["id"], "rep": rep, "kind": kind, "message": str(e)[:500],
                    "model": MODEL, "usage": sum_usage(calls),
                    "cost_usd": round(sum(cost_usd(c["model"], c["usage"]) or 0 for c in calls), 5),
                })
                print(f"ERROR {case['id']} (rep {rep}) {kind}: {str(e)[:120]}")

        async def guarded(case: dict, rep: int) -> None:
            async with limit:
                await attempt(case, rep)

        # Cases where a supervisor decides change the database (refunds), so they run one at a time,
        # each on freshly reset demo data, after the concurrent cases have finished.
        concurrent = [(c, r) for c, r in todo if not c.get("expect", {}).get("decision")]
        serial = [(c, r) for c, r in todo if c.get("expect", {}).get("decision")]
        await asyncio.gather(*(guarded(c, r) for c, r in concurrent))
        for case, rep in serial:
            await in_thread(lambda: supabase_client().rpc("reset_demo_data").execute())
            await attempt(case, rep)
        agent.tracer.flush()

    summary = summarize(out, args.variant)
    print("\n" + (out / "summary.md").read_text(encoding="utf-8"))
    if summary["errors"]:
        print(f"{summary['errors']} attempt(s) failed to produce a gradable result; see errors.jsonl. "
              "Re-run the same command to retry just those.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--variant", default="baseline", help="output directory name: baseline, v1, v2, ...")
    parser.add_argument("--reps", type=int, default=1, help="runs per case")
    parser.add_argument("--only", help="comma-separated case ids")
    parser.add_argument("--concurrency", type=int, default=3)
    parser.add_argument("--timeout-s", type=float, default=420, help="wall-clock limit per case")
    parser.add_argument("--approve-harness", action="store_true", help="record the current eval code as reviewed")
    parser.add_argument("--check-harness", action="store_true", help="only check the harness gate (for CI)")
    parser.add_argument("--selftest", action="store_true", help="check the graders on known-good and known-bad outputs")
    args = parser.parse_args()
    if args.variant != "baseline" and not (args.variant.startswith("v") and args.variant[1:].isdigit()):
        raise SystemExit("--variant must be baseline or v<N> (the report builder ignores other names)")
    sys.stdout.reconfigure(encoding="utf-8")

    if args.approve_harness:
        check_harness(approve=True)
        return
    check_harness(approve=False)
    if args.check_harness:
        print("Harness matches the approved version.")
        return
    if args.selftest:
        from evals.selftest import run_selftest

        sys.exit(asyncio.run(run_selftest()))
    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()
