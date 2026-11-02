"""The agent loop, with human approval for risky tools.

A turn streams Claude's reply and runs tools until Claude is done. When Claude calls
a risky tool, the loop records an approval request, holds the turn's other tool
results in conversation.pending_turn, and stops with status "awaiting_approval".
When every approval in the turn is decided, resume_after_decisions() runs the
approved tools, sends all the results back to Claude, and continues the loop.

The full message history is stored in Supabase, so a paused conversation survives
restarts and can be resumed by a later request.
"""

import json
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any

import anthropic

from agent import guardrails, store
from agent.models import AGENT_MODEL, fallback_args
from agent.pricing import usage_dict
from agent.prompts import system_blocks
from agent.store import in_thread
from agent.tools import RISKY_TOOLS, STATUS_LABELS, ApprovalNeeded, Toolbox, ToolResult
from agent.tracing import Tracer

MODEL = AGENT_MODEL
MAX_TOOL_ROUNDS = 12  # per turn, as a backstop against loops
INTERRUPTED = "This tool call was interrupted by an internal error and did not complete."
ONE_AT_A_TIME = ("Not requested: another action in this reply is already waiting for a supervisor's review. "
                 "Request this one, if it's still needed, after that result is in.")
Emit = Callable[[dict], Awaitable[None]]
log = logging.getLogger("agent")


async def _ignore(_: dict) -> None:
    pass


