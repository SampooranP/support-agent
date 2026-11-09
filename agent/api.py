"""HTTP API for the support agent: chat (streamed) and human approvals.

Run from the repo root:
    uvicorn agent.api:app --reload --port 8000

Every endpoint except /health needs the X-Agent-Secret header when AGENT_API_SECRET is set (it always
is in deployment). Only the Next.js server calls this API, so there's no CORS: browsers can't call it.

Endpoints:
    GET  /health                         liveness check for the load balancer (no secret needed)
    GET  /customers                      demo customers to sign in as
    POST /conversations                  start a conversation for a customer
    GET  /conversations/{id}             transcript, status, specialist and approvals
    POST /conversations/{id}/messages    send a message; the reply streams as server-sent events
    GET  /approvals?status=pending       approval queue (status: one or more, comma-separated; empty = all)
    POST /approvals/{id}/decision        approve or reject; the conversation then resumes
    GET  /tickets                        support tickets the agent opened, newest first

Stream events (one JSON object per `data:` line):
    {"type": "status", "text": "Thinking"}
    {"type": "text", "delta": "..."}
    {"type": "retry"}                    discard the text streamed since the last "status"
    {"type": "tool", "name": "get_order", "status": "running" | "done" | "error", "label": "..."}
    {"type": "route", "specialist": "billing", "title": "Billing", "changed": true, "model": "...", "usage": {...}}
    {"type": "approval", "id": "...", "tool_name": "issue_refund", "summary": "..."}
    {"type": "sources", "items": ["refund-policy.md - Damaged or defective items", ...]}
    {"type": "model_call", "model": "...", "usage": {...}, "stop_reason": "...", "latency_s": 4.2}
    {"type": "guardrail", "kind": "personal_data" | "unconfirmed_claim", ...}
    {"type": "error", "message": "..."}
    {"type": "done", "status": "active" | "awaiting_approval"}   always last, exactly once
"""

import asyncio
import hmac
import json
import logging
import os
import time
import weakref
from collections.abc import Coroutine
from contextlib import asynccontextmanager

import anthropic
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse
from mcp import Client
from pydantic import BaseModel, Field

from agent import spend, store
from agent.guardrails import RateLimiter
from agent.loop import Agent, transcript
from agent.store import in_thread
from agent.tools import Toolbox, mcp_server_params
from agent.tracing import Tracer
from ingestion.config import require_env

logging.getLogger("httpx").setLevel(logging.WARNING)
log = logging.getLogger("agent")

RESUME_RETRY_SECONDS = 15  # after a failed resume, wait this long before trying again
API_SECRET = os.getenv("AGENT_API_SECRET", "")

# Guardrail: cap how fast one conversation, or one customer across conversations, can send messages.
per_conversation_limit = RateLimiter(limit=10, window_s=300)
per_customer_limit = RateLimiter(limit=40, window_s=3600)

# One agent run at a time per conversation (a new message, or a resume after approval). The dict holds
# locks weakly, so a conversation's lock is dropped as soon as nothing is using it.
_conversation_locks: weakref.WeakValueDictionary[str, asyncio.Lock] = weakref.WeakValueDictionary()
_resume_failed_at: dict[str, float] = {}
_resume_requested: set[str] = set()  # conversations that need a resume check
_resume_running: set[str] = set()  # conversations with a resume worker running
_background_tasks: set[asyncio.Task] = set()


def conversation_lock(conversation_id: str) -> asyncio.Lock:
    lock = _conversation_locks.get(conversation_id)
    if lock is None:
        lock = _conversation_locks[conversation_id] = asyncio.Lock()
    return lock


def spawn(coro: Coroutine) -> None:
    """Run a coroutine in the background, keeping a reference so it isn't garbage-collected mid-run."""
    task = asyncio.create_task(coro)
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)


def schedule_resume(conversation_id: str) -> None:
    """Resume a paused conversation whose approvals are all decided, in the background.

    Called after each decision, whenever a paused conversation is viewed, and at startup, so a resume
    that failed (Claude overloaded, a restart mid-resume) is retried instead of leaving the
    conversation stuck.
    """
    failed_at = _resume_failed_at.get(conversation_id)
    if failed_at and time.monotonic() - failed_at < RESUME_RETRY_SECONDS:
        return
    _resume_requested.add(conversation_id)
    if conversation_id in _resume_running:
        return  # the running worker checks again when it finishes (e.g. a second approval just got decided)
    _resume_running.add(conversation_id)

    async def worker():
        lock = conversation_lock(conversation_id)
        try:
            while conversation_id in _resume_requested:
                _resume_requested.discard(conversation_id)
                async with lock:
                    conversation = await in_thread(store.get_conversation, conversation_id)
                    if not conversation or conversation["status"] != "awaiting_approval":
                        continue
                    try:
                        await app.state.agent.resume_after_decisions(conversation, spend.metered(_discard))
                        _resume_failed_at.pop(conversation_id, None)
                    except Exception:
                        log.exception("resume after approval failed; will retry")
                        _resume_failed_at[conversation_id] = time.monotonic()
                        break
        finally:
            _resume_running.discard(conversation_id)
            _resume_requested.discard(conversation_id)

    spawn(worker())


async def _discard(_: dict) -> None:
    pass


