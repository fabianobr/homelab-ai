"""src/carwatch/probe.py"""
import csv
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urljoin

import feedparser
from selectolax.parser import HTMLParser

from carwatch import fetcher
from carwatch.models import BrandEntry, BrandsConfig

CANDIDATE_PATHS = (
    "/rss", "/feed", "/feed.rss", "/rss.xml", "/feeds/news.xml",
    "/en/rss", "/news/rss", "/press-releases/rss",
)
MAX_FEED_AGE_DAYS = 90
MIN_FEED_ENTRIES = 5


def validate_feed_content(body: str | None) -> bool:
    if not body:
        return False
    parsed = feedparser.parse(body)
    if len(parsed.entries) < MIN_FEED_ENTRIES:
        return False
    newest = None
    for entry in parsed.entries:
        if entry.get("published_parsed"):
            published = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
            if newest is None or published > newest:
                newest = published
    if newest is None:
        return False
    return datetime.now(timezone.utc) - newest < timedelta(days=MAX_FEED_AGE_DAYS)


async def _try_candidate_paths(press_domain: str) -> str | None:
    for path in CANDIDATE_PATHS:
        url = f"https://{press_domain}{path}"
        result = await fetcher.fetch(url, kind="feed")
        if result.status == 200 and not result.blocked and validate_feed_content(result.body):
            return url
    return None


async def _try_link_rel_discovery(press_domain: str) -> str | None:
    home_url = f"https://{press_domain}/"
    result = await fetcher.fetch(home_url, kind="page")
    if result.status != 200 or result.blocked or not result.body:
        return None
    tree = HTMLParser(result.body)
    node = tree.css_first('link[rel="alternate"][type="application/rss+xml"]')
    if node is None or not node.attributes.get("href"):
        return None
    candidate_url = urljoin(home_url, node.attributes["href"])
    result = await fetcher.fetch(candidate_url, kind="feed")
    if result.status == 200 and not result.blocked and validate_feed_content(result.body):
        return candidate_url
    return None


async def _try_sitemaps(press_domain: str) -> str | None:
    for path in ("/sitemap.xml", "/news-sitemap.xml"):
        url = f"https://{press_domain}{path}"
        result = await fetcher.fetch(url, kind="feed")
        if result.status == 200 and not result.blocked and validate_feed_content(result.body):
            return url
    return None


async def probe_brand(brand: BrandEntry) -> tuple[str | None, str]:
    if not brand.press_domain:
        return None, "no_press_domain"

    for strategy in (_try_candidate_paths, _try_link_rel_discovery, _try_sitemaps):
        feed_url = await strategy(brand.press_domain)
        if feed_url:
            return feed_url, "ok"

    return None, "no_feed_found"


async def run_probe(pool, brands: BrandsConfig, out_csv: Path, gaps_csv: Path, logger) -> dict:
    found = 0
    gaps = 0
    out_rows = []
    gap_rows = []

    for brand in brands.brands:
        feed_url, reason = await probe_brand(brand)
        out_rows.append({"brand": brand.name, "feed_url": feed_url or "", "reason": reason})

        if feed_url:
            found += 1
            async with pool.connection() as conn:
                await conn.execute(
                    "INSERT INTO sources (domain, feed_url, kind, tier, status, brand_scope) "
                    "VALUES (%s, %s, 'rss', 1, 'probation', %s) "
                    "ON CONFLICT (feed_url) DO NOTHING",
                    (brand.press_domain, feed_url, [brand.name]),
                )
        else:
            gaps += 1
            gap_rows.append({"brand": brand.name, "reason": reason})

    out_csv.parent.mkdir(parents=True, exist_ok=True)
    with out_csv.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["brand", "feed_url", "reason"])
        writer.writeheader()
        writer.writerows(out_rows)

    gaps_csv.parent.mkdir(parents=True, exist_ok=True)
    with gaps_csv.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["brand", "reason"])
        writer.writeheader()
        writer.writerows(gap_rows)

    stats = {"probed": len(brands.brands), "found": found, "gaps": gaps}
    if logger is not None:
        logger.info("probe.run", **stats)
    return stats