class Agent:
    def __init__(self, client: anthropic.AsyncAnthropic, toolbox: Toolbox, tracer: Tracer | None = None):
        self.client = client
        self.toolbox = toolbox
        self.tracer = tracer or Tracer()

    async def handle_user_message(self, conversation: dict, text: str, emit: Emit = _ignore) -> None:
        conversation["messages"].append({"role": "user", "content": text})
        with self.tracer.turn("chat-turn", conversation, input=text):
            await self._run(conversation, emit)

    async def resume_after_decisions(self, conversation: dict, emit: Emit = _ignore) -> bool:
        """If every approval in the paused turn is decided, finish the turn. Returns True if it resumed.

        Safe to call again after a failure: each approval's stored status says what already happened,
        so an action that ran is never run twice or reported as rejected. An unexpected error while
        running an approved action propagates, leaving it "approved" and the conversation paused,
        so the caller can retry.
        """
        pending = conversation["pending_turn"]
        approvals = {a["tool_use_id"]: a for a in await in_thread(store.list_approvals, None, conversation["id"])}
        if any(approvals[i]["status"] == "pending" for i in pending["awaiting"]):
            return False

        decided = {i: approvals[i]["status"] for i in pending["awaiting"]}
        with self.tracer.turn("resume-after-approval", conversation, input=decided):
            results = pending["results"]
            for tool_use_id in pending["awaiting"]:
                outcome = await self._approval_outcome(approvals[tool_use_id], conversation, emit)
                results[tool_use_id] = outcome.as_block(tool_use_id)

            conversation["messages"].append({"role": "user", "content": [results[i] for i in pending["order"]]})
            conversation["pending_turn"] = None
            conversation["status"] = "active"
            await self._run(conversation, emit)
        return True

    async def _approval_outcome(self, approval: dict, conversation: dict, emit: Emit) -> ToolResult:
        """The tool result Claude gets for a decided approval, running the action first if it's approved.

        The result says what happened in words: to Claude, the tool call just returned, with no sign
        a human was involved.
        """
        name, status = approval["tool_name"], approval["status"]
        if status == "approved":
            await emit({"type": "tool", "name": name, "status": "running", "label": STATUS_LABELS[name]})
            with self.tracer.tool(name, input={**_model_input(approval), "approval_id": approval["id"]}) as span:
                result = await self.toolbox.run(name, _model_input(approval), conversation, approval_id=approval["id"])
                span.update(output=result.content, level="ERROR" if result.is_error else "DEFAULT")
            await emit({"type": "tool", "name": name, "status": "error" if result.is_error else "done"})
            if result.is_error:  # refused by the tool or database (e.g. over the refundable amount)
                await in_thread(store.mark_approval_failed, approval["id"], str(result.content))
                status, approval["result"] = "failed", {"error": str(result.content)}
            else:  # the database marked it executed
                status, approval["result"] = "executed", json.loads(result.content)

        if status == "executed":
            done = "The refund has been issued" if name == "issue_refund" else "The email has been sent"
            return ToolResult(f"A support supervisor approved this request and it is complete. {done}. "
                              f"Record: {json.dumps(approval['result'], default=str)}")
        if status == "failed":
            error = (approval.get("result") or {}).get("error", "unknown error")
            return ToolResult(f"A support supervisor approved this, but it failed: {error}", is_error=True)
        note = f" Reviewer's note: {approval['reviewer_note']}" if approval.get("reviewer_note") else ""
        return ToolResult(f"A support supervisor rejected this action, so it was not carried out.{note}",
                          is_error=True)

    async def _run(self, conversation: dict, emit: Emit) -> None:
        """Run Claude until the turn ends. Errors are reported to the client, never raised, and the
        conversation is always saved in a state the next request can continue from."""
        messages = conversation["messages"]
        try:
            customer = await in_thread(store.get_customer_by_email, conversation["customer_email"])
            system = system_blocks(customer["name"], customer["email"])
            for _ in range(MAX_TOOL_ROUNDS):
                response = await self._stream(system, messages, emit)
                content, tool_uses = _history_content(response.content)

                if response.stop_reason == "refusal" or (response.stop_reason == "max_tokens" and tool_uses):
                    # Don't run tools from a declined or cut-off reply, and keep no unanswered tool_use in
                    # history (the next request would be rejected). Keep any text so the history stays valid.
                    kept = [b for b in content if b["type"] != "tool_use"]
                    messages.append({"role": "assistant", "content": kept or "Sorry, I can't help with that."})
                    await emit({"type": "error", "message": "The request was declined." if response.stop_reason
                                == "refusal" else "The reply was too long and got cut off."})
                    break
                messages.append({"role": "assistant", "content": content})
                if not tool_uses:
                    await self._check_reply(conversation, customer, content, emit)
                    break

                results, awaiting = await self._run_tools(conversation, tool_uses, emit)
                if awaiting:
                    conversation["pending_turn"] = {
                        "order": [t.id for t in tool_uses],
                        "results": results,
                        "awaiting": awaiting,
                    }
                    conversation["status"] = "awaiting_approval"
                    break
                messages.append({"role": "user", "content": [results[t.id] for t in tool_uses]})
            else:
                await emit({"type": "error", "message": "Stopped after too many tool calls."})
        except Exception:
            log.exception("agent turn failed")
            await emit({"type": "error", "message": "Something went wrong. Please try again."})
        finally:
            _close_dangling_tool_uses(conversation)
            await in_thread(store.save_conversation, conversation)
            await emit({"type": "done", "status": conversation["status"]})

    async def _stream(self, system: list[dict], messages: list[dict], emit: Emit):
        await emit({"type": "status", "text": "Thinking"})
        for attempt in range(3):
            try:
                started = time.monotonic()
                with self.tracer.generation("claude", MODEL, input=messages[-1]) as generation:
                    async with self.client.beta.messages.stream(
                        model=MODEL,
                        # A cap, not a cost: replies plus thinking run well under 2K tokens, and this
                        # stops a runaway generation early.
                        max_tokens=16000,
                        system=system,
                        tools=self.toolbox.claude_tools(),
                        messages=messages,
                        output_config={"effort": "medium"},
                        cache_control={"type": "ephemeral"},
                        **fallback_args(MODEL),
                    ) as stream:
                        async for event in stream:
                            if event.type == "text":
                                await emit({"type": "text", "delta": event.text})
                        message = await stream.get_final_message()
                    self.tracer.record_generation(generation, message)
                # For evals and monitoring: which model served the call, its tokens, and how long it took.
                await emit({"type": "model_call", "model": message.model, "usage": usage_dict(message.usage),
                            "stop_reason": message.stop_reason, "latency_s": round(time.monotonic() - started, 2)})
                sources = _cited_sources(b.model_dump(mode="json") for b in message.content)
                if sources:
                    await emit({"type": "sources", "items": sources})
                return message
            except ValueError:
                # Tool input JSON the SDK couldn't parse at all (possible with eager input streaming).
                # Nothing was appended to history, so re-issue the turn; "retry" tells the client to
                # discard the text this attempt already streamed.
                if attempt == 2:
                    raise
                await emit({"type": "retry"})

    async def _run_tools(self, conversation: dict, tool_uses: list, emit: Emit) -> tuple[dict, list[str]]:
        """Run (or hold for approval) each tool call. Every call gets a result, even if its tool fails."""
        results: dict[str, Any] = {}
        awaiting: list[str] = []
        for tool_use in tool_uses:
            error = self.toolbox.validate(tool_use.name, tool_use.input)
            if error:
                results[tool_use.id] = ToolResult(error, is_error=True).as_block(tool_use.id)
                continue

            label = STATUS_LABELS.get(tool_use.name, tool_use.name)
            if tool_use.name == "get_order":
                label += f" #{str(tool_use.input['order_number']).lstrip('#')}"
            await emit({"type": "tool", "name": tool_use.name, "status": "running", "label": label})

            with self.tracer.tool(tool_use.name, input=tool_use.input) as span:
                try:
                    if tool_use.name in RISKY_TOOLS:
                        check = await self.toolbox.check_risky(tool_use.name, tool_use.input, conversation)
                        if isinstance(check, ApprovalNeeded) and awaiting:
                            # One approval per pause, so an email confirming a refund is written after the
                            # refund's outcome is known, not alongside the request.
                            result = ToolResult(ONE_AT_A_TIME, is_error=True)
                        elif isinstance(check, ApprovalNeeded):
                            approval = await in_thread(store.create_approval, conversation["id"], tool_use.id,
                                                       check.tool_name, check.tool_input, check.summary)
                            awaiting.append(tool_use.id)
                            results[tool_use.id] = None  # filled in after the decision
                            span.update(output={"approval_requested": approval["id"], "summary": check.summary})
                            await emit({"type": "approval", "id": approval["id"], "tool_name": check.tool_name,
                                        "summary": check.summary})
                            continue
                        else:
                            result = check
                    else:
                        result = await self.toolbox.run(tool_use.name, tool_use.input, conversation)
                except Exception:
                    # A network or database error. Claude gets an error result instead of the turn crashing,
                    # which would leave a tool_use with no tool_result and break the conversation.
                    log.exception("tool %s failed", tool_use.name)
                    result = ToolResult(INTERRUPTED, is_error=True)
                span.update(output=result.content, level="ERROR" if result.is_error else "DEFAULT")

            results[tool_use.id] = result.as_block(tool_use.id)
            await emit({"type": "tool", "name": tool_use.name, "status": "error" if result.is_error else "done"})
        return results, awaiting

    async def _check_reply(self, conversation: dict, customer: dict, content: list[dict], emit: Emit) -> None:
        """Output guardrails on a final reply: redact other people's contact details, flag unconfirmed claims."""
        text = "".join(b["text"] for b in content if b["type"] == "text")
        leaked = guardrails.foreign_personal_data(text, customer["email"], customer.get("phone"))
        if leaked:
            # The text already streamed; the stored copy (what the chat reloads) is redacted.
            for block in content:
                if block["type"] == "text":
                    block["text"] = guardrails.redact(block["text"], leaked)
                    block.pop("citations", None)  # citations point at the unredacted text
            log.warning("guardrail: redacted %d contact detail(s) from a reply", len(leaked))
            self.tracer.event("guardrail:personal-data", as_type="guardrail", level="WARNING",
                              metadata={"redacted": len(leaked)})
            await emit({"type": "guardrail", "kind": "personal_data",
                        "message": "Part of this reply was hidden to protect someone's personal information."})

        claimed = guardrails.unconfirmed_claims(text, executed_tools=set())
        if claimed:
            # Only look up approvals when the text makes a claim (rare), then check it against what really ran.
            approvals = await in_thread(store.list_approvals, ["executed"], conversation["id"])
            claimed = guardrails.unconfirmed_claims(text, {a["tool_name"] for a in approvals})
        if claimed:
            log.warning("guardrail: reply claims %s without an executed approval", claimed)
            self.tracer.event("guardrail:unconfirmed-claim", as_type="guardrail", level="WARNING",
                              metadata={"claims": claimed})
            await emit({"type": "guardrail", "kind": "unconfirmed_claim", "claims": claimed})


