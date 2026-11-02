"""Conversations and approval requests in Supabase.

These functions are synchronous (the Supabase client is); the async agent code
calls them through anyio.to_thread.
"""

import functools
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, TypeVar

import anyio
import httpx

from ingestion.config import supabase_client

T = TypeVar("T")
TRANSIENT_ERRORS = (httpx.RemoteProtocolError, httpx.ConnectError, httpx.ReadError)


def _retry_once(fn: Callable[..., T]) -> Callable[..., T]:
    """Retry a call once if the connection to Supabase dropped. Only for reads and idempotent writes."""

    @functools.wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> T:
        try:
            return fn(*args, **kwargs)
        except TRANSIENT_ERRORS:
            return fn(*args, **kwargs)

    return wrapper


async def in_thread(fn: Callable[..., T], *args: Any) -> T:
    """Run a blocking call (the Supabase client is synchronous) without blocking the event loop."""
    return await anyio.to_thread.run_sync(lambda: fn(*args))


def _db():
    return supabase_client()  # created once and reused (functools.cache in ingestion.config)


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _is_uuid(value: str) -> bool:
    try:
        uuid.UUID(value)
        return True
    except ValueError:
        return False


@_retry_once
def get_customer_by_email(email: str) -> dict | None:
    rows = _db().table("customers").select("id, name, email, phone").eq("email", email.strip().lower()).execute().data
    return rows[0] if rows else None


@_retry_once
def list_demo_customers() -> list[dict]:
    return _db().table("customers").select("id, name, email").order("id").execute().data


def create_conversation(customer_email: str) -> dict:
    return _db().table("conversations").insert({"customer_email": customer_email}).execute().data[0]


@_retry_once
def get_conversation(conversation_id: str) -> dict | None:
    if not _is_uuid(conversation_id):
        return None  # the column is a uuid; a malformed id would make Postgres raise
    rows = _db().table("conversations").select("*").eq("id", conversation_id).execute().data
    return rows[0] if rows else None


@_retry_once
def list_awaiting_conversations() -> list[dict]:
    return _db().table("conversations").select("*").eq("status", "awaiting_approval").execute().data


@_retry_once
def save_conversation(conversation: dict) -> None:
    _db().table("conversations").update({
        "messages": conversation["messages"],
        "status": conversation["status"],
        "pending_turn": conversation["pending_turn"],
        "specialist": conversation.get("specialist"),
        "updated_at": _now(),
    }).eq("id", conversation["id"]).execute()


def create_approval(conversation_id: str, tool_use_id: str, tool_name: str, tool_input: dict, summary: str) -> dict:
    return _db().table("approval_requests").insert({
        "conversation_id": conversation_id,
        "tool_use_id": tool_use_id,
        "tool_name": tool_name,
        "tool_input": tool_input,
        "summary": summary,
    }).execute().data[0]


@_retry_once
def get_approval(approval_id: str) -> dict | None:
    if not _is_uuid(approval_id):
        return None
    rows = _db().table("approval_requests").select("*").eq("id", approval_id).execute().data
    return rows[0] if rows else None


@_retry_once
def list_approvals(
    statuses: list[str] | None = None, conversation_id: str | None = None, limit: int = 200
) -> list[dict]:
    """Approvals, newest first, each with its conversation's customer_email (one request, via an embedded select)."""
    query = (
        _db()
        .table("approval_requests")
        .select("*, conversations(customer_email)")
        .order("created_at", desc=True)
        .limit(limit)
    )
    if statuses:
        query = query.in_("status", statuses)
    if conversation_id:
        query = query.eq("conversation_id", conversation_id)
    rows = query.execute().data
    for row in rows:
        row["customer_email"] = (row.pop("conversations") or {}).get("customer_email")
    return rows


@_retry_once
def decide_approval(approval_id: str, approved: bool, reviewer: str, note: str | None) -> dict | None:
    """Move a pending approval to approved/rejected. Returns None if it wasn't pending (already decided)."""
    rows = (
        _db()
        .table("approval_requests")
        .update({
            "status": "approved" if approved else "rejected",
            "reviewer": reviewer,
            "reviewer_note": note,
            "decided_at": _now(),
        })
        .eq("id", approval_id)
        .eq("status", "pending")  # only one decision can win
        .execute()
        .data
    )
    return rows[0] if rows else None


@_retry_once
def mark_approval_failed(approval_id: str, error: str) -> None:
    _db().table("approval_requests").update({"status": "failed", "result": {"error": error}}).eq("id", approval_id).execute()
