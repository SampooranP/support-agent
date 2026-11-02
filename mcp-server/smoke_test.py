"""Launch the MCP server over stdio and check each tool against the seed data.

Reloads the demo data first (supabase/seed.sql's reset_demo_data()), so the
date-based checks hold no matter when the seed was last run. The reset refuses
to run if the database holds any customers or orders that aren't demo data.

Usage (from the repo root, after running supabase/seed.sql once):
    python mcp-server/smoke_test.py
"""

import asyncio
import json
import sys
from pathlib import Path

from mcp import Client, StdioServerParameters
from postgrest.exceptions import APIError

from db import supabase_client

SERVER = Path(__file__).resolve().parent / "server.py"


def reset_demo_data() -> None:
    try:
        supabase_client().rpc("reset_demo_data").execute()
    except APIError as e:
        raise SystemExit(f"Demo data reset refused: {e.message}") from None
    print("demo data reset")


async def main() -> None:
    reset_demo_data()
    params = StdioServerParameters(command=sys.executable, args=[str(SERVER)])
    failures = 0

    async with Client(params) as client:
        tools = sorted(t.name for t in (await client.list_tools()).tools)
        print(f"tools: {tools}")
        if tools != ["create_ticket", "get_customer", "get_order", "issue_refund", "send_email"]:
            failures += 1
            print("FAIL  unexpected tool list")

        async def check(name: str, args: dict, expect_error: bool, test) -> None:
            nonlocal failures
            try:
                result = await client.call_tool(name, args)
                text = getattr(result.content[0], "text", "") if result.content else ""
                data = result.structured_content or {}
                ok = result.is_error == expect_error and test(data, text)
                summary = text if result.is_error else json.dumps(data)[:120]
            except Exception as e:  # a malformed response is a failed check, not a crashed run
                ok, summary = False, f"{type(e).__name__}: {e}"
            failures += not ok
            print(f"{'PASS' if ok else 'FAIL'}  {name}({args}) -> {summary}")

        await check("get_order", {"order_number": "#1042"}, False,
                    lambda d, _: d["status"] == "delivered" and d["days_since_delivery"] == 3
                    and d["customer"]["email"] == "maya.chen@example.com" and len(d["items"]) == 1)
        await check("get_order", {"order_number": "1047"}, False,
                    lambda d, _: d["items"][0]["final_sale"] is True and d["currency"] == "CAD")
        await check("get_order", {"order_number": "1046"}, False,
                    lambda d, _: d["status"] == "processing" and d["hours_since_placed"] < 1
                    and "days_since_delivery" not in d)
        await check("get_order", {"order_number": "9999"}, True, lambda _, t: "No order #9999" in t)
        await check("get_order", {"order_number": "abc"}, True, lambda _, t: "valid order number" in t)
        await check("get_customer", {"email": "Priya.N@Example.com"}, False,
                    lambda d, _: d["id"] == "cus_003" and [o["order_number"] for o in d["recent_orders"]] == [1045])
        await check("get_customer", {"customer_id": "cus_004"}, False,
                    lambda d, _: [o["order_number"] for o in d["recent_orders"]] == [1046, 1049])
        await check("get_customer", {"email": " ", "customer_id": "cus_001"}, False,
                    lambda d, _: d["name"] == "Maya Chen")
        await check("get_customer", {"email": "nobody@example.com"}, True, lambda _, t: "No customer" in t)
        await check("get_customer", {"email": "   "}, True, lambda _, t: "exactly one" in t)
        await check("get_customer", {}, True, lambda _, t: "exactly one" in t)
        await check("create_ticket", {"subject": "Lost package", "description": "Order #1048 never arrived.",
                                      "priority": "high", "order_number": "1048",
                                      "customer_email": "leo.martins@example.com"}, False,
                    lambda d, _: d["ticket_number"] >= 5001 and d["customer_id"] == "cus_005" and d["status"] == "open")
        await check("create_ticket", {"subject": "x", "description": "y", "order_number": "9999"}, True,
                    lambda _, t: "No order #9999" in t)
        # Refunds and emails must be refused without a real, approved approval.
        fake = "00000000-0000-0000-0000-000000000000"
        await check("issue_refund", {"order_number": "1042", "amount": 10, "reason": "test", "approval_id": fake}, True,
                    lambda _, t: "No refund approval" in t)
        await check("issue_refund", {"order_number": "1042", "amount": 10, "reason": "test", "approval_id": "not-a-uuid"},
                    True, lambda _, t: "uuid" in t.lower())
        await check("send_email", {"to": "maya.chen@example.com", "subject": "Hi", "body": "Test", "approval_id": fake},
                    True, lambda _, t: "No email approval" in t)

    print(f"\n{'All checks passed.' if not failures else f'{failures} check(s) failed.'}")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    asyncio.run(main())
