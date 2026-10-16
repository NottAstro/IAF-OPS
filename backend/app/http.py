"""Shared upstream HTTP client + TTL cache with request coalescing (port of God's Eye common/http.js idea)."""
import asyncio
import time
from collections import OrderedDict
from collections.abc import Awaitable, Callable

import httpx

from . import config

UA = config.AWC_USER_AGENT or "iaf-airops/0.1"
client = httpx.AsyncClient(headers={"User-Agent": UA}, timeout=httpx.Timeout(20, connect=10), follow_redirects=True,
                           verify=config.HTTP_VERIFY, limits=httpx.Limits(max_connections=40))


class TTLCache:
    """ponytail: in-process LRU; move to Redis only if we ever run >1 worker."""

    def __init__(self, max_items: int = 512):
        self.data: OrderedDict[str, tuple[float, object]] = OrderedDict()
        self.inflight: dict[str, asyncio.Future] = {}
        self.max = max_items

    def peek(self, key: str):
        hit = self.data.get(key)
        return hit[1] if hit else None

    async def get(self, key: str, ttl: float, fetch: Callable[[], Awaitable[object]], stale_ok: bool = True):
        hit = self.data.get(key)
        if hit and hit[0] > time.monotonic():
            self.data.move_to_end(key)
            return hit[1]
        if key in self.inflight:                     # coalesce identical concurrent requests
            return await asyncio.shield(self.inflight[key])
        fut = asyncio.get_running_loop().create_future()
        self.inflight[key] = fut
        try:
            value = await fetch()
            self.data[key] = (time.monotonic() + ttl, value)
            self.data.move_to_end(key)
            while len(self.data) > self.max:
                self.data.popitem(last=False)
            fut.set_result(value)
            return value
        except Exception as ex:
            if hit and stale_ok:                      # serve stale on upstream failure
                fut.set_result(hit[1])
                return hit[1]
            fut.set_exception(ex)
            fut.exception()  # mark retrieved
            raise
        finally:
            self.inflight.pop(key, None)
