"""Daily spend cap for the agent API.

Every Claude call the API makes (the router and the agent, including resumes after an approval) adds its
cost to today's total in Supabase (the daily_spend table, per UTC day). Once the total reaches
DAILY_SPEND_CAP_USD, new customer messages are refused until the next day. A turn already running is
allowed to finish, and so is a resume after an approval, so the cap can be passed by one turn's cost.
"""

import logging
import os
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

from agent.pricing import cost_usd
from agent.store import _db, in_thread

log = logging.getLogger("agent")

CAP_USD = float(os.getenv("DAILY_SPEND_CAP_USD", "5"))  # 0 turns the cap off
UNPRICED_MODEL = "claude-opus-5"  # an unknown model is charged at the highest known price

Emit = Callable[[dict], Awaitable[None]]


def spent_today() -> float:
    today = datetime.now(UTC).date().isoformat()
    rows = _db().table("daily_spend").select("usd").eq("day", today).execute().data
    return float(rows[0]["usd"]) if rows else 0.0


def add(usd: float) -> float:
    """Add to today's total and return the new total. Not retried: a retry could count a call twice."""
    return float(_db().rpc("add_spend", {"p_usd": round(usd, 6)}).execute().data)


async def over_cap() -> bool:
    return CAP_USD > 0 and await in_thread(spent_today) >= CAP_USD


def call_cost(event: dict) -> float:
    """The cost of the Claude call an event reports (model_call and route events), else 0."""
    if event["type"] not in ("model_call", "route") or not event.get("model"):
        return 0.0
    cost = cost_usd(event["model"], event["usage"])
    return cost if cost is not None else cost_usd(UNPRICED_MODEL, event["usage"])


def metered(emit: Emit) -> Emit:
    """Wrap an agent's emit so each Claude call it reports is added to today's spend."""

    async def wrapped(event: dict) -> None:
        if cost := call_cost(event):
            try:
                await in_thread(add, cost)
            except Exception:
                log.exception("couldn't record spend of $%.4f", cost)  # never fail the customer's turn over it
        await emit(event)

    return wrapped
