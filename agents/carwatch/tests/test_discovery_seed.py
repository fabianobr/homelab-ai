"""tests/test_discovery_seed.py"""
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import respx

from carwatch.discovery_seed import (
    build_google_news_sources,
    load_fixed_sources,
    seed_fixed_sources,
)
from carwatch.models import BrandsConfig

CONFIG_DIR = Path(__file__).resolve().parents[1] / "config"


def test_build_google_news_sources_one_entry_per_brand_by_default():
    brands = BrandsConfig.model_validate({"brands": [{"name": "Toyota"}, {"name": "BYD"}]})
    sources = build_google_news_sources(brands, extra_locales={})

    assert len(sources) == 2
    toyota = next(s for s in sources if s["domain"] == "news.google.com")
    assert "Toyota" in toyota["feed_url"]
    assert toyota["tier"] == 4


def test_load_fixed_sources_reads_tier2_and_tier3_from_settings_yaml():
    sources = load_fixed_sources(CONFIG_DIR / "settings.yaml")

    assert any(s["tier"] == 2 for s in sources)
    assert any(s["tier"] == 3 for s in sources)
    motor1 = next(s for s in sources if "motor1.com" in s["feed_url"])
    assert motor1["tier"] == 3


@respx.mock
async def test_seed_fixed_sources_only_inserts_validated_feeds(db_pool):
    respx.get("https://good.example.com/robots.txt").mock(
        return_value=httpx.Response(200, text="User-agent: *\nAllow: /\n")
    )
    respx.get("https://bad.example.com/robots.txt").mock(
        return_value=httpx.Response(200, text="User-agent: *\nAllow: /\n")
    )
    # NOTE: pubDate must be recent relative to "now" — validate_feed_content
    # (Task 13) rejects feeds whose newest entry is older than 90 days. The
    # brief's literal test used a fixed date (Jan 2026) that has since aged
    # past that window; generated relative to datetime.now() here instead,
    # matching the precedent already set in tests/test_probe.py's
    # _valid_rss() helper.
    now = datetime.now(timezone.utc)
    good_feed = "<?xml version='1.0'?><rss><channel>" + "".join(
        f"<item><title>i{i}</title><link>https://x/{i}</link>"
        f"<pubDate>{(now - timedelta(days=i)).strftime('%a, %d %b %Y %H:%M:%S +0000')}</pubDate></item>"
        for i in range(5)
    ) + "</channel></rss>"
    respx.get("https://good.example.com/feed").mock(return_value=httpx.Response(200, text=good_feed))
    respx.get("https://bad.example.com/feed").mock(return_value=httpx.Response(404))

    candidates = [
        {"domain": "good.example.com", "feed_url": "https://good.example.com/feed", "kind": "rss", "tier": 3, "region": "GLOBAL", "lang": "en"},
        {"domain": "bad.example.com", "feed_url": "https://bad.example.com/feed", "kind": "rss", "tier": 3, "region": "GLOBAL", "lang": "en"},
    ]

    stats = await seed_fixed_sources(db_pool, candidates, logger=None)

    assert stats == {"attempted": 2, "seeded": 1}
    async with db_pool.connection() as conn:
        result = await conn.execute("SELECT feed_url FROM sources")
        rows = await result.fetchall()
    assert rows == [("https://good.example.com/feed",)]
