"""Run a coroutine from synchronous code, even inside a running event loop."""

from __future__ import annotations

import asyncio
import concurrent.futures


def run_sync(coroutine):
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coroutine)
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coroutine).result()
