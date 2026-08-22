"""tests/test_ratelimit.py"""
import asyncio
import time

from carwatch.ratelimit import RateLimiter


async def test_same_domain_requests_are_spaced_by_min_interval():
    limiter = RateLimiter(min_interval_sec=0.2, global_concurrency=10, jitter_pct=0.0)

    start = time.monotonic()
    async with limiter.domain("example.com"):
        pass
    async with limiter.domain("example.com"):
        pass
    elapsed = time.monotonic() - start

    assert elapsed >= 0.2


async def test_different_domains_do_not_wait_on_each_other():
    limiter = RateLimiter(min_interval_sec=1.0, global_concurrency=10, jitter_pct=0.0)

    start = time.monotonic()
    async with limiter.domain("a.com"):
        pass
    async with limiter.domain("b.com"):
        pass
    elapsed = time.monotonic() - start

    assert elapsed < 0.5


async def test_same_domain_concurrency_is_serialized():
    limiter = RateLimiter(min_interval_sec=0.0, global_concurrency=10, jitter_pct=0.0)
    order = []

    async def worker(name):
        async with limiter.domain("example.com"):
            order.append(f"{name}-start")
            await asyncio.sleep(0.05)
            order.append(f"{name}-end")

    await asyncio.gather(worker("a"), worker("b"))

    assert order == ["a-start", "a-end", "b-start", "b-end"] or order == [
        "b-start",
        "b-end",
        "a-start",
        "a-end",
    ]


async def test_global_concurrency_is_capped():
    limiter = RateLimiter(min_interval_sec=0.0, global_concurrency=2, jitter_pct=0.0)
    active = 0
    max_active = 0

    async def worker(domain):
        nonlocal active, max_active
        async with limiter.domain(domain):
            active += 1
            max_active = max(max_active, active)
            await asyncio.sleep(0.05)
            active -= 1

    await asyncio.gather(*(worker(f"d{i}.com") for i in range(5)))

    assert max_active <= 2
