"""src/carwatch/discovery_seed.py"""
from pathlib import Path
from urllib.parse import quote, urlencode

import yaml

from carwatch import fetcher
from carwatch.models import BrandsConfig
from carwatch.probe import validate_feed_content


def build_google_news_sources(brands: BrandsConfig, extra_locales: dict) -> list[dict]:
    sources = []
    for brand in brands.brands:
        query = f'"{brand.name}" (unveil OR reveal OR debut OR launch)'
        params = urlencode({"q": query, "hl": "en", "gl": "US", "ceid": "US:en"}, quote_via=quote)
        sources.append(
            {
                "domain": "news.google.com",
                "feed_url": f"https://news.google.com/rss/search?{params}",
                "kind": "gnews",
                "tier": 4,
                "region": "GLOBAL",
                "lang": "en",
            }
        )
    return sources


def load_fixed_sources(settings_path: Path) -> list[dict]:
    data = yaml.safe_load(settings_path.read_text())
    fixed = data.get("fixed_sources", {})
    sources = []
    for tier_key, tier_num in (("tier2", 2), ("tier3", 3)):
        for entry in fixed.get(tier_key, []):
            sources.append(
                {
                    "domain": entry["feed_url"].split("/")[2],
                    "feed_url": entry["feed_url"],
                    "kind": "rss",
                    "tier": tier_num,
                    "region": entry.get("region", "GLOBAL"),
                    "lang": entry.get("lang", "en"),
                }
            )
    return sources


async def seed_fixed_sources(pool, fixed_sources: list[dict], logger) -> dict:
    seeded = 0
    for candidate in fixed_sources:
        result = await fetcher.fetch(candidate["feed_url"], kind="feed")
        if result.status != 200 or result.blocked or not validate_feed_content(result.body):
            if logger is not None:
                logger.warning("discovery_seed.rejected", feed_url=candidate["feed_url"])
            continue

        async with pool.connection() as conn:
            await conn.execute(
                "INSERT INTO sources (domain, feed_url, kind, tier, status, region, lang) "
                "VALUES (%(domain)s, %(feed_url)s, %(kind)s, %(tier)s, 'probation', %(region)s, %(lang)s) "
                "ON CONFLICT (feed_url) DO NOTHING",
                candidate,
            )
        seeded += 1

    return {"attempted": len(fixed_sources), "seeded": seeded}
