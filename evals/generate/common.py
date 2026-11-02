"""Shared helpers for the case generators: a Claude client (GEN_MODEL) with structured output, cost tracking, YAML I/O."""

import asyncio
from pathlib import Path
from typing import TypeVar

import anthropic
import yaml
from pydantic import BaseModel

from agent.models import GEN_MODEL, fallback_args
from agent.pricing import cost_usd
from ingestion.config import REPO_ROOT, require_env

GENERATED = REPO_ROOT / "evals" / "generated"
T = TypeVar("T", bound=BaseModel)


class Generator:
    """Claude calls with a concurrency cap and a running cost total."""

    def __init__(self, concurrency: int = 4):
        self.client = anthropic.AsyncAnthropic(api_key=require_env("ANTHROPIC_API_KEY"), max_retries=4)
        self.limit = asyncio.Semaphore(concurrency)
        self.cost = 0.0
        self.calls = 0

    async def parse(self, system: str, prompt: str, schema: type[T], max_tokens: int = 8000) -> T:
        async with self.limit:
            response = await self.client.beta.messages.parse(
                model=GEN_MODEL,
                max_tokens=max_tokens,
                system=system,
                messages=[{"role": "user", "content": prompt}],
                output_format=schema,
                **fallback_args(GEN_MODEL),
            )
        self.calls += 1
        self.cost += cost_usd(response.model, response.usage) or 0
        if response.stop_reason == "refusal" or response.parsed_output is None:
            raise RuntimeError(f"no structured output (stop_reason={response.stop_reason})")
        return response.parsed_output


class _Dumper(yaml.SafeDumper):
    pass


def _str(dumper, value: str):
    # Multi-line strings as blocks, so generated files stay reviewable in a diff.
    return dumper.represent_scalar("tag:yaml.org,2002:str", value, style="|" if "\n" in value else None)


_Dumper.add_representer(str, _str)


def load_yaml(path: Path) -> list[dict]:
    return (yaml.safe_load(path.read_text(encoding="utf-8")) or []) if path.exists() else []


def write_yaml(path: Path, header: str, cases: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    body = yaml.dump(cases, Dumper=_Dumper, sort_keys=False, allow_unicode=True, width=120)
    path.write_text("".join(f"# {line}\n".replace("# \n", "#\n") for line in header.strip().splitlines()) + "\n" + body,
                    encoding="utf-8")
