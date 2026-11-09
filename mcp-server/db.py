"""Supabase client shared by the MCP server and its smoke test."""

import os
from functools import cache
from pathlib import Path

import httpx
from dotenv import load_dotenv
from supabase import Client, create_client

load_dotenv(Path(__file__).resolve().parent.parent / ".env")


@cache
def supabase_client() -> Client:
    url, key = os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        raise RuntimeError("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set in .env (see .env.example).")
    client = create_client(url, key)
    # The MCP server runs each tool in a worker thread, all sharing this client. supabase-py's default HTTP/2
    # session intermittently fails with "Server disconnected" when shared across threads; HTTP/1.1 doesn't.
    postgrest = client.postgrest
    http2_session = postgrest.session
    postgrest.session = httpx.Client(
        base_url=http2_session.base_url,
        headers=http2_session.headers,
        timeout=http2_session.timeout,
        follow_redirects=True,
        http2=False,
    )
    http2_session.close()
    return client
