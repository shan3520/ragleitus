from app.services.llm import Usage
from app.services.llm.pricing import estimate_cost_usd


def test_known_model_cost():
    # claude-opus-5-5: $4 in / $20 out per million tokens
    assert estimate_cost_usd("claude-opus-5-5", Usage(1_000_000, 1_000_000)) == 24.0
    assert estimate_cost_usd("gpt-4o-mini", Usage(1000, 500)) == round((1000 * 0.15 + 500 * 0.60) / 1e6, 8)


def test_openrouter_style_namespaced_model_uses_base_price():
    assert estimate_cost_usd("openai/gpt-4o-mini", Usage(1000, 0)) == estimate_cost_usd("gpt-4o-mini", Usage(1000, 0))


def test_unknown_model_or_missing_usage_has_no_cost():
    assert estimate_cost_usd("some-local-model", Usage(10, 10)) is None
    assert estimate_cost_usd("gpt-4o-mini", Usage(None, 10)) is None
    assert estimate_cost_usd(None, Usage(10, 10)) is None


def test_every_providers_default_chat_model_with_a_published_price_is_priced():
    from app.services.llm import get_spec

    # Groq's default, at Groq's list price ($0.15 in, $0.60 out per million tokens).
    groq = get_spec("groq").default_model
    assert estimate_cost_usd(groq, Usage(1_000_000, 1_000_000)) == 0.75
    for name in ("openai", "anthropic", "groq"):
        assert estimate_cost_usd(get_spec(name).default_model, Usage(1000, 1000)) is not None, name
