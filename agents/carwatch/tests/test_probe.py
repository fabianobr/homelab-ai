"""tests/test_probe.py"""
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import httpx
import respx

from carwatch import probe as probe_module
from carwatch.models import BrandEntry
from carwatch.probe import CANDIDATE_PATHS, probe_brand, run_probe
from carwatch.models import BrandsConfig


def _valid_rss(n_entries: int = 5, newest_days_ago: int = 1) -> str:
    now = datetime.now(timezone.utc)
    items = []
    for i in range(n_entries):
        days_ago = newest_days_ago + i
        pub = (now - timedelta(days=days_ago)).strftime("%a, %d %b %Y %H:%M:%S +0000")
        items.append(f"<item><title>Item {i}</title><link>https://x.com/{i}</link><pubDate>{pub}</pubDate></item>")
    return f"<?xml version='1.0'?><rss version='2.0'><channel>{''.join(items)}</channel></rss>"


def _allow_robots(host: str):
    respx.get(f"https://{host}/robots.txt").mock(
        return_value=httpx.Response(200, text="User-agent: *\nAllow: /\n")
    )


@respx.mock
async def test_probe_brand_succeeds_on_first_candidate_path():
    _allow_robots("press.example.com")
    respx.get("https://press.example.com/rss").mock(
        return_value=httpx.Response(200, text=_valid_rss())
    )

    feed_url, reason = await probe_brand(
        BrandEntry(name="Acme", press_domain="press.example.com")
    )

    assert feed_url == "https://press.example.com/rss"
    assert reason == "ok"


@respx.mock
async def test_probe_brand_falls_back_to_link_rel_discovery():
    _allow_robots("press.example.com")
    for path in ["/rss", "/feed", "/feed.rss", "/rss.xml", "/feeds/news.xml", "/en/rss", "/news/rss", "/press-releases/rss"]:
        respx.get(f"https://press.example.com{path}").mock(return_value=httpx.Response(404))
    # fetcher._is_blocked() flags any 200-status body under 500 chars as an
    # anti-bot challenge page regardless of content (see test_ingest.py for
    # the same gotcha), so pad this homepage fixture past that threshold
    # with a harmless trailing comment.
    respx.get("https://press.example.com/").mock(
        return_value=httpx.Response(
            200,
            text='<html><head><link rel="alternate" type="application/rss+xml" '
            'href="https://press.example.com/discovered.xml"></head></html>'
            f"<!-- {'x' * 500} -->",
        )
    )
    respx.get("https://press.example.com/discovered.xml").mock(
        return_value=httpx.Response(200, text=_valid_rss())
    )

    feed_url, reason = await probe_brand(
        BrandEntry(name="Acme", press_domain="press.example.com")
    )

    assert feed_url == "https://press.example.com/discovered.xml"


@respx.mock
async def test_probe_brand_rejects_feed_with_too_few_entries():
    _allow_robots("press.example.com")
    for path in ["/rss", "/feed", "/feed.rss", "/rss.xml", "/feeds/news.xml", "/en/rss", "/news/rss", "/press-releases/rss"]:
        respx.get(f"https://press.example.com{path}").mock(return_value=httpx.Response(404))
    respx.get("https://press.example.com/").mock(return_value=httpx.Response(404))

    feed_url, reason = await probe_brand(
        BrandEntry(name="Acme", press_domain="press.example.com")
    )

    assert feed_url is None
    assert reason == "no_feed_found"


async def test_probe_brand_without_press_domain_is_a_gap():
    feed_url, reason = await probe_brand(BrandEntry(name="Acme", press_domain=None))
    assert feed_url is None
    assert reason == "no_press_domain"


@respx.mock
async def test_run_probe_inserts_sources_and_writes_csvs(db_pool, tmp_path):
    _allow_robots("press.example.com")
    respx.get("https://press.example.com/rss").mock(return_value=httpx.Response(200, text=_valid_rss()))

    brands = BrandsConfig.model_validate(
        {
            "brands": [
                {"name": "Acme", "press_domain": "press.example.com"},
                {"name": "NoDomainBrand", "press_domain": None},
            ]
        }
    )
    out_csv = tmp_path / "sources.csv"
    gaps_csv = tmp_path / "gaps.csv"

    stats = await run_probe(db_pool, brands, out_csv, gaps_csv, logger=None)

    assert stats == {"probed": 2, "found": 1, "gaps": 1}
    assert out_csv.exists()
    assert "no_press_domain" in gaps_csv.read_text()
    async with db_pool.connection() as conn:
        result = await conn.execute("SELECT feed_url, status, tier FROM sources")
        row = await result.fetchone()
    assert row == ("https://press.example.com/rss", "probation", 1)


@respx.mock
async def test_run_probe_survives_one_failing_brand_and_probes_the_rest(db_pool, tmp_path):
    """CRITICAL 2: run_probe had no per-brand guard, so one raising press
    domain aborted the whole probe run."""
    _allow_robots("press.example.com")
    respx.get("https://press.example.com/rss").mock(
        return_value=httpx.Response(200, text=_valid_rss())
    )

    brands = BrandsConfig.model_validate(
        {
            "brands": [
                {"name": "Boom", "press_domain": "boom.example.com"},
                {"name": "Acme", "press_domain": "press.example.com"},
            ]
        }
    )

    real_probe_brand = probe_brand

    async def flaky_probe_brand(brand):
        if brand.press_domain == "boom.example.com":
            raise RuntimeError("simulated unhandled failure for this brand")
        return await real_probe_brand(brand)

    with patch("carwatch.probe.probe_brand", new=flaky_probe_brand):
        stats = await run_probe(db_pool, brands, tmp_path / "s.csv", tmp_path / "g.csv", logger=None)

    assert stats == {"probed": 2, "found": 1, "gaps": 1}
    assert "error" in (tmp_path / "g.csv").read_text()


@respx.mock
async def test_probe_brand_does_not_try_sitemaps_anymore():
    """IMPORTANT 5: feedparser extracts zero entries from a <urlset> sitemap,
    so validate_feed_content()'s >=5-entries check could never pass — the
    sitemap fallback was dead code costing 2 extra requests per brand."""
    _allow_robots("press.example.com")
    for path in CANDIDATE_PATHS:
        respx.get(f"https://press.example.com{path}").mock(return_value=httpx.Response(404))
    respx.get("https://press.example.com/").mock(return_value=httpx.Response(404))
    sitemap = respx.get("https://press.example.com/sitemap.xml")
    news_sitemap = respx.get("https://press.example.com/news-sitemap.xml")

    feed_url, reason = await probe_brand(
        BrandEntry(name="Acme", press_domain="press.example.com")
    )

    assert (feed_url, reason) == (None, "no_feed_found")
    assert sitemap.call_count == 0
    assert news_sitemap.call_count == 0
    assert not hasattr(probe_module, "_try_sitemaps")
