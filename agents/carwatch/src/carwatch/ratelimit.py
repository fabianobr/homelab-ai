"""src/carwatch/ratelimit.py"""
import asyncio
import contextlib
import random
import time
from collections import defaultdict


class RateLimiter:
    def __init__(self, min_interval_sec: float, global_concurrency: int, jitter_pct: float = 0.30):
        self._min_interval_sec = min_interval_sec
        self._jitter_pct = jitter_pct
        self._global_sem = asyncio.Semaphore(global_concurrency)
        self._domain_locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
        self._last_request_at: dict[str, float] = {}

    @contextlib.asynccontextmanager
    async def domain(self, domain: str):
        async with self._global_sem:
            async with self._domain_locks[domain]:
                await self._wait_for_interval(domain)
                try:
                    yield
                finally:
                    self._last_request_at[domain] = time.monotonic()

    async def _wait_for_interval(self, domain: str) -> None:
        last = self._last_request_at.get(domain)
        if last is None:
            return
        jitter = 1.0 + random.uniform(-self._jitter_pct, self._jitter_pct)
        required = self._min_interval_sec * jitter
        elapsed = time.monotonic() - last
        remaining = required - elapsed
        if remaining > 0:
            await asyncio.sleep(remaining)
