"""MCP server exposing Lumen & Pine customer-support tools, backed by Supabase.

Tools:
    get_order     look up an order by number, with its line items and customer
    get_customer  look up a customer by email or ID, with their recent orders

Run over stdio (how MCP clients such as Claude Desktop launch it):
    python mcp-server/server.py
"""

import logging
import re
from datetime import datetime, timezone
from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp_types import ToolAnnotations

from db import supabase_client as db

logging.getLogger("httpx").setLevel(logging.WARNING)  # don't log every Supabase request URL

READ_ONLY = ToolAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=False)
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


def _parse_order_number(value: str) -> int:
    match = re.fullmatch(r"\s*(?:order\s*)?#?\s*(\d{1,9})\s*", value, flags=re.IGNORECASE)
    if not match:
        raise ToolError(f'"{value}" isn\'t a valid order number. Order numbers look like #1042.')
    return int(match.group(1))


def _age(timestamp: str):
    return datetime.now(timezone.utc) - datetime.fromisoformat(timestamp)


if __name__ == "__main__":
    mcp.run()
