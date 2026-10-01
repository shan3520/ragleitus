"""Refuse provider URLs that point into a private network.

A self-hosted provider's base URL comes from the user, and the API server
calls it. Without a check, any user could make the server request internal
services (the database, Qdrant, a cloud metadata endpoint). Such addresses
are refused unless the operator opts in with ALLOW_PRIVATE_PROVIDER_URLS,
which is what a self-hosted Ollama, LM Studio or vLLM next to the API needs.

The host is resolved and every address it resolves to must be public. The
HTTP client resolves the name again when it connects, so a DNS server that
changes its answer in between is not covered.
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from urllib.parse import urlsplit

from app.core.config import settings
from app.services.llm.base import ProviderError

PRIVATE_URL_MESSAGE = (
    "That address is on a private network, which is not allowed. "
    "To use a self-hosted server, the operator can set ALLOW_PRIVATE_PROVIDER_URLS=true."
)


def is_public_address(address: str) -> bool:
    ip = ipaddress.ip_address(address.split("%", 1)[0])
    if ip.version == 6 and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return ip.is_global


async def ensure_public_url(url: str) -> None:
    """Raise ProviderError (status 400) unless every address of the URL's host is public."""
    if settings.allow_private_provider_urls:
        return
    host = urlsplit(url).hostname
    if not host:
        raise ProviderError("The base URL has no host.", status_code=400)
    try:
        infos = await asyncio.get_running_loop().getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except socket.gaierror:
        raise ProviderError(f"Could not resolve {host}.") from None
    if not infos or not all(is_public_address(info[4][0]) for info in infos):
        raise ProviderError(PRIVATE_URL_MESSAGE, status_code=400)
