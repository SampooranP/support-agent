"""Claude API prices (first-party, USD per million tokens), for cost tracking in traces and evals."""

from typing import Any

# input, output, cache read. Cache writes cost 1.25x input.
PRICES: dict[str, tuple[float, float, float]] = {
    "claude-opus-5-5": (4.00, 20.00, 0.20),
    "claude-sonnet-5-5": (2.00, 10.00, 0.20),
    "claude-haiku-5-5": (0.10, 0.50, 0.01),
    # Possible refusal-fallback targets
    "claude-opus-5": (5.00, 25.00, 0.50),
    "claude-opus-4-8": (5.00, 25.00, 0.50),
}


def usage_dict(usage: Any) -> dict[str, int]:
    """Token counts from an API usage object (or dict), with missing fields as 0."""
    get = usage.get if isinstance(usage, dict) else lambda k, d=None: getattr(usage, k, d)
    return {
        "input_tokens": get("input_tokens", 0) or 0,
        "output_tokens": get("output_tokens", 0) or 0,
        "cache_read_input_tokens": get("cache_read_input_tokens", 0) or 0,
        "cache_creation_input_tokens": get("cache_creation_input_tokens", 0) or 0,
    }


def cost_usd(model: str, usage: Any) -> float | None:
    """Dollar cost of one call, or None if the model's price isn't known."""
    prices = PRICES.get(model)
    if prices is None:
        return None
    price_in, price_out, price_cache_read = prices
    u = usage_dict(usage)
    return (
        u["input_tokens"] * price_in
        + u["output_tokens"] * price_out
        + u["cache_read_input_tokens"] * price_cache_read
        + u["cache_creation_input_tokens"] * price_in * 1.25
    ) / 1_000_000
