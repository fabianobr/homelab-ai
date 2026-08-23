"""tests/test_ingest.py"""
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import httpx
import respx

from carwatch.ingest import ingest_source, normalize_url, run_ingest


def test_normalize_url_strips_tracking_params_and_fragment_and_trailing_slash():
    url = "HTTPS://Example.com/News/Article/?utm_source=x&fbclid=y&id=1#section"
    assert normalize_url(url) == "https://example.com/News/Article?id=1"


def test_normalize_url_lowercases_host_only():
    assert normalize_url("https://EXAMPLE.com/Path/") == "https://example.com/Path"


def _rss(items: list[tuple[str, str, datetime]]) -> str:
    entries = "".join(
        f"<item><title>{title}</title><link>{link}</link>"
        f"<pubDate>{pub.strftime('%a, %d %b %Y %H:%M:%S +0000')}</pubDate></item>"
        for title, link, pub in items
    )
    # fetcher._is_blocked() flags any 200-status body under 500 chars as an
    # anti-bot challenge page regardless of content, so a bare-bones RSS
    # fixture (well under 500 chars) would be silently discarded before ever
    # reaching feedparser. Pad with a harmless channel description, the same
    # way test_fetcher.py pads its fixtures, to stay above that threshold.
    padding = "x" * 500
    return (
        "<?xml version='1.0'?><rss version='2.0'><channel>"
        f"<description>{padding}</description>{entries}</channel></rss>"
    )


async def _insert_source(db_pool, feed_url: str) -> int:
    async with db_pool.connection() as conn:
        result = await conn.execute(
            "INSERT INTO sources (domain, feed_url, kind, tier, status) "
            "VALUES ('example.com', %s, 'rss', 1, 'active') RETURNING id",
            (feed_url,),
        )
        return (await result.fetchone())[0]


@respx.mock
async def test_ingest_source_inserts_recent_item_and_skips_old_one(db_pool):
    respx.get("https://example.com/robots.txt").mock(
        return_value=httpx.Response(200, text="User-agent: *\nAllow: /\n")
    )
    now = datetime.now(timezone.utc)
    recent = now - timedelta(days=5)
    old = now - timedelta(days=100)
    body = _rss(
        [
            ("Recent launch", "https://example.com/recent", recent),
            ("Old launch", "https://example.com/old", old),
        ]
    )
    respx.get("https://example.com/feed.xml").mock(return_value=httpx.Response(200, text=body))
    source_id = await _insert_source(db_pool, "https://example.com/feed.xml")

    stats = await ingest_source(db_pool, source_id, "https://example.com/feed.xml", logger=None)

    assert stats["items_new"] == 1
    async with db_pool.connection() as conn:
        result = await conn.execute("SELECT title FROM raw_items")
        rows = await result.fetchall()
    assert rows == [("Recent launch",)]


@respx.mock
async def test_ingest_source_is_idempotent_on_second_run(db_pool):
    respx.get("https://example.com/robots.txt").mock(
        return_value=httpx.Response(200, text="User-agent: *\nAllow: /\n")
    )
    now = datetime.now(timezone.utc)
    body = _rss([("Same item", "https://example.com/same", now - timedelta(days=1))])
    route = respx.get("https://example.com/feed.xml").mock(
        return_value=httpx.Response(200, text=body)
    )
    source_id = await _insert_source(db_pool, "https://example.com/feed.xml")

    first = await ingest_source(db_pool, source_id, "https://example.com/feed.xml", logger=None)
    second = await ingest_source(db_pool, source_id, "https://example.com/feed.xml", logger=None)

    assert first["items_new"] == 1
    assert second["items_new"] == 0
    async with db_pool.connection() as conn:
        result = await conn.execute("SELECT count(*) FROM raw_items")
        count = (await result.fetchone())[0]
    assert count == 1


@respx.mock
async def test_run_ingest_only_selects_active_and_probation_sources(db_pool):
    respx.get("https://example.com/robots.txt").mock(
        return_value=httpx.Response(200, text="User-agent: *\nAllow: /\n")
    )
    now = datetime.now(timezone.utc)
    body = _rss([("Item", "https://example.com/x", now)])
    respx.get("https://example.com/active-feed").mock(return_value=httpx.Response(200, text=body))

    async with db_pool.connection() as conn:
        await conn.execute(
            "INSERT INTO sources (domain, feed_url, kind, tier, status) VALUES "
            "('example.com', 'https://example.com/active-feed', 'rss', 1, 'active'), "
            "('example.com', 'https://example.com/retired-feed', 'rss', 1, 'retired')"
        )

    stats = await run_ingest(db_pool, logger=None)

    assert stats["sources_checked"] == 1
    assert stats["items_new"] == 1


@respx.mock
async def test_run_ingest_survives_one_failing_source_and_processes_the_rest(db_pool):
    """CRITICAL 2: run_ingest had no per-source guard, so one raising source
    (routine across 20+ third-party domains) aborted the whole weekly run and
    every later source went un-ingested."""
    respx.get("https://example.com/robots.txt").mock(
        return_value=httpx.Response(200, text="User-agent: *\nAllow: /\n")
    )
    now = datetime.now(timezone.utc)
    respx.get("https://example.com/good-feed").mock(
        return_value=httpx.Response(200, text=_rss([("Item", "https://example.com/x", now)]))
    )

    async with db_pool.connection() as conn:
        await conn.execute(
            "INSERT INTO sources (domain, feed_url, kind, tier, status) VALUES "
            "('example.com', 'https://example.com/broken-feed', 'rss', 1, 'active'), "
            "('example.com', 'https://example.com/good-feed', 'rss', 1, 'active')"
        )

    real_ingest_source = ingest_source

    async def flaky_ingest_source(pool, source_id, feed_url, logger):
        if feed_url.endswith("broken-feed"):
            raise RuntimeError("simulated unhandled failure for this source")
        return await real_ingest_source(pool, source_id, feed_url, logger)

    with patch("carwatch.ingest.ingest_source", new=flaky_ingest_source):
        stats = await run_ingest(db_pool, logger=None)

    assert stats["sources_checked"] == 2
    assert stats["sources_failed"] == 1
    assert stats["items_new"] == 1  # the healthy source was still ingested


@respx.mock
async def test_run_ingest_survives_a_dns_failure_on_a_real_source(db_pool):
    """The realistic shape of the same bug: an unresolvable domain whose
    robots.txt request raises before the target request is ever made."""
    respx.get("https://dead.example.com/robots.txt").mock(
        side_effect=httpx.ConnectError("Name or service not known")
    )
    respx.get("https://dead.example.com/feed").mock(
        side_effect=httpx.ConnectError("Name or service not known")
    )
    respx.get("https://example.com/robots.txt").mock(
        return_value=httpx.Response(200, text="User-agent: *\nAllow: /\n")
    )
    now = datetime.now(timezone.utc)
    respx.get("https://example.com/good-feed").mock(
        return_value=httpx.Response(200, text=_rss([("Item", "https://example.com/x", now)]))
    )

    async with db_pool.connection() as conn:
        await conn.execute(
            "INSERT INTO sources (domain, feed_url, kind, tier, status) VALUES "
            "('dead.example.com', 'https://dead.example.com/feed', 'rss', 1, 'active'), "
            "('example.com', 'https://example.com/good-feed', 'rss', 1, 'active')"
        )

    stats = await run_ingest(db_pool, logger=None)

    assert stats["sources_checked"] == 2
    assert stats["items_new"] == 1
