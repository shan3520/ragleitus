"""Token prices used to estimate the cost of each LLM call.

Prices are USD per million tokens (input, output), list prices at the time of
writing. Providers change prices, and OpenRouter/Together/NIM prices vary by
upstream route, so models not listed here get a cost of ``None`` rather than
a guess. Edit this table to match your contracts.
"""

from __future__ import annotations

from app.services.llm.base import Usage

PRICES_PER_MILLION: dict[str, tuple[float, float]] = {
    # Anthropic
    "claude-fable-5-1": (10.00, 50.00),
    "claude-opus-5-5": (4.00, 20.00),
    "claude-opus-5": (5.00, 25.00),
    "claude-opus-4-8": (5.00, 25.00),
    "claude-sonnet-5-5": (2.00, 10.00),
    "claude-sonnet-5": (2.00, 10.00),
    "claude-sonnet-4-6": (3.00, 15.00),
    "claude-haiku-4-5": (1.00, 5.00),
    # OpenAI
    "gpt-4o": (2.50, 10.00),
    "gpt-4o-mini": (0.15, 0.60),
    # Embedding models: input tokens only.
    "text-embedding-3-small": (0.02, 0.0),
    "text-embedding-3-large": (0.13, 0.0),
    "gemini-embedding-001": (0.15, 0.0),
    "mistral-embed": (0.10, 0.0),
    # Groq
    "llama-3.3-70b-versatile": (0.59, 0.79),
    "llama-3.1-8b-instant": (0.05, 0.08),
}


def estimate_cost_usd(model: str | None, usage: Usage) -> float | None:
    if model is None or usage.prompt_tokens is None or usage.completion_tokens is None:
        return None
    prices = PRICES_PER_MILLION.get(model)
    if prices is None:
        # OpenRouter model ids are namespaced ("openai/gpt-4o-mini").
        prices = PRICES_PER_MILLION.get(model.rsplit("/", 1)[-1])
    if prices is None:
        return None
    input_price, output_price = prices
    return round((usage.prompt_tokens * input_price + usage.completion_tokens * output_price) / 1_000_000, 8)
