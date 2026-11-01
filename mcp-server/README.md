# mcp-server

MCP server exposing support tools, backed by Supabase. See the [main README](../README.md#mcp-server) for setup.

- `server.py`: the server. Tools so far: `get_order`, `get_customer` (read-only).
- `smoke_test.py`: launches the server over stdio and checks each tool against `supabase/seed.sql`.

Planned with the human-approval flow: `create_ticket`, `issue_refund`, `send_email`.
