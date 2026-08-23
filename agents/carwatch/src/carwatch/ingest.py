"""src/carwatch/ingest.py"""
import hashlib
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import feedparser

from carwatch import fetcher

_TRACKING_PARAM_PREFIXES = ("utm_",)
_TRACKING_PARAM_NAMES = {"fbclid", "gclid", "ref", "source"}
_BACKLOG_CUTOFF_DAYS = 45


def normalize_url(url: str) -> str:
    parts = urlsplit(url.strip())
    host = parts.netloc.lower()
    query_pairs = [
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if key not in _TRACKING_PARAM_NAMES and not key.startswith(_TRACKING_PARAM_PREFIXES)
    ]
    path = parts.path.rstrip("/") or ""
    return urlunsplit((parts.scheme.lower(), host, path, urlencode(query_pairs), ""))


def _url_hash(normalized_url: str) -> str:
    return hashlib.sha256(normalized_url.encode("utf-8")).hexdigest()


async def ingest_source(pool, source_id: int, feed_url: str, logger) -> dict:
    result = await fetcher.fetch(feed_url, kind="feed", source_id=source_id)

    if result.not_modified or result.blocked or result.body is None:
        return {"items_new": 0, "not_modified": result.not_modified}

    # feedparser.parse() must receive the already-fetched body STRING, never
    # a URL — passing a URL would make feedparser perform its own HTTP
    # request, bypassing fetcher.fetch() as the single HTTP egress point
    # (the invariant enforced by Task 8's guardrail test). RSS/Atom bodies
    # never start with "http", so feedparser will never mistake this string
    # for a URL to fetch on its own.
    parsed = feedparser.parse(result.body)
    cutoff = datetime.now(timezone.utc) - timedelta(days=_BACKLOG_CUTOFF_DAYS)

    items_new = 0
    async with pool.connection() as conn:
        for entry in parsed.entries:
            title = entry.get("title", "").strip()
            link = entry.get("link", "").strip()
            if not title or not link:
                continue

            published_at = None
            if entry.get("published_parsed"):
                published_at = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
            if published_at is not None and published_at < cutoff:
                continue

            normalized = normalize_url(link)
            url_hash = _url_hash(normalized)
            summary = entry.get("summary")

            row = await conn.execute(
                "INSERT INTO raw_items "
                "(source_id, url, url_hash, title, summary, published_at, status) "
                "VALUES (%s, %s, %s, %s, %s, %s, 'new') "
                "ON CONFLICT (url_hash) DO NOTHING RETURNING id",
                (source_id, normalized, url_hash, title, summary, published_at),
            )
            if await row.fetchone() is not None:
                items_new += 1

        if items_new > 0:
            await conn.execute(
                "UPDATE sources SET last_item_at = now() WHERE id = %s", (source_id,)
            )

    return {"items_new": items_new, "not_modified": False}


async def run_ingest(pool, logger) -> dict:
    start = time.monotonic()
    async with pool.connection() as conn:
        result = await conn.execute(
            "SELECT id, feed_url FROM sources "
            "WHERE status IN ('active', 'probation') "
            "AND (blocked_until IS NULL OR blocked_until < now())"
        )
        eligible = await result.fetchall()

    items_new_total = 0
    sources_failed = 0
    for source_id, feed_url in eligible:
        # One unreachable/misbehaving source must never abort the batch: across
        # 20+ third-party press-room domains at least one failing per run is
        # routine, and the remaining sources still have to be ingested.
        try:
            stats = await ingest_source(pool, source_id, feed_url, logger)
        except Exception as exc:
            sources_failed += 1
            if logger is not None:
                logger.warning(
                    "ingest.source_failed",
                    source_id=source_id,
                    feed_url=feed_url,
                    error=f"{type(exc).__name__}: {exc}",
                )
            continue
        items_new_total += stats["items_new"]

    elapsed_ms = int((time.monotonic() - start) * 1000)
    result = {
        "sources_checked": len(eligible),
        "sources_failed": sources_failed,
        "items_new": items_new_total,
        "ms": elapsed_ms,
    }
    if logger is not None:
        logger.info("ingest.cycle", **result)
    return result
