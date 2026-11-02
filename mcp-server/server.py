"""MCP server exposing Lumen & Pine customer-support tools, backed by Supabase.

Tools:
    get_order      look up an order by number, with its line items and customer
    get_customer   look up a customer by email or ID, with their recent orders
    create_ticket  open a support ticket for a human to follow up
    issue_refund   refund money on an order (requires a human approval)
    send_email     email a customer (requires a human approval)

issue_refund and send_email take an approval_id. The database checks that the
approval exists, was approved by a person, hasn't been used, and matches the
exact arguments, so these tools can't act without a human in the loop.

Run over stdio (how MCP clients such as Claude Desktop launch it):
    python mcp-server/server.py
"""

import logging
import re
from datetime import UTC, datetime
from typing import Any, Literal

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp_types import ToolAnnotations
from postgrest.exceptions import APIError

from db import supabase_client as db

logging.getLogger("httpx").setLevel(logging.WARNING)  # don't log every Supabase request URL

READ_ONLY = ToolAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=False)
WRITE = ToolAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=False, open_world_hint=False)
NEEDS_APPROVAL = ToolAnnotations(read_only_hint=False, destructive_hint=True, idempotent_hint=False, open_world_hint=True)
RECENT_ORDERS_LIMIT = 20

mcp = MCPServer(
    name="lumen-pine-support",
    instructions=(
        "Customer-support tools for Lumen & Pine, an online outdoor-gear and home-goods store. "
        "Look up orders and customers before answering questions about them. "
        "Times are UTC; money amounts are in the order's currency."
    ),
)


@mcp.tool(annotations=READ_ONLY)
def get_order(order_number: str) -> dict[str, Any]:
    """Look up an order by its order number, such as "1042" or "#1042".

    Returns the order's status, shipping method and address, carrier and tracking
    number, money amounts, key dates, line items (including whether each item is
    Final Sale), and the customer's ID, name and email. Also returns
    hours_since_placed and, for delivered orders, days_since_delivery, so you
    don't need to do date arithmetic against the refund and shipping policies.
    """
    number = _parse_order_number(order_number)
    rows = (
        db()
        .table("orders")
        .select("*, order_items(sku, product_name, quantity, unit_price, final_sale), customers(id, name, email)")
        .eq("order_number", number)
        .execute()
        .data
    )
    if not rows:
        raise ToolError(f"No order #{number} found. Check the number with the customer.")

    order = rows[0]
    order["items"] = order.pop("order_items")
    order["customer"] = order.pop("customers")
    del order["customer_id"]
    order["hours_since_placed"] = round(_age(order["placed_at"]).total_seconds() / 3600, 1)
    if order["delivered_at"]:
        order["days_since_delivery"] = _age(order["delivered_at"]).days
    return order


@mcp.tool(annotations=READ_ONLY)
def get_customer(email: str | None = None, customer_id: str | None = None) -> dict[str, Any]:
    """Look up a customer by email address or customer ID (such as "cus_001"). Give exactly one.

    Returns the customer's profile (name, email, phone, city, region, country,
    Trail Rewards points, account creation date) and their most recent orders,
    newest first, with each order's number, status, total, currency and dates.
    Use get_order for an order's line items and tracking details.
    """
    email = (email or "").strip().lower() or None
    customer_id = (customer_id or "").strip() or None
    if bool(email) == bool(customer_id):
        raise ToolError("Give exactly one of email or customer_id.")

    query = db().table("customers").select("*, orders(order_number, status, total, currency, placed_at, delivered_at)")
    if email:
        query = query.eq("email", email)
    else:
        query = query.eq("id", customer_id)
    query = query.order("placed_at", desc=True, foreign_table="orders").limit(RECENT_ORDERS_LIMIT, foreign_table="orders")
    rows = query.execute().data
    if not rows:
        lookup = f"email {email}" if email else f"ID {customer_id}"
        raise ToolError(f"No customer found with {lookup}.")

    customer = rows[0]
    customer["recent_orders"] = customer.pop("orders")
    return customer


@mcp.tool(annotations=WRITE)
def create_ticket(
    subject: str,
    description: str,
    priority: Literal["low", "normal", "high", "urgent"] = "normal",
    order_number: str | None = None,
    customer_email: str | None = None,
    conversation_id: str | None = None,
) -> dict[str, Any]:
    """Open a support ticket so a human agent follows up, for example on a lost-package
    claim, a warranty claim, or anything the policies say to escalate.

    Give a short subject and a description with the facts a human needs (what happened,
    what the customer wants, what you've already checked). Link the order and customer
    when you know them. Returns the new ticket, including its ticket_number.
    """
    if not subject.strip() or not description.strip():
        raise ToolError("subject and description can't be empty.")

    row: dict[str, Any] = {
        "subject": subject.strip(),
        "description": description.strip(),
        "priority": priority,
        "conversation_id": conversation_id,
    }
    if order_number:
        row["order_number"] = _parse_order_number(order_number)
    if customer_email:
        customers = db().table("customers").select("id").eq("email", customer_email.strip().lower()).execute().data
        if not customers:
            raise ToolError(f"No customer found with email {customer_email}.")
        row["customer_id"] = customers[0]["id"]
    try:
        return db().table("tickets").insert(row).execute().data[0]
    except APIError as e:
        if e.code == "23503":  # foreign key violation: the order doesn't exist
            raise ToolError(f"No order #{row.get('order_number')} found.") from None
        raise


@mcp.tool(annotations=NEEDS_APPROVAL)
def issue_refund(order_number: str, amount: float, reason: str, approval_id: str) -> dict[str, Any]:
    """Refund money to the customer's original payment method.

    Requires a human approval: approval_id identifies a refund request that a support
    supervisor approved with exactly this order_number and amount. The refund can't
    exceed what's left to refund on the order. Returns the refund record.
    """
    number = _parse_order_number(order_number)
    if amount <= 0:
        raise ToolError("amount must be greater than 0.")
    return _call_approved("execute_refund", {
        "p_approval_id": approval_id,
        "p_order_number": number,
        "p_amount": round(amount, 2),
        "p_reason": reason.strip(),
    })


@mcp.tool(annotations=NEEDS_APPROVAL)
def send_email(to: str, subject: str, body: str, approval_id: str) -> dict[str, Any]:
    """Send an email to a customer.

    Requires a human approval: approval_id identifies an email that a support agent
    approved with exactly this recipient, subject and body. Returns the sent email record.
    """
    return _call_approved("execute_email", {
        "p_approval_id": approval_id,
        "p_to_email": to,
        "p_subject": subject,
        "p_body": body,
    })


def _call_approved(function: str, params: dict[str, Any]) -> dict[str, Any]:
    try:
        return db().rpc(function, params).execute().data
    except APIError as e:
        # The database refuses unapproved, used, or mismatched actions (and invalid IDs).
        raise ToolError(e.message) from None


def _parse_order_number(value: str) -> int:
    match = re.fullmatch(r"\s*(?:order\s*)?#?\s*(\d{1,9})\s*", value, flags=re.IGNORECASE)
    if not match:
        raise ToolError(f'"{value}" isn\'t a valid order number. Order numbers look like #1042.')
    return int(match.group(1))


def _age(timestamp: str):
    return datetime.now(UTC) - datetime.fromisoformat(timestamp)


if __name__ == "__main__":
    mcp.run()
