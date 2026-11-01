"""Launch the MCP server over stdio and check each tool against the seed data.

Reloads the demo data first (supabase/seed.sql's reset_demo_data()), so the
date-based checks hold no matter when the seed was last run.

Usage (from the repo root, after running supabase/seed.sql once):
    python mcp-server/smoke_test.py
"""

import asyncio
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from mcp import Client, StdioServerParameters
from supabase import create_client

SERVER = Path(__file__).resolve().parent / "server.py"
load_dotenv(SERVER.parent.parent / ".env")


def reset_demo_data() -> None:
    url, key = os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        raise SystemExit("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set in .env")
    create_client(url, key).rpc("reset_demo_data").execute()
    print("demo data reset")


async def main() -> None:
    reset_demo_data()
    params = StdioServerParameters(command=sys.executable, args=[str(SERVER)])
    failures = 0

    async with Client(params) as client:
        tools = sorted(t.name for t in (await client.list_tools()).tools)
        print(f"tools: {tools}")

        async def check(name: str, args: dict, expect_error: bool, test) -> None:
            nonlocal failures
            result = await client.call_tool(name, args)
            text = result.content[0].text if result.content else ""
            data = result.structured_content or {}
            ok = result.is_error == expect_error and test(data, text)
            failures += not ok
            summary = text if result.is_error else json.dumps(data)[:120]
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
        await check("get_customer", {"email": "nobody@example.com"}, True, lambda _, t: "No customer" in t)
        await check("get_customer", {}, True, lambda _, t: "exactly one" in t)

    print(f"\n{'All checks passed.' if not failures else f'{failures} check(s) failed.'}")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    asyncio.run(main())
