import asyncio
from types import SimpleNamespace

from fastapi.testclient import TestClient

from agent import api, spend, store, tools

client = TestClient(api.app)  # no `with`, so the lifespan (Claude client, MCP server) doesn't start


def test_health_needs_no_secret(monkeypatch):
    monkeypatch.setattr(api, "API_SECRET", "s3cret")
    assert client.get("/health").json() == {"status": "ok"}


def test_other_endpoints_need_the_secret(monkeypatch):
    monkeypatch.setattr(api, "API_SECRET", "s3cret")
    assert client.get("/customers").status_code == 401
    assert client.get("/approvals", headers={"x-agent-secret": "wrong"}).status_code == 401


def test_tickets_need_the_secret_and_are_listed_with_it(monkeypatch):
    monkeypatch.setattr(api, "API_SECRET", "s3cret")
    monkeypatch.setattr(api.store, "list_tickets", lambda limit: [{"ticket_number": 5001, "limit": limit}])
    assert client.get("/tickets").status_code == 401
    response = client.get("/tickets?limit=5", headers={"x-agent-secret": "s3cret"})
    assert response.json() == [{"ticket_number": 5001, "limit": 5}]


def test_list_tickets_flattens_the_customer_and_hides_the_conversation(monkeypatch):
    rows = [
        {"ticket_number": 5002, "customers": {"name": "Maya", "email": "maya@example.com"}},
        {"ticket_number": 5001, "customers": None},  # a ticket with no customer
    ]
    query = SimpleNamespace(columns=None)
    query.select = lambda columns: (setattr(query, "columns", columns), query)[1]
    query.order = lambda *_, **__: query
    query.limit = lambda _: query
    query.execute = lambda: SimpleNamespace(data=rows)
    monkeypatch.setattr(store, "_db", lambda: SimpleNamespace(table=lambda _: query))

    tickets = store.list_tickets(5)
    assert [(t["customer_name"], t["customer_email"]) for t in tickets] == [("Maya", "maya@example.com"), (None, None)]
    assert all("customers" not in t for t in tickets)
    assert "*" not in query.columns and "conversation_id" not in query.columns


def test_mcp_server_is_given_the_database_settings(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "test-key")
    assert tools.mcp_server_params().env == {
        "SUPABASE_URL": "https://example.supabase.co",
        "SUPABASE_SERVICE_ROLE_KEY": "test-key",
    }


def test_every_reported_claude_call_is_added_to_todays_spend(monkeypatch):
    added, seen = [], []
    monkeypatch.setattr(spend, "add", added.append)

    async def emit(event):
        seen.append(event["type"])

    usage = {"input_tokens": 1_000_000, "output_tokens": 0}
    metered = spend.metered(emit)
    for event in [
        {"type": "route", "model": "claude-haiku-5-5", "usage": usage},
        {"type": "model_call", "model": "claude-sonnet-5-5", "usage": usage},
        {"type": "model_call", "model": "claude-unknown", "usage": usage},  # charged at the highest price
        {"type": "route", "model": None, "usage": {}},  # the router failed: no call to pay for
        {"type": "text", "delta": "Hi"},
    ]:
        asyncio.run(metered(event))
    assert added == [0.10, 2.00, 5.00]
    assert seen == ["route", "model_call", "model_call", "route", "text"]  # every event still reaches the client