def all_decided(conversation: dict, approvals: list[dict]) -> bool:
    pending = conversation.get("pending_turn") or {}
    statuses = {a["tool_use_id"]: a["status"] for a in approvals}
    return conversation["status"] == "awaiting_approval" and all(
        statuses.get(i) not in (None, "pending") for i in pending.get("awaiting", [])
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    client = anthropic.AsyncAnthropic(api_key=require_env("ANTHROPIC_API_KEY"))
    tracer = Tracer()
    if not API_SECRET:
        log.warning("AGENT_API_SECRET isn't set: the API accepts requests from anyone who can reach it")
    log.info("Langfuse tracing is %s", "on" if tracer.enabled else "off (no LANGFUSE_* keys)")
    async with Client(mcp_server_params()) as mcp:
        app.state.agent = Agent(client, await Toolbox.connect(mcp), tracer)
        # Finish any conversation whose resume was interrupted by a restart.
        for conversation in await in_thread(store.list_awaiting_conversations):
            schedule_resume(conversation["id"])
        try:
            yield
        finally:
            tracer.flush()


app = FastAPI(title="Lumen & Pine support agent", lifespan=lifespan)


@app.middleware("http")
async def require_secret(request: Request, call_next):
    if API_SECRET and request.url.path != "/health":
        if not hmac.compare_digest(request.headers.get("x-agent-secret", "").encode(), API_SECRET.encode()):
            return JSONResponse({"detail": "Missing or wrong X-Agent-Secret header"}, status_code=401)
    return await call_next(request)


class NewConversation(BaseModel):
    customer_email: str


class NewMessage(BaseModel):
    text: str = Field(min_length=1, max_length=4000)


class Decision(BaseModel):
    approved: bool
    reviewer: str = Field(min_length=1, max_length=100)
    note: str | None = Field(default=None, max_length=1000)


async def _conversation_or_404(conversation_id: str) -> dict:
    conversation = await in_thread(store.get_conversation, conversation_id)
    if not conversation:
        raise HTTPException(404, "Conversation not found")
    return conversation


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/customers")
async def customers():
    return await in_thread(store.list_demo_customers)


@app.post("/conversations", status_code=201)
async def create_conversation(body: NewConversation):
    customer = await in_thread(store.get_customer_by_email, body.customer_email)
    if not customer:
        raise HTTPException(404, "No customer with that email")
    conversation = await in_thread(store.create_conversation, customer["email"])
    return {"id": conversation["id"], "customer": customer}


@app.get("/conversations/{conversation_id}")
async def get_conversation(conversation_id: str):
    conversation = await _conversation_or_404(conversation_id)
    approvals = await in_thread(store.list_approvals, None, conversation_id)
    if all_decided(conversation, approvals):
        schedule_resume(conversation_id)  # e.g. an earlier resume failed; the chat polls this endpoint
    customer = await in_thread(store.get_customer_by_email, conversation["customer_email"])
    return {
        "id": conversation["id"],
        "status": conversation["status"],
        "specialist": conversation.get("specialist"),
        "customer": customer,
        "items": transcript(conversation, approvals),
        "approvals": approvals,
    }


@app.post("/conversations/{conversation_id}/messages")
async def send_message(conversation_id: str, body: NewMessage):
    conversation = await _conversation_or_404(conversation_id)
    lock = conversation_lock(conversation_id)
    if lock.locked():
        raise HTTPException(409, "The agent is still working on the last message")
    if not (per_conversation_limit.allow(conversation_id) and per_customer_limit.allow(conversation["customer_email"])):
        raise HTTPException(429, "You're sending messages too quickly. Please wait a few minutes and try again.")
    if await spend.over_cap():
        raise HTTPException(503, "The demo has used up today's budget for AI calls. Please try again tomorrow.")
    await lock.acquire()
    try:
        conversation = await _conversation_or_404(conversation_id)  # re-read now that we hold the lock
        if conversation["status"] == "awaiting_approval":
            raise HTTPException(409, "Waiting for a support agent to review a pending action")
    except BaseException:
        lock.release()
        raise

    queue: asyncio.Queue[dict | None] = asyncio.Queue()
    sent_done = False

    async def emit(event: dict) -> None:
        nonlocal sent_done
        sent_done = sent_done or event["type"] == "done"
        await queue.put(event)

    async def run():
        try:
            await app.state.agent.handle_user_message(conversation, body.text, spend.metered(emit))
        except Exception:
            # The agent reports its own errors; this only catches failures outside its turn handling.
            log.exception("agent run failed")
            if not sent_done:
                await emit({"type": "error", "message": "Something went wrong. Please try again."})
                await emit({"type": "done", "status": conversation["status"]})
        finally:
            lock.release()
            await queue.put(None)

    # The run continues even if the client disconnects, so the conversation is always saved.
    spawn(run())

    async def events():
        while (event := await queue.get()) is not None:
            yield f"data: {json.dumps(event)}\n\n"

    return StreamingResponse(events(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})


@app.get("/approvals")
async def approvals(status: str = "pending", limit: int = Query(200, ge=1, le=200)):
    statuses = [s.strip() for s in status.split(",") if s.strip()] or None
    return await in_thread(store.list_approvals, statuses, None, limit)


@app.get("/tickets")
async def tickets(limit: int = Query(100, ge=1, le=200)):
    return await in_thread(store.list_tickets, limit)


@app.post("/approvals/{approval_id}/decision")
async def decide(approval_id: str, body: Decision):
    approval = await in_thread(store.get_approval, approval_id)
    if not approval:
        raise HTTPException(404, "Approval not found")
    decided = await in_thread(store.decide_approval, approval_id, body.approved, body.reviewer, body.note)
    if not decided:
        raise HTTPException(409, f"This request was already {approval['status']}")
    schedule_resume(approval["conversation_id"])
    return decided
