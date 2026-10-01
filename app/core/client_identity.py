"""Who is making a request, for rate limiting.

X-Forwarded-For can be set by any caller, so it is only believed when the
connection comes from a configured trusted proxy (TRUSTED_PROXIES). Requests
with a valid access token are keyed by their user instead of an address: a
token cannot be forged, and it keeps users apart when they all reach the API
through the same proxy (the web app).
"""

from __future__ import annotations

import ipaddress
from functools import lru_cache
from typing import Iterable

from starlette.requests import Request

from app.core.config import settings

_Network = ipaddress.IPv4Network | ipaddress.IPv6Network


@lru_cache(maxsize=8)
def _networks(trusted: tuple[str, ...]) -> tuple[_Network, ...]:
    return tuple(ipaddress.ip_network(entry, strict=False) for entry in trusted)


def _parse(address: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    try:
        ip = ipaddress.ip_address(address.strip().split("%", 1)[0])
    except ValueError:
        return None
    if ip.version == 6 and ip.ipv4_mapped is not None:
        return ip.ipv4_mapped
    return ip


def _is_trusted(address: str, networks: tuple[_Network, ...]) -> bool:
    ip = _parse(address)
    return ip is not None and any(ip in network for network in networks)


def client_address(peer: str | None, forwarded_for: str | None, trusted: Iterable[str]) -> str:
    """The address of the client, believing X-Forwarded-For only as far back as trusted proxies vouch for it.

    Walks the header from the right (the hop closest to us): each trusted
    proxy reports the address it was connected from, and the first address
    that is not a trusted proxy is the client. Anything to its left was
    written by the client and is ignored.
    """
    peer = peer or "unknown"
    networks = _networks(tuple(trusted))
    if not networks or not _is_trusted(peer, networks):
        return peer
    client = peer
    for hop in reversed((forwarded_for or "").split(",")):
        hop = hop.strip()
        if not hop:
            continue
        if _parse(hop) is None:
            break  # garbage: stop at the last address a trusted proxy vouched for
        client = hop
        if not _is_trusted(hop, networks):
            break
    return client


def rate_limit_key(request: Request) -> str:
    """`user:<id>` for a valid access token, else `ip:<client address>`."""
    authorization = request.headers.get("Authorization", "")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() == "bearer" and token:
        # Imported here: core must not depend on services at import time.
        from app.services.auth_service import token_subject

        user_id = token_subject(token.strip())
        if user_id is not None:
            return f"user:{user_id}"
    peer = request.client.host if request.client else None
    return f"ip:{client_address(peer, request.headers.get('X-Forwarded-For'), settings.trusted_proxies)}"
