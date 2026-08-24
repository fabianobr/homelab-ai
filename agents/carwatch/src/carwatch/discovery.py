"""src/carwatch/discovery.py"""
from urllib.parse import urlsplit

from psycopg.errors import UniqueViolation
from selectolax.parser import HTMLParser

from carwatch.probe import discover_feed_for_domain

OUTBOUND_LINK_PATTERNS = ("media.", "press.", "newsroom.", ".presse")

# Bounds find_outbound_link_candidates' tier-3 raw_items body scan to recent
# history. Without this, the query re-parses the ENTIRE historical archive of
# tier-3 article bodies every single week -- an unbounded, ever-growing
# in-memory HTML-parsing cost. Mirrors dedupe.py's EXACT_MATCH_WINDOW_DAYS/
# FUZZY_MATCH_WINDOW_DAYS style.
OUTBOUND_BODY_SCAN_WINDOW_DAYS = 30


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
            "WHERE s.tier = 3 AND ri.body IS NOT NULL "
            "AND ri.fetched_at >= now() - make_interval(days => %s)",
            (OUTBOUND_BODY_SCAN_WINDOW_DAYS,),
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
    """Probe each candidate domain for a feed and register it in `sources`.

    SPEC.md §14: "Candidatos entram como status='candidate', passam pelo
    probe de validação de feed, e vão para probation se válidos." A `sources`
    row is inserted for EVERY candidate up front, before the (slow, ~3s
    rate-limited) feed probe -- not just for ones that turn out to have a
    real feed. This is what makes rejection self-healing: once a domain has
    ANY row in `sources`, find_scoop_domain_candidates/
    find_outbound_link_candidates's `domain NOT IN (SELECT domain FROM
    sources)` filter excludes it from every future run for free. Before this
    fix, a rejected domain left no trace in the DB and was re-probed in full,
    forever, every week -- an unbounded, monotonically growing cost that could
    blow the systemd unit's 20-minute timeout.

    feed_url is NOT NULL UNIQUE, so a not-yet-validated candidate row gets a
    synthetic `candidate://<domain>` placeholder; a validated candidate has
    that placeholder overwritten with the real feed URL when it's promoted to
    'probation'.
    """
    registered = 0
    for domain in domains:
        async with pool.connection() as conn:
            insert_result = await conn.execute(
                "INSERT INTO sources (domain, feed_url, kind, tier, status) "
                "VALUES (%s, %s, 'rss', %s, 'candidate') "
                "ON CONFLICT (feed_url) DO NOTHING RETURNING id",
                (domain, f"candidate://{domain}", tier),
            )
            row = await insert_result.fetchone()

        if row is None:
            # Defensive: this domain already has a sources row (e.g. a race
            # within the same run producing the same candidate twice via both
            # heuristics). existing_domains's exclusion filter is meant to
            # prevent this from happening at all; skip rather than re-probe.
            continue
        source_id = row[0]

        feed_url = await discover_feed_for_domain(domain)
        if not feed_url:
            if logger is not None:
                logger.info("discovery.candidate_rejected", domain=domain)
            continue

        try:
            async with pool.connection() as conn:
                await conn.execute(
                    "UPDATE sources SET feed_url = %s, status = 'probation', probation_since = now() "
                    "WHERE id = %s",
                    (feed_url, source_id),
                )
        except UniqueViolation:
            # Two different candidate domains resolved to the identical feed
            # URL (e.g. both redirect to the same underlying feed). feed_url
            # is UNIQUE, so the second one can't be promoted -- leave its row
            # as 'candidate' (harmless, and still excluded from future
            # re-probing) rather than letting this crash the whole run.
            if logger is not None:
                logger.warning("discovery.candidate_duplicate_feed_url", domain=domain, feed_url=feed_url)
            continue
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