def _close_dangling_tool_uses(conversation: dict) -> None:
    """If a turn stopped right after Claude asked for tools (an error mid-turn), answer those calls with
    errors. The Messages API rejects any history with a tool_use that has no tool_result."""
    if conversation["status"] == "awaiting_approval":
        return  # the results are held in pending_turn until the approvals are decided
    messages = conversation["messages"]
    last = messages[-1] if messages else None
    if not last or last["role"] != "assistant" or isinstance(last["content"], str):
        return
    ids = [b["id"] for b in last["content"] if b["type"] == "tool_use"]
    if ids:
        messages.append({"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": i, "content": INTERRUPTED, "is_error": True} for i in ids
        ]})


def _history_content(blocks) -> tuple[list[dict], list]:
    """Turn response blocks into history content, and pick out the tool calls to run.

    After a mid-answer fallback to another model, thinking and tool_use blocks before the
    last fallback block belong to the declined attempt: they're left out of history and
    never run.
    """
    boundary = max((i for i, b in enumerate(blocks) if b.type == "fallback"), default=-1)
    content, tool_uses = [], []
    for i, block in enumerate(blocks):
        if i < boundary and block.type in ("thinking", "redacted_thinking", "tool_use"):
            continue
        content.append(block.model_dump(mode="json", exclude_none=True))
        if block.type == "tool_use":
            tool_uses.append(block)
    return content, tool_uses


