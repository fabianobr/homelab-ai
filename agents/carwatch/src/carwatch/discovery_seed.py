"""src/carwatch/discovery_seed.py"""
from pathlib import Path
from urllib.parse import quote, urlencode

import yaml

from carwatch import fetcher
from carwatch.models import BrandsConfig
from carwatch.probe import validate_feed_content


def build_google_news_sources(brands: BrandsConfig, extra_locales: dict) -> list[dict]:
    """Build one default (en/US) Google News search-RSS source per brand,
    plus one additional source per brand for every locale dict found in
    each list under `extra_locales`.

    SPEC.md's original intent was to target the extra locales only at
    CN/IN-origin brands, but BrandEntry (Task 9) carries no
    region/country-of-origin field, and adding one would ripple back into
    Task 9's model and every brands.yaml entry — too invasive for this
    fix. Instead, every extra locale is applied uniformly across ALL
    brands: a simplification from the spec's nuance, but honest (no fake
    targeting logic) and harmless (a few extra low-yield Tier 4 sources
    per brand, not incorrect ones).
    """
    sources = []
    for brand in brands.brands:
        query = f'"{brand.name}" (unveil OR reveal OR debut OR launch)'

        default_params = urlencode(
            {"q": query, "hl": "en", "gl": "US", "ceid": "US:en"}, quote_via=quote
        )
        sources.append(
            {
                "domain": "news.google.com",
                "feed_url": f"https://news.google.com/rss/search?{default_params}",
                "kind": "gnews",
                "tier": 4,
                "region": "GLOBAL",
                "lang": "en",
            }
        )

        for lang_key, locale_list in extra_locales.items():
            for locale in locale_list:
                params = urlencode(
                    {"q": query, "hl": locale["hl"], "gl": locale["gl"], "ceid": locale["ceid"]},
                    quote_via=quote,
                )
                sources.append(
                    {
                        "domain": "news.google.com",
                        "feed_url": f"https://news.google.com/rss/search?{params}",
                        "kind": "gnews",
                        "tier": 4,
                        "region": locale["gl"],
                        "lang": lang_key,
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
    failed = 0
    for candidate in fixed_sources:
        # One dead candidate domain (DNS failure, refused connection, TLS
        # error) must not abort seeding of every remaining candidate.
        try:
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
        except Exception as exc:
            failed += 1
            if logger is not None:
                logger.warning(
                    "discovery_seed.failed",
                    feed_url=candidate["feed_url"],
                    error=f"{type(exc).__name__}: {exc}",
                )
            continue
        seeded += 1

    return {"attempted": len(fixed_sources), "seeded": seeded, "failed": failed}
