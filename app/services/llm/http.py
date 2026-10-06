"""Shared HTTP helpers for adapters that speak to providers over raw HTTP."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import AsyncIterator, Mapping

import httpx

from app.core.config import settings
from app.services.llm.base import ProviderError


def make_client(transport: httpx.AsyncBaseTransport | None = None) -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=settings.llm_timeout_seconds, transport=transport)


def _error_text(response: httpx.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        return response.text[:300]
    error = body.get("error") if isinstance(body, dict) else None
    if isinstance(error, dict):
        return str(error.get("message") or error)[:300]
    if isinstance(error, str):
        return error[:300]
    if isinstance(body, dict) and "message" in body:
        return str(body["message"])[:300]
    return str(body)[:300]


def retry_after_seconds(headers: Mapping[str, str] | None) -> float | None:
    """The wait a Retry-After header asks for (seconds or an HTTP date), if any."""
    value = (headers or {}).get("retry-after") or (headers or {}).get("Retry-After")
    if not value:
        return None
    value = value.strip()
    try:
        return max(0.0, float(value))
    except ValueError:
        pass
    try:
        when = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return max(0.0, (when - datetime.now(timezone.utc)).total_seconds())


def google_retry_delay(response: httpx.Response) -> float | None:
    """The wait a Google API error asks for in its body, if any.

    Gemini's 429 has no Retry-After header; the wait is a google.rpc.RetryInfo
    detail instead: {"@type": ".../google.rpc.RetryInfo", "retryDelay": "34s"}.
    """
    try:
        body = response.json()
    except ValueError:
        return None
    error = body.get("error") if isinstance(body, dict) else None
    details = error.get("details") if isinstance(error, dict) else None
    for detail in details if isinstance(details, list) else []:
        if not isinstance(detail, dict) or not str(detail.get("@type", "")).endswith("google.rpc.RetryInfo"):
            continue
        delay = detail.get("retryDelay")
        if isinstance(delay, str) and delay.endswith("s"):
            try:
                return max(0.0, float(delay[:-1]))
            except ValueError:
                return None
    return None


def error_status(response: httpx.Response) -> int:
    """The response's status, with Google's way of rejecting a key made a 401.

    Gemini answers an invalid API key with 400 INVALID_ARGUMENT and the
    reason API_KEY_INVALID; callers check `is_auth_error` to tell a rejected
    key from a bad request.
    """
    if response.status_code != 400:
        return response.status_code
    try:
        body = response.json()
    except ValueError:
        return 400
    error = body.get("error") if isinstance(body, dict) else None
    details = error.get("details") if isinstance(error, dict) else None
    if isinstance(details, list) and any(isinstance(d, dict) and d.get("reason") == "API_KEY_INVALID" for d in details):
        return 401
    return 400


async def raise_for_status(response: httpx.Response, provider: str, *, include_body: bool = True) -> None:
    """Raise ProviderError for an error response.

    `include_body=False` leaves the response text out of the message. Used for
    user-supplied URLs, so the error can't be used to read an arbitrary server.
    """
    if response.status_code < 400:
        return
    retry_after = retry_after_seconds(response.headers)
    if not include_body:
        raise ProviderError(
            f"{provider} returned HTTP {response.status_code}", status_code=response.status_code, retry_after=retry_after
        )
    await response.aread()
    if retry_after is None:
        retry_after = google_retry_delay(response)
    raise ProviderError(
        f"{provider} returned HTTP {response.status_code}: {_error_text(response)}",
        status_code=error_status(response),
        retry_after=retry_after,
    )


async def iter_sse_json(response: httpx.Response) -> AsyncIterator[dict]:
    """Yield the JSON payload of each `data:` line of a server-sent event stream.

    Stops at the OpenAI-style `[DONE]` sentinel. Lines that are not data lines
    (comments, `event:` names, keep-alives) are skipped.
    """
    async for line in response.aiter_lines():
        if not line.startswith("data:"):
            continue
        data = line[len("data:"):].strip()
        if not data:
            continue
        if data == "[DONE]":
            return
        try:
            yield json.loads(data)
        except ValueError:
            continue


def transport_error(provider: str, exc: httpx.HTTPError) -> ProviderError:
    # The exception type is enough; its text can include the request URL.
    return ProviderError(f"Could not reach {provider} ({type(exc).__name__})")
