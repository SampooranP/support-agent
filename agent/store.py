"""Conversations and approval requests in Supabase.

These functions are synchronous (the Supabase client is); the async agent code
calls them through anyio.to_thread.
"""

from datetime import datetime, timezone
from typing import Any

from ingestion.config import supabase_client


def _db():
    return supabase_client()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_customer_by_email(email: str) -> dict | None:
    rows = _db().table("customers").select("id, name, email").eq("email", email.strip().lower()).execute().data
    return rows[0] if rows else None


def list_demo_customers() -> list[dict]:
    return _db().table("customers").select("id, name, email").order("id").execute().data


def create_conversation(customer_email: str) -> dict:
    return _db().table("conversations").insert({"customer_email": customer_email}).execute().data[0]


def get_conversation(conversation_id: str) -> dict | None:
    rows = _db().table("conversations").select("*").eq("id", conversation_id).execute().data
    return rows[0] if rows else None


def save_conversation(conversation: dict) -> None:
    _db().table("conversations").update({
        "messages": conversation["messages"],
        "status": conversation["status"],
        "pending_turn": conversation["pending_turn"],
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


def get_approval(approval_id: str) -> dict | None:
    rows = _db().table("approval_requests").select("*").eq("id", approval_id).execute().data
    return rows[0] if rows else None


def list_approvals(status: str | None = None, conversation_id: str | None = None) -> list[dict]:
    query = _db().table("approval_requests").select("*").order("created_at", desc=True).limit(200)
    if status:
        query = query.eq("status", status)
    if conversation_id:
        query = query.eq("conversation_id", conversation_id)
    return query.execute().data


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


def mark_approval_failed(approval_id: str, error: str) -> None:
    _db().table("approval_requests").update({"status": "failed", "result": {"error": error}}).eq("id", approval_id).execute()