def _cited_sources(blocks) -> list[str]:
    """The distinct knowledge-base sections cited by a message's text blocks, in order."""
    sources: list[str] = []
    for block in blocks:
        if block.get("type") != "text":
            continue
        for citation in block.get("citations") or []:
            label = citation.get("title") or citation.get("source")
            if label and label not in sources:
                sources.append(label)
    return sources


def _model_input(approval: dict) -> dict:
    """The approved input, as Claude's tool schema shapes it (the agent adds hidden fields itself)."""
    tool_input = dict(approval["tool_input"])
    if approval["tool_name"] == "send_email":
        tool_input.pop("to", None)
    return tool_input


def transcript(conversation: dict, approvals: list[dict]) -> list[dict]:
    """The conversation as the chat UI shows it: user and assistant messages, tool steps, and sources."""
    by_tool_use = {a["tool_use_id"]: a for a in approvals}
    items: list[dict] = []
    for message in conversation["messages"]:
        if message["role"] == "user":
            if isinstance(message["content"], str):
                items.append({"role": "user", "text": message["content"]})
            continue
        content = message["content"]
        if isinstance(content, str):
            items.append({"role": "assistant", "text": content, "sources": []})
            continue
        text, text_blocks = "", []

        def flush():
            nonlocal text, text_blocks
            if text.strip():
                items.append({"role": "assistant", "text": text.strip(), "sources": _cited_sources(text_blocks)})
            text, text_blocks = "", []

        for block in content:
            if block["type"] == "text":
                text += block["text"]
                text_blocks.append(block)
            elif block["type"] == "tool_use":
                flush()  # text before a tool call is shown before the tool step
                step = {"role": "tool", "name": block["name"], "label": STATUS_LABELS.get(block["name"], block["name"])}
                if block["id"] in by_tool_use:
                    a = by_tool_use[block["id"]]
                    step["approval"] = {"id": a["id"], "status": a["status"], "summary": a["summary"]}
                items.append(step)
        flush()
    return items
