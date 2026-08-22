"""tests/test_probe.py"""
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import respx

from carwatch.models import BrandEntry
from carwatch.probe import probe_brand, run_probe
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
    respx.get("https://press.example.com/sitemap.xml").mock(return_value=httpx.Response(404))
    respx.get("https://press.example.com/news-sitemap.xml").mock(return_value=httpx.Response(404))

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
