"""tests/test_discovery.py"""
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

from carwatch.discovery import (
    find_outbound_link_candidates,
    find_scoop_domain_candidates,
    register_and_validate_candidates,
    run_discovery,
)


async def _insert_source(db_pool, domain: str, tier: int, feed_url: str) -> int:
    async with db_pool.connection() as conn:
        result = await conn.execute(
            "INSERT INTO sources (domain, feed_url, kind, tier, status) "
            "VALUES (%s, %s, 'rss', %s, 'active') RETURNING id",
            (domain, feed_url, tier),
        )
        return (await result.fetchone())[0]


async def test_find_scoop_domain_candidates_finds_real_domain_behind_tier4_event(db_pool):
    tier4_id = await _insert_source(db_pool, "news.google.com", 4, "https://news.google.com/feed1")
    async with db_pool.connection() as conn:
        item = await conn.execute(
            "INSERT INTO raw_items (source_id, url, url_hash, title) "
            "VALUES (%s, 'https://newmedia.example.com/article', 'h1', 't') RETURNING id",
            (tier4_id,),
        )
        item_id = (await item.fetchone())[0]
        event = await conn.execute(
            "INSERT INTO launch_events (dedupe_key, brand, model, model_slug, stage, highlights, confidence) "
            "VALUES ('k1', 'X', 'Y', 'y', 'teaser', ARRAY['h'], 0.7) RETURNING id"
        )
        event_id = (await event.fetchone())[0]
        await conn.execute(
            "INSERT INTO event_sources (event_id, item_id, source_id) VALUES (%s, %s, %s)",
            (event_id, item_id, tier4_id),
        )

    candidates = await find_scoop_domain_candidates(db_pool)

    assert candidates == ["newmedia.example.com"]


async def test_find_outbound_link_candidates_matches_press_patterns(db_pool):
    tier3_id = await _insert_source(db_pool, "carscoops.com", 3, "https://carscoops.com/feed")
    body = (
        '<html><body><article>'
        '<a href="https://media.acme-motors.com/press-release">official</a>'
        '<a href="https://twitter.com/acme">social</a>'
        '</article></body></html>'
    )
    async with db_pool.connection() as conn:
        await conn.execute(
            "INSERT INTO raw_items (source_id, url, url_hash, title, body) "
            "VALUES (%s, 'https://carscoops.com/a', 'h1', 't', %s)",
            (tier3_id, body),
        )

    candidates = await find_outbound_link_candidates(db_pool)

    assert candidates == ["media.acme-motors.com"]


async def test_find_outbound_link_candidates_covers_all_four_configured_patterns(db_pool):
    """Regression test for the OUTBOUND_LINK_PATTERNS[".presse"] double-dot
    bug: f".{pattern}" on a pattern that already starts with "." built the
    literal needle "..presse", which no real hostname ever contains, so the
    ".presse" pattern silently matched nothing. Each of the four configured
    patterns ("media.", "press.", "newsroom.", ".presse") must be exercised
    by at least one realistic hostname here so a regression on any one of
    them fails this test instead of shipping unnoticed.
    """
    tier3_id = await _insert_source(db_pool, "carscoops.com", 3, "https://carscoops.com/feed")
    body = (
        '<html><body><article>'
        '<a href="https://media.acme-motors.com/press-release">media prefix</a>'
        '<a href="https://press.bmw-group.com/global/article">press prefix</a>'
        '<a href="https://newsroom.bmw.com/en/article">newsroom prefix</a>'
        '<a href="https://peugeot.presse.fr/communique">presse subdomain</a>'
        '<a href="https://twitter.com/acme">social, not a match</a>'
        '</article></body></html>'
    )
    async with db_pool.connection() as conn:
        await conn.execute(
            "INSERT INTO raw_items (source_id, url, url_hash, title, body) "
            "VALUES (%s, 'https://carscoops.com/a', 'h1', 't', %s)",
            (tier3_id, body),
        )

    candidates = await find_outbound_link_candidates(db_pool)

    assert candidates == [
        "media.acme-motors.com",
        "newsroom.bmw.com",
        "peugeot.presse.fr",
        "press.bmw-group.com",
    ]


async def test_register_and_validate_candidates_only_promotes_domains_with_a_valid_feed(db_pool):
    with patch(
        "carwatch.discovery.discover_feed_for_domain",
        new=AsyncMock(side_effect=lambda d: "https://good.com/rss" if d == "good.com" else None),
    ):
        stats = await register_and_validate_candidates(db_pool, ["good.com", "bad.com"], tier=1, logger=None)

    assert stats == {"attempted": 2, "registered": 1}
    async with db_pool.connection() as conn:
        result = await conn.execute("SELECT domain, status FROM sources ORDER BY domain")
        rows = await result.fetchall()
    # SPEC.md §14: both candidates get a `sources` row -- the rejected one
    # stays 'candidate' (never revisited) instead of leaving no trace, which
    # is what makes rejection self-healing (see next test).
    assert rows == [("bad.com", "candidate"), ("good.com", "probation")]


