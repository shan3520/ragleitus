import asyncio

import httpx
import pytest

from app.services.llm.base import ProviderError
from app.services.llm.http import _error_text, iter_sse_json, raise_for_status, transport_error


@pytest.mark.parametrize(
    "response, expected",
    [
        (httpx.Response(400, json={"error": {"message": "bad model"}}), "bad model"),
        (httpx.Response(400, json={"error": "quota"}), "quota"),
        (httpx.Response(400, json={"message": "nope"}), "nope"),
        (httpx.Response(400, text="plain failure"), "plain failure"),
        (httpx.Response(400, text="x" * 1000), "x" * 300),
    ],
)
def test_error_text_reads_common_error_shapes(response, expected):
    assert _error_text(response) == expected


def test_raise_for_status_passes_success_and_reports_errors():
    asyncio.run(raise_for_status(httpx.Response(200), "openai"))
    with pytest.raises(ProviderError) as exc:
        asyncio.run(raise_for_status(httpx.Response(429, json={"error": {"message": "slow down"}}), "openai"))
    assert exc.value.status_code == 429
    assert exc.value.message == "openai returned HTTP 429: slow down"


def test_raise_for_status_can_leave_the_body_out():
    with pytest.raises(ProviderError) as exc:
        asyncio.run(raise_for_status(httpx.Response(500, text="internal detail"), "custom", include_body=False))
    assert exc.value.message == "custom returned HTTP 500"


def test_iter_sse_json_skips_non_data_lines_and_stops_at_done():
    body = (
        ": keep-alive\n\n"
        "event: message\n"
        'data: {"n": 1}\n\n'
        "data: not json\n\n"
        "data:\n\n"
        'data: {"n": 2}\n\n'
        "data: [DONE]\n\n"
        'data: {"n": 3}\n\n'
    )

    async def collect():
        return [item async for item in iter_sse_json(httpx.Response(200, text=body))]

    assert asyncio.run(collect()) == [{"n": 1}, {"n": 2}]


def test_transport_error_does_not_include_the_url():
    request = httpx.Request("GET", "https://api.example.test/v1/models?key=secret")
    error = transport_error("openai", httpx.ConnectError("failed to connect to https://api.example.test", request=request))
    assert error.message == "Could not reach openai (ConnectError)"
    assert "example" not in error.message and error.status_code is None


def test_retry_after_is_read_from_seconds_or_a_date():
    from datetime import datetime, timedelta, timezone
    from email.utils import format_datetime

    from app.services.llm.http import retry_after_seconds

    assert retry_after_seconds({"retry-after": "7"}) == 7.0
    assert retry_after_seconds(httpx.Headers({"Retry-After": "1.5"})) == 1.5
    soon = format_datetime(datetime.now(timezone.utc) + timedelta(seconds=30), usegmt=True)
    assert 25 <= retry_after_seconds({"retry-after": soon}) <= 30
    assert retry_after_seconds({"retry-after": "soon"}) is None
    assert retry_after_seconds({}) is None and retry_after_seconds(None) is None
    assert retry_after_seconds({"retry-after": "-3"}) == 0.0

    with pytest.raises(ProviderError) as exc:
        asyncio.run(raise_for_status(httpx.Response(429, headers={"Retry-After": "12"}, text="slow"), "openai"))
    assert exc.value.retry_after == 12.0 and exc.value.is_retryable


# Gemini's real free-tier 429 (message shortened): the wait is in the body, not a header.
GEMINI_429 = {
    "error": {
        "code": 429,
        "message": "You exceeded your current quota, please check your plan and billing details.",
        "status": "RESOURCE_EXHAUSTED",
        "details": [
            {"@type": "type.googleapis.com/google.rpc.Help",
             "links": [{"description": "Learn more about Gemini API quotas", "url": "https://ai.google.dev/gemini-api/docs/rate-limits"}]},
            {"@type": "type.googleapis.com/google.rpc.QuotaFailure",
             "violations": [{"quotaId": "GenerateRequestsPerMinutePerProjectPerModel-FreeTier", "quotaValue": "5"}]},
            {"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "34s"},
        ],
    }
}


def test_a_google_retry_delay_in_the_body_is_the_wait():
    from app.services.llm.http import google_retry_delay

    with pytest.raises(ProviderError) as exc:
        asyncio.run(raise_for_status(httpx.Response(429, json=GEMINI_429), "gemini"))
    assert exc.value.retry_after == 34.0 and exc.value.is_retryable
    assert "exceeded your current quota" in exc.value.message

    # A Retry-After header still wins; odd or missing delays are ignored.
    with pytest.raises(ProviderError) as exc:
        asyncio.run(raise_for_status(httpx.Response(429, headers={"Retry-After": "3"}, json=GEMINI_429), "gemini"))
    assert exc.value.retry_after == 3.0
    assert google_retry_delay(httpx.Response(429, json={"error": {"details": [
        {"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "0.5s"}]}})) == 0.5
    assert google_retry_delay(httpx.Response(429, json={"error": {"details": [
        {"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "soon"}]}})) is None
    assert google_retry_delay(httpx.Response(429, json={"error": "slow down"})) is None
    assert google_retry_delay(httpx.Response(429, text="not json")) is None


def test_a_429_with_no_allowance_at_all_is_not_retryable():
    # Mistral's real answer for mistral-small-latest on a plan without it.
    headers = {"x-ratelimit-limit-req-minute": "0", "x-ratelimit-remaining-req-minute": "0"}
    body = {"object": "error", "message": "Rate limit exceeded", "type": "rate_limited", "param": None,
            "code": "1300", "raw_status_code": 429}
    for include_body in (True, False):
        with pytest.raises(ProviderError) as exc:
            asyncio.run(raise_for_status(httpx.Response(429, headers=headers, json=body), "mistral", include_body=include_body))
        assert exc.value.status_code == 429 and not exc.value.is_retryable and not exc.value.is_auth_error
        assert "plan allows no requests to this model" in exc.value.message
        assert ("Rate limit exceeded" in exc.value.message) is include_body

    # An ordinary rate limit (allowance left this minute, or no header) is still retried.
    for headers in ({"x-ratelimit-limit-req-minute": "188", "x-ratelimit-remaining-req-minute": "0"}, {}):
        with pytest.raises(ProviderError) as exc:
            asyncio.run(raise_for_status(httpx.Response(429, headers=headers, json=body), "mistral"))
        assert exc.value.is_retryable and "plan allows" not in exc.value.message
