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
        self._domain_min_interval: dict[str, float] = {}

    def set_domain_min_interval(self, domain: str, seconds: float) -> None:
        """Override the minimum interval for a single domain (e.g. from that
        domain's robots.txt Crawl-delay), without affecting any other domain
        or the process-wide default.
        """
        self._domain_min_interval[domain] = seconds

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
        min_interval = self._domain_min_interval.get(domain, self._min_interval_sec)
        required = min_interval * jitter
        elapsed = time.monotonic() - last
        remaining = required - elapsed
        if remaining > 0:
            await asyncio.sleep(remaining)