async def test_register_and_validate_candidates_persists_rejected_domain_with_a_placeholder_feed_url(db_pool):
    with patch("carwatch.discovery.discover_feed_for_domain", new=AsyncMock(return_value=None)):
        await register_and_validate_candidates(db_pool, ["bad.com"], tier=1, logger=None)

    async with db_pool.connection() as conn:
        result = await conn.execute("SELECT domain, status, feed_url FROM sources")
        row = await result.fetchone()
    assert row == ("bad.com", "candidate", "candidate://bad.com")


async def test_rejected_candidate_domain_is_never_reprobed_on_a_later_discovery_run(db_pool):
    """Regression test for the bug where a rejected domain left NO trace in
    `sources`, so it was handed back by find_scoop_domain_candidates and
    re-probed in full every subsequent run, forever. Before the fix this test
    fails: `candidates_again` would still contain "newmedia.example.com" and
    discover_feed_for_domain would be invoked a second time.
    """
    tier4_id = await _insert_source(db_pool, "news.google.com", 4, "https://news.google.com/feed1")
    async with db_pool.connection() as conn:
        item = await conn.execute(
            "INSERT INTO raw_items (source_id, url, url_hash, title) "
            "VALUES (%s, 'https://newmedia.example.com/article', 'h1', 't') RETURNING id",
            (tier4_id,),
        )
        item_id = (await item.fetchone())[0]
        event = await conn.execute(
            "INSERT INTO launch_events (dedupe_key, brand, model, model_slug, stage, highlights, confidence) "
            "VALUES ('k1', 'X', 'Y', 'y', 'teaser', ARRAY['h'], 0.7) RETURNING id"
        )
        event_id = (await event.fetchone())[0]
        await conn.execute(
            "INSERT INTO event_sources (event_id, item_id, source_id) VALUES (%s, %s, %s)",
            (event_id, item_id, tier4_id),
        )

    discover_mock = AsyncMock(return_value=None)
    with patch("carwatch.discovery.discover_feed_for_domain", new=discover_mock):
        candidates = await find_scoop_domain_candidates(db_pool)
        assert candidates == ["newmedia.example.com"]
        await register_and_validate_candidates(db_pool, candidates, tier=3, logger=None)

    discover_mock.assert_awaited_once_with("newmedia.example.com")
    async with db_pool.connection() as conn:
        result = await conn.execute(
            "SELECT status FROM sources WHERE domain = 'newmedia.example.com'"
        )
        assert (await result.fetchone())[0] == "candidate"

    discover_mock.reset_mock()
    with patch("carwatch.discovery.discover_feed_for_domain", new=discover_mock):
        candidates_again = await find_scoop_domain_candidates(db_pool)

    assert candidates_again == []
    discover_mock.assert_not_awaited()


async def test_find_outbound_link_candidates_excludes_bodies_older_than_the_scan_window(db_pool):
    """Regression test for the unbounded body-scan bug: without a fetched_at
    window, find_outbound_link_candidates re-parses the entire historical
    tier-3 archive every run. A body fetched 45 days ago (older than
    OUTBOUND_BODY_SCAN_WINDOW_DAYS=30) must be excluded.
    """
    tier3_id = await _insert_source(db_pool, "carscoops.com", 3, "https://carscoops.com/feed")
    body = (
        '<html><body><article>'
        '<a href="https://media.acme-motors.com/press-release">official</a>'
        '</article></body></html>'
    )
    old_fetched_at = datetime.now(timezone.utc) - timedelta(days=45)
    async with db_pool.connection() as conn:
        await conn.execute(
            "INSERT INTO raw_items (source_id, url, url_hash, title, body, fetched_at) "
            "VALUES (%s, 'https://carscoops.com/a', 'h1', 't', %s, %s)",
            (tier3_id, body, old_fetched_at),
        )

    candidates = await find_outbound_link_candidates(db_pool)

    assert candidates == []


async def test_run_discovery_orchestrates_both_heuristics(db_pool):
    with patch(
        "carwatch.discovery.find_scoop_domain_candidates", new=AsyncMock(return_value=["a.com"])
    ), patch(
        "carwatch.discovery.find_outbound_link_candidates", new=AsyncMock(return_value=["media.b.com"])
    ), patch(
        "carwatch.discovery.discover_feed_for_domain",
        new=AsyncMock(side_effect=lambda d: f"https://{d}/rss"),
    ):
        stats = await run_discovery(db_pool, logger=None)

    assert stats["total_registered"] == 2
