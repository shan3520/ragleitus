"""Outbound network for the tests: blocked, except in the opt-in live tests.

Tests must run with no external services (CONTRIBUTING.md), so conftest.py
calls `block()` before anything else: connections may only go to loopback
or Unix sockets, and proxy variables are removed (a local proxy would let
requests past the loopback exemption). The live tests (tests/live, run with
`pytest -m live`) talk to real providers on purpose and use `allow`.
"""

from __future__ import annotations

import os
import socket

PROXY_VARS = ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy")

_real_connect = socket.socket.connect
_saved_proxies: dict[str, str] = {}


def _loopback_only(self, address):
    if self.family == socket.AF_UNIX or (isinstance(address, tuple) and address[0] in ("127.0.0.1", "::1", "localhost")):
        return _real_connect(self, address)
    raise RuntimeError(f"test attempted a network connection to {address!r}")


def block() -> None:
    for name in PROXY_VARS:
        if name in os.environ:
            _saved_proxies[name] = os.environ.pop(name)
    socket.socket.connect = _loopback_only


def allow(monkeypatch) -> None:
    """Real network (and the proxies the environment set) for one test."""
    monkeypatch.setattr(socket.socket, "connect", _real_connect)
    for name, value in _saved_proxies.items():
        monkeypatch.setenv(name, value)
