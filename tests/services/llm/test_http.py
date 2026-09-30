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
