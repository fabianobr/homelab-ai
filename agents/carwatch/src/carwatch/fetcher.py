"""src/carwatch/fetcher.py"""
import asyncio
import random
from dataclasses import dataclass
from typing import Literal
from urllib.parse import urlsplit

import httpx
from psycopg_pool import AsyncConnectionPool

from carwatch import breaker, robots
from carwatch.db import get_pool
from carwatch.ratelimit import RateLimiter
from carwatch.settings import get_settings

_BLOCK_MARKERS = (
    "Just a moment",
    "Attention Required",
    "cf-browser-verification",
    "DataDome",
    "px-captcha",
    "Access Denied",
    "unusual traffic",
)

_client: httpx.AsyncClient | None = None
_limiter: RateLimiter | None = None


@dataclass
class FetchResult:
    status: int
    body: str | None
    etag: str | None
    last_modified: str | None
    not_modified: bool
    blocked: bool
    reason: str | None


def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        settings = get_settings()
        _client = httpx.AsyncClient(
            http2=True,
            follow_redirects=True,
            headers={"User-Agent": settings.user_agent},
        )
    return _client


def _get_limiter() -> RateLimiter:
    global _limiter
    if _limiter is None:
        settings = get_settings()
        _limiter = RateLimiter(
            min_interval_sec=settings.fetch_min_interval_sec,
            global_concurrency=settings.fetch_global_concurrency,
        )
    return _limiter


async def close_client() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


async def _get_open_pool() -> AsyncConnectionPool:
    """Return the module-level DB pool, opening it first if needed.

    `get_pool()` constructs the pool lazily with `open=False`; calling
    `.connection()` on an unopened pool raises `PoolClosed`. `.open()` is
    documented as safe to call again on an already-open pool, so this can be
    called unconditionally at every call site instead of racing on a private
    `_opened` check.
    """
    pool = get_pool()
    await pool.open()
    return pool


async def _raw_get(url: str, headers: dict | None = None, timeout: float = 20.0):
    client = _get_client()
    return await client.get(url, headers=headers or {}, timeout=timeout)


def _is_blocked(status: int, body: str) -> bool:
    if status != 200:
        return False
    if len(body) < 500:
        return True
    return any(marker in body for marker in _BLOCK_MARKERS)


def _is_retryable(status: int, exc: Exception | None) -> bool:
    if exc is not None:
        return isinstance(exc, (httpx.TimeoutException, httpx.ConnectError))
    return status >= 500 or status == 429


async def fetch(
    url: str,
    *,
    kind: Literal["feed", "page"] = "page",
    source_id: int | None = None,
    timeout: float = 20.0,
) -> FetchResult:
    settings = get_settings()
    parts = urlsplit(url)
    domain = parts.netloc

    allowed, crawl_delay = await robots.is_allowed(
        url, settings.user_agent, fetch_fn=lambda robots_url: _raw_get(robots_url, timeout=10.0)
    )
    if not allowed:
        return FetchResult(0, None, None, None, False, False, "robots")

    conditional_headers: dict[str, str] = {}
    if source_id is not None:
        pool = await _get_open_pool()
        async with pool.connection() as conn:
            result = await conn.execute(
                "SELECT etag, last_modified FROM sources WHERE id = %s", (source_id,)
            )
            row = await result.fetchone()
            if row:
                etag, last_modified = row
                if etag:
                    conditional_headers["If-None-Match"] = etag
                if last_modified:
                    conditional_headers["If-Modified-Since"] = last_modified

    limiter = _get_limiter()
    async with limiter.domain(domain):
        if crawl_delay:
            limiter._min_interval_sec = max(limiter._min_interval_sec, crawl_delay)

        response = None
        exc: Exception | None = None
        attempts = 0
        max_attempts = 3

        while attempts < max_attempts:
            attempts += 1
            exc = None
            try:
                response = await _raw_get(url, headers=conditional_headers, timeout=timeout)
            except (httpx.TimeoutException, httpx.ConnectError) as e:
                exc = e
                response = None

            if exc is None and response.status_code in (403, 404, 410):
                break
            if exc is None and not _is_retryable(response.status_code, None):
                break
            if attempts >= max_attempts:
                break

            wait_seconds = 2.0 ** attempts
            if response is not None and response.status_code in (429, 503):
                retry_after = response.headers.get("Retry-After")
                if retry_after is not None:
                    wait_seconds = float(retry_after)
            wait_seconds *= 1.0 + random.uniform(-0.2, 0.2)

            await asyncio.sleep(max(wait_seconds, 0.0))

        if exc is not None:
            if source_id is not None:
                pool = await _get_open_pool()
                await breaker.record_fetch_result(pool, source_id, status=0, blocked=False)
            return FetchResult(0, None, None, None, False, False, str(exc))

        status = response.status_code

        if status == 304:
            if source_id is not None:
                pool = await _get_open_pool()
                await breaker.record_fetch_result(pool, source_id, status=304, blocked=False)
            return FetchResult(304, None, None, None, True, False, None)

        body = response.text
        blocked = _is_blocked(status, body)
        etag = response.headers.get("ETag")
        last_modified = response.headers.get("Last-Modified")

        if source_id is not None:
            pool = await _get_open_pool()
            await breaker.record_fetch_result(pool, source_id, status=status, blocked=blocked)
            if status == 200 and not blocked and (etag or last_modified):
                async with pool.connection() as conn:
                    await conn.execute(
                        "UPDATE sources SET etag = %s, last_modified = %s WHERE id = %s",
                        (etag, last_modified, source_id),
                    )

        return FetchResult(
            status=status,
            body=body if not blocked else None,
            etag=etag,
            last_modified=last_modified,
            not_modified=False,
            blocked=blocked,
            reason=None,
        )
