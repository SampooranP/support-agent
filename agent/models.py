"""Which Claude model each part of the project uses.

Development defaults to Claude Haiku 5.5 everywhere, which costs a fraction of Opus. For
official numbers (the README baselines), set the env vars to the official models:

    AGENT_MODEL=claude-opus-5-5 JUDGE_MODEL=claude-sonnet-5-5
"""

import os

import ingestion.config  # noqa: F401  (loads .env, so the overrides below can live there)

DEV_MODEL = "claude-haiku-5-5"
OFFICIAL = {"agent": "claude-opus-5-5", "judge": "claude-sonnet-5-5"}

AGENT_MODEL = os.getenv("AGENT_MODEL", DEV_MODEL)  # the support agent and the RAG script
JUDGE_MODEL = os.getenv("JUDGE_MODEL", DEV_MODEL)  # the eval judge
GEN_MODEL = os.getenv("GEN_MODEL", DEV_MODEL)  # the eval case generators
ROUTER_MODEL = os.getenv("ROUTER_MODEL", DEV_MODEL)  # picks the specialist; Haiku for official runs too


def is_official() -> bool:
    return AGENT_MODEL == OFFICIAL["agent"] and JUDGE_MODEL == OFFICIAL["judge"]


def supports_system_messages(model: str) -> bool:
    """Whether the model takes role "system" messages mid-conversation (Haiku 5.5 doesn't)."""
    return not model.startswith("claude-haiku")


def fallback_args(model: str) -> dict:
    """Server-side retry on Anthropic's recommended model when a safety classifier declines.
    Haiku 5.5 has no fallback, so it gets none (a decline there ends as stop_reason "refusal")."""
    if model.startswith("claude-haiku"):
        return {}
    return {"betas": ["server-side-fallback-2026-07-01"], "fallbacks": "default"}
