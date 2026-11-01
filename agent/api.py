"""HTTP API for the support agent: chat (streamed) and human approvals.

Run from the repo root:
    uvicorn agent.api:app --reload --port 8000

Endpoints:
    GET  /customers                      demo customers to sign in as
    POST /conversations                  start a conversation for a customer
    GET  /conversations/{id}             transcript, status and approvals
    POST /conversations/{id}/messages    send a message; the reply streams as server-sent events
    GET  /approvals?status=pending       approval queue for the dashboard
    POST /approvals/{id}/decision        approve or reject; the conversation then resumes

Stream events (one JSON object per `data:` line):
    {"type": "status", "text": "Thinking"}
    {"type": "text", "delta": "..."}
    {"type": "tool", "name": "get_order", "status": "running" | "done" | "error", "label": "..."}
    {"type": "approval", "id": "...", "tool_name": "issue_refund", "summary": "..."}
    {"type": "sources", "items": ["refund-policy.md - Damaged or defective items", ...]}
    {"type": "error", "message": "..."}
    {"type": "done", "status": "active" | "awaiting_approval"}
"""

import asyncio
import json
import logging
import sys
from collections import defaultdict
from contextlib import asynccontextmanager

import anthropic
import anyio
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from mcp import Client, StdioServerParameters
from pydantic import BaseModel, Field

from agent import store
from agent.loop import Agent, transcript
from agent.tools import Toolbox
from ingestion.config import REPO_ROOT, require_env

logging.getLogger("httpx").setLevel(logging.WARNING)
log = logging.getLogger("agent")

MCP_SERVER = REPO_ROOT / "mcp-server" / "server.py"

# One agent run at a time per conversation (a new message, or a resume after approval).
conversation_locks: defaultdict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
background_tasks: set[asyncio.Task] = set()


@asynccontextmanager
async def lifespan(app: FastAPI):
    client = anthropic.AsyncAnthropic(api_key=require_env("ANTHROPIC_API_KEY"))
    async with Client(StdioServerParameters(command=sys.executable, args=[str(MCP_SERVER)])) as mcp:
        app.state.agent = Agent(client, await Toolbox.connect(mcp))
        yield


app = FastAPI(title="Lumen & Pine support agent", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class NewConversation(BaseModel):
    customer_email: str


class NewMessage(BaseModel):
    text: str = Field(min_length=1, max_length=4000)


class Decision(BaseModel):
    approved: bool
    reviewer: str = Field(min_length=1, max_length=100)
    note: str | None = Field(default=None, max_length=1000)


async def _thread(fn, *args):
    return await anyio.to_thread.run_sync(lambda: fn(*args))


async def _conversation_or_404(conversation_id: str) -> dict:
    conversation = await _thread(store.get_conversation, conversation_id)
    if not conversation:
        raise HTTPException(404, "Conversation not found")
    return conversation


@app.get("/customers")
async def customers():
    return await _thread(store.list_demo_customers)


@app.post("/conversations", status_code=201)
async def create_conversation(body: NewConversation):
    customer = await _thread(store.get_customer_by_email, body.customer_email)
    if not customer:
        raise HTTPException(404, "No customer with that email")
    conversation = await _thread(store.create_conversation, customer["email"])
    return {"id": conversation["id"], "customer": customer}


@app.get("/conversations/{conversation_id}")
async def get_conversation(conversation_id: str):
    conversation = await _conversation_or_404(conversation_id)
    approvals = await _thread(store.list_approvals, None, conversation_id)
    customer = await _thread(store.get_customer_by_email, conversation["customer_email"])
    return {
        "id": conversation["id"],
        "status": conversation["status"],
        "customer": customer,
        "items": transcript(conversation, approvals),
        "approvals": approvals,
    }


@app.post("/conversations/{conversation_id}/messages")
async def send_message(conversation_id: str, body: NewMessage):
    lock = conversation_locks[conversation_id]
    if lock.locked():
        raise HTTPException(409, "The agent is still working on the last message")
    await lock.acquire()
    try:
        conversation = await _conversation_or_404(conversation_id)
        if conversation["status"] == "awaiting_approval":
            raise HTTPException(409, "Waiting for a support agent to review a pending action")
    except BaseException:
        lock.release()
        raise

    queue: asyncio.Queue[dict | None] = asyncio.Queue()

    async def run():
        try:
            await app.state.agent.handle_user_message(conversation, body.text, queue.put)
        except Exception:
            log.exception("agent run failed")
            await queue.put({"type": "error", "message": "Something went wrong. Please try again."})
            await queue.put({"type": "done", "status": conversation["status"]})
        finally:
            lock.release()
            await queue.put(None)

    # The run continues even if the client disconnects, so the conversation is always saved.
    task = asyncio.create_task(run())
    background_tasks.add(task)
    task.add_done_callback(background_tasks.discard)

    async def events():
        while (event := await queue.get()) is not None:
            yield f"data: {json.dumps(event)}\n\n"

    return StreamingResponse(events(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})


@app.get("/approvals")
async def approvals(status: str | None = "pending"):
    rows = await _thread(store.list_approvals, status, None)
    emails = {}
    for row in rows:
        if row["conversation_id"] not in emails:
            conversation = await _thread(store.get_conversation, row["conversation_id"])
            emails[row["conversation_id"]] = conversation["customer_email"] if conversation else None
        row["customer_email"] = emails[row["conversation_id"]]
    return rows


@app.post("/approvals/{approval_id}/decision")
async def decide(approval_id: str, body: Decision):
    approval = await _thread(store.get_approval, approval_id)
    if not approval:
        raise HTTPException(404, "Approval not found")
    decided = await _thread(store.decide_approval, approval_id, body.approved, body.reviewer, body.note)
    if not decided:
        raise HTTPException(409, f"This request was already {approval['status']}")

    async def resume():
        async with conversation_locks[approval["conversation_id"]]:
            conversation = await _thread(store.get_conversation, approval["conversation_id"])
            if conversation and conversation["status"] == "awaiting_approval":
                try:
                    await app.state.agent.resume_after_decisions(conversation)
                except Exception:
                    log.exception("resume after approval failed")

    task = asyncio.create_task(resume())
    background_tasks.add(task)
    task.add_done_callback(background_tasks.discard)
    return decided
