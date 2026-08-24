"""src/carwatch/discovery.py"""
from urllib.parse import urlsplit

from selectolax.parser import HTMLParser

from carwatch.probe import discover_feed_for_domain

OUTBOUND_LINK_PATTERNS = ("media.", "press.", "newsroom.", ".presse")


def _matches_outbound_pattern(hostname: str, pattern: str) -> bool:
    # A pattern that already starts with a dot (like ".presse") must not get
    # a second dot prepended when building the substring needle — naively
    # doing f".{pattern}" on ".presse" builds the literal "..presse", which
    # no real hostname ever contains, silently making that pattern
    # permanently dead. Patterns without a leading dot (e.g. "media.") still
    # get one prepended so they also match as a subdomain component, not
    # just as a literal prefix.
    needle = pattern if pattern.startswith(".") else f".{pattern}"
    return hostname.startswith(pattern) or needle in hostname


async def find_scoop_domain_candidates(pool) -> list[str]:
    async with pool.connection() as conn:
        result = await conn.execute(
            "SELECT DISTINCT ri.url FROM event_sources es "
            "JOIN raw_items ri ON ri.id = es.item_id "
            "JOIN sources s ON s.id = es.source_id "
            "WHERE s.tier = 4 "
            "AND es.seen_at = (SELECT min(seen_at) FROM event_sources es2 WHERE es2.event_id = es.event_id)"
        )
        urls = [r[0] for r in await result.fetchall()]
        existing_result = await conn.execute("SELECT DISTINCT domain FROM sources")
        existing_domains = {r[0] for r in await existing_result.fetchall()}

    candidates = set()
    for url in urls:
        domain = urlsplit(url).netloc.lower()
        if domain and domain != "news.google.com" and domain not in existing_domains:
            candidates.add(domain)
    return sorted(candidates)


async def find_outbound_link_candidates(pool) -> list[str]:
    async with pool.connection() as conn:
        result = await conn.execute(
            "SELECT ri.body FROM raw_items ri JOIN sources s ON s.id = ri.source_id "
            "WHERE s.tier = 3 AND ri.body IS NOT NULL"
        )
        bodies = [r[0] for r in await result.fetchall()]
        existing_result = await conn.execute("SELECT DISTINCT domain FROM sources")
        existing_domains = {r[0] for r in await existing_result.fetchall()}

    candidates = set()
    for body in bodies:
        tree = HTMLParser(body)
        for node in tree.css("a[href]"):
            href = node.attributes.get("href") or ""
            if not href.startswith("http"):
                continue
            hostname = urlsplit(href).netloc.lower()
            if not hostname or hostname in existing_domains:
                continue
            if any(_matches_outbound_pattern(hostname, p) for p in OUTBOUND_LINK_PATTERNS):
                candidates.add(hostname)
    return sorted(candidates)


async def register_and_validate_candidates(pool, domains: list[str], tier: int, logger) -> dict:
    registered = 0
    for domain in domains:
        feed_url = await discover_feed_for_domain(domain)
        if not feed_url:
            if logger is not None:
                logger.info("discovery.candidate_rejected", domain=domain)
            continue
        async with pool.connection() as conn:
            await conn.execute(
                "INSERT INTO sources (domain, feed_url, kind, tier, status, probation_since) "
                "VALUES (%s, %s, 'rss', %s, 'probation', now()) ON CONFLICT (feed_url) DO NOTHING",
                (domain, feed_url, tier),
            )
        registered += 1
    return {"attempted": len(domains), "registered": registered}


async def run_discovery(pool, logger) -> dict:
    scoop_domains = await find_scoop_domain_candidates(pool)
    outbound_domains = await find_outbound_link_candidates(pool)

    scoop_stats = await register_and_validate_candidates(pool, scoop_domains, tier=3, logger=logger)
    outbound_stats = await register_and_validate_candidates(pool, outbound_domains, tier=1, logger=logger)

    stats = {
        "scoop_candidates": scoop_stats,
        "outbound_candidates": outbound_stats,
        "total_registered": scoop_stats["registered"] + outbound_stats["registered"],
    }
    if logger is not None:
        logger.info("discovery.run", **stats)
    return stats
