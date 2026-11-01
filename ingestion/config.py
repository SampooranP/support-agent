"""Settings and API clients shared by the ingestion pipeline and the RAG script."""

import os
from functools import cache
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parent.parent
DOCS_DIR = REPO_ROOT / "docs"

load_dotenv(REPO_ROOT / ".env")

VOYAGE_MODEL = os.getenv("VOYAGE_MODEL", "voyage-3.5")
EMBEDDING_DIM = 1024  # must match vector(1024) in supabase/migrations
CHUNKS_TABLE = "doc_chunks"
MATCH_FUNCTION = "match_doc_chunks"


def require_env(name: str) -> str:
    """Return an environment variable, or exit with a message naming (never printing) it."""
    value = os.getenv(name)
    if not value:
        raise SystemExit(f"Missing {name}. Add it to .env (see .env.example).")
    return value


@cache
def voyage_client():
    import voyageai

    # Retries rate-limit and server errors with exponential backoff (up to 16s between tries),
    # which keeps the free tier's 3-requests-per-minute limit from failing a run.
    return voyageai.Client(api_key=require_env("VOYAGE_API_KEY"), max_retries=8)


@cache
def supabase_client():
    from supabase import create_client

    return create_client(require_env("SUPABASE_URL"), require_env("SUPABASE_SERVICE_ROLE_KEY"))
