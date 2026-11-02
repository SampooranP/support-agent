"""Langfuse tracing for the agent: one trace per turn, grouped into sessions by conversation.

Each trace holds a generation per Claude call (model, tokens, cost, latency), a span per tool
call, and events for approvals and guardrail flags. Tracing turns on when LANGFUSE_PUBLIC_KEY
and LANGFUSE_SECRET_KEY are set (plus LANGFUSE_BASE_URL for a non-default region or a
self-hosted instance); otherwise every call here is a no-op.
"""

import logging
import os
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from agent.pricing import cost_usd, usage_dict

log = logging.getLogger("agent")


class _NoOp:
    """Stands in for a Langfuse observation when tracing is off."""

    id = None

    def update(self, **_: Any) -> None:
        pass


class Tracer:
    def __init__(self) -> None:
        self._client = None
        if os.getenv("LANGFUSE_PUBLIC_KEY") and os.getenv("LANGFUSE_SECRET_KEY"):
            try:
                from langfuse import Langfuse

                self._client = Langfuse()  # reads the LANGFUSE_* environment variables
            except Exception:
                log.exception("Langfuse failed to start; tracing is off")

    @property
    def enabled(self) -> bool:
        return self._client is not None

    @contextmanager
    def turn(self, name: str, conversation: dict, input: Any) -> Iterator[Any]:
        """The root observation for one agent turn."""
        if not self._client:
            yield _NoOp()
            return
        from langfuse import propagate_attributes

        with self._client.start_as_current_observation(name=name, as_type="agent", input=input) as root:
            with propagate_attributes(
                session_id=conversation["id"], user_id=conversation["customer_email"], trace_name=name
            ):
                yield root

    @contextmanager
    def generation(self, name: str, model: str, input: Any) -> Iterator[Any]:
        if not self._client:
            yield _NoOp()
            return
        with self._client.start_as_current_observation(name=name, as_type="generation", model=model, input=input) as gen:
            yield gen

    def record_generation(self, gen: Any, message: Any) -> None:
        """Attach a finished Claude response's output, tokens and cost to its generation."""
        usage = usage_dict(message.usage)
        cost = cost_usd(message.model, message.usage)
        gen.update(
            model=message.model,
            output=[b.model_dump(mode="json", exclude_none=True) for b in message.content],
            usage_details={
                "input": usage["input_tokens"],
                "output": usage["output_tokens"],
                "cache_read_input_tokens": usage["cache_read_input_tokens"],
                "cache_creation_input_tokens": usage["cache_creation_input_tokens"],
            },
            cost_details={"total": cost} if cost is not None else None,
            metadata={"stop_reason": message.stop_reason},
        )

    @contextmanager
    def tool(self, name: str, input: Any) -> Iterator[Any]:
        if not self._client:
            yield _NoOp()
            return
        with self._client.start_as_current_observation(name=name, as_type="tool", input=input) as span:
            yield span

    def event(self, name: str, as_type: str = "span", level: str = "DEFAULT", **fields: Any) -> None:
        """A point-in-time observation in the current trace (an approval request, a guardrail flag)."""
        if not self._client:
            return
        with self._client.start_as_current_observation(name=name, as_type=as_type, level=level, **fields):
            pass

    def flush(self) -> None:
        if self._client:
            self._client.flush()
