"""src/carwatch/fetcher.py"""
import asyncio
import random
import time
from dataclasses import dataclass
from typing import Literal
from urllib.parse import urlsplit

import httpx
import structlog

from carwatch import breaker, robots
from carwatch.db import get_open_pool
from carwatch.ratelimit import RateLimiter
from carwatch.settings import get_settings

logger = structlog.get_logger()

# httpx.RequestError's three direct subtrees, spelled out: TransportError
# (timeouts, connect/read/write errors, proxy errors, local/remote protocol
# errors), TooManyRedirects and DecodingError. All of them are realistic
# against 20+ third-party press-room domains and all of them used to escape
# this module — the single HTTP egress point — uncaught.
_RETRYABLE_EXCEPTIONS = (httpx.TransportError, httpx.TooManyRedirects, httpx.DecodingError)

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


async def _raw_get(url: str, headers: dict | None = None, timeout: float = 20.0):
    client = _get_client()
    return await client.get(url, headers=headers or {}, timeout=timeout)


async def _robots_get(robots_url: str):
    """Fetch robots.txt, mapping any transport failure to None.

    robots.is_allowed() treats a None response exactly like a 4xx one and
    fails open. Doing the httpx-typed part here keeps HTTP-library knowledge
    inside this module (the single egress point) while making sure an
    unreachable domain's robots.txt can never abort the caller's whole batch.
    """
    try:
        return await _raw_get(robots_url, timeout=10.0)
    except httpx.HTTPError:
        return None


def _is_blocked(status: int, body: str, kind: Literal["feed", "page"] = "page") -> bool:
    if status != 200:
        return False
    # The "suspiciously short body" heuristic only makes sense for HTML pages,
    # where an anti-bot interstitial is a tiny document. A legitimately small
    # RSS/Atom feed (few recent items) is perfectly normal, and flagging it as
    # blocked feeds the circuit breaker: 24h pause -> probation -> permanently
    # blocked, blacklisting a valid feed purely for being short.
    if kind == "page" and len(body) < 500:
        return True
    return any(marker in body for marker in _BLOCK_MARKERS)


def _is_retryable(status: int, exc: Exception | None) -> bool:
    if exc is not None:
        return isinstance(exc, _RETRYABLE_EXCEPTIONS)
    return status >= 500 or status == 429


def _log_result(
    *,
    domain: str,
    status: int,
    started: float,
    not_modified: bool = False,
    blocked: bool = False,
    reason: str | None = None,
) -> None:
    """SPEC.md §18's `fetch.result` observability event, one per fetch()."""
    logger.info(
        "fetch.result",
        domain=domain,
        status=status,
        ms=int((time.monotonic() - started) * 1000),
        not_modified=not_modified,
        blocked=blocked,
        reason=reason,
    )


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
    started = time.monotonic()

    # Circuit-breaker ENFORCEMENT. record_fetch_result() below writes breaker
    # state, but until now nothing read it back here: only ingest.py's
    # source-selection SQL honoured it, leaving probe.py and
    # discovery_seed.py free to keep hammering a blocked source.
    if source_id is not None and await breaker.is_source_paused(
        await get_open_pool(), source_id
    ):
        _log_result(domain=domain, status=0, started=started, reason="breaker")
        return FetchResult(0, None, None, None, False, False, "breaker")

    limiter = _get_limiter()
    async with limiter.domain(domain):
        # The robots.txt check can itself issue a real HTTP request (on a
        # cache miss) — it must happen inside the domain's rate-limit scope
        # so that request also consumes this domain's slot, not before it.
        allowed, crawl_delay = await robots.is_allowed(
            url, settings.user_agent, fetch_fn=_robots_get
        )
        if not allowed:
            # Not a fetch attempt against the target URL — no breaker call.
            _log_result(domain=domain, status=0, started=started, reason="robots")
            return FetchResult(0, None, None, None, False, False, "robots")

        if crawl_delay:
            limiter.set_domain_min_interval(domain, crawl_delay)

        conditional_headers: dict[str, str] = {}
        if source_id is not None:
            pool = await get_open_pool()
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

        response = None
        exc: Exception | None = None
        attempts = 0
        max_attempts = 3

        while attempts < max_attempts:
            attempts += 1
            exc = None
            try:
                response = await _raw_get(url, headers=conditional_headers, timeout=timeout)
            except _RETRYABLE_EXCEPTIONS as e:
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
                    try:
                        wait_seconds = float(retry_after)
                    except ValueError:
                        # Legal HTTP-date Retry-After values (RFC 7231
                        # §7.1.3) aren't numeric; parsing them is out of
                        # scope here, so fall back to the exponential wait
                        # already computed above instead of crashing the
                        # single HTTP egress point.
                        pass
            wait_seconds *= 1.0 + random.uniform(-0.2, 0.2)

            await asyncio.sleep(max(wait_seconds, 0.0))

        if exc is not None:
            if source_id is not None:
                pool = await get_open_pool()
                await breaker.record_fetch_result(pool, source_id, status=0, blocked=False)
            reason = f"{type(exc).__name__}: {exc}"
            _log_result(domain=domain, status=0, started=started, reason=reason)
            return FetchResult(0, None, None, None, False, False, reason)

        status = response.status_code

        if status == 304:
            if source_id is not None:
                pool = await get_open_pool()
                await breaker.record_fetch_result(pool, source_id, status=304, blocked=False)
            _log_result(domain=domain, status=304, started=started, not_modified=True)
            return FetchResult(304, None, None, None, True, False, None)

        body = response.text
        blocked = _is_blocked(status, body, kind)
        etag = response.headers.get("ETag")
        last_modified = response.headers.get("Last-Modified")

        if source_id is not None:
            pool = await get_open_pool()
            await breaker.record_fetch_result(pool, source_id, status=status, blocked=blocked)
            if status == 200 and not blocked and (etag or last_modified):
                async with pool.connection() as conn:
                    await conn.execute(
                        "UPDATE sources SET etag = %s, last_modified = %s WHERE id = %s",
                        (etag, last_modified, source_id),
                    )

        _log_result(domain=domain, status=status, started=started, blocked=blocked)
        return FetchResult(
            status=status,
            body=body if not blocked else None,
            etag=etag,
            last_modified=last_modified,
            not_modified=False,
            blocked=blocked,
            reason=None,
        )
