"""src/carwatch/cli.py"""
import asyncio
from pathlib import Path

import typer
import yaml

from carwatch.cost import month_to_date_cost_usd
from carwatch.curate import confirm_retirement, run_curate
from carwatch.daily_stats import aggregate_daily_stats
from carwatch.db import close_pool, get_open_pool, run_migrations
from carwatch.discovery import run_discovery
from carwatch.discovery_seed import build_google_news_sources, load_fixed_sources, seed_fixed_sources
from carwatch.ingest import run_ingest
from carwatch.llm.classify import run_classify
from carwatch.llm.extract import run_extract
from carwatch.logging_setup import configure_logging
from carwatch.models import load_brands_config, load_keywords_config
from carwatch.prefilter import run_prefilter
from carwatch.probe import run_probe
from carwatch.publishers.atom import write_atom_feed
from carwatch.publishers.telegram import get_pending_events, publish_pending_events
from carwatch.review import run_review
from carwatch.settings import CONFIG_DIR, MIGRATIONS_DIR, get_settings

app = typer.Typer()
db_app = typer.Typer()
app.add_typer(db_app, name="db")


def _logger():
    return configure_logging(get_settings().log_level)


async def _publish_and_write_feed(pool, settings, logger):
    """Send pending launch_events over Telegram, then (re)write the Atom feed.

    Shared by `publish` (non-dry-run path) and `weekly-run` -- both need the
    identical publish-then-write-feed sequence, and letting them drift would
    risk one route writing a stale feed after a publish.
    """
    stats = await publish_pending_events(pool, settings.telegram_bot_token, settings.telegram_chat_id, logger)
    await write_atom_feed(pool, Path(settings.atom_feed_path), settings.atom_feed_url)
    return stats


@db_app.command("migrate")
def db_migrate():
    async def _run():
        pool = await get_open_pool()
        applied = await run_migrations(pool, MIGRATIONS_DIR)
        await close_pool()
        return applied

    applied = asyncio.run(_run())
    typer.echo(f"Applied {len(applied)} migration(s): {applied}")


@app.command()
def probe(
    brands: Path = typer.Option(CONFIG_DIR / "brands.yaml", "--brands"),
    out: Path = typer.Option(Path("sources.csv"), "--out"),
    gaps: Path = typer.Option(Path("gaps.csv"), "--gaps"),
):
    async def _run():
        logger = _logger()
        pool = await get_open_pool()
        brands_config = load_brands_config(brands)
        stats = await run_probe(pool, brands_config, out, gaps, logger)
        await close_pool()
        return stats

    typer.echo(asyncio.run(_run()))


@app.command(name="seed-sources")
def seed_sources():
    """Seed `sources` with Tier 2/3 fixed feeds and Tier 4 Google News per-brand
    search feeds (Task 14), validating each candidate feed before insert.

    Wires up discovery_seed.load_fixed_sources / build_google_news_sources /
    seed_fixed_sources against config/settings.yaml and config/brands.yaml —
    these otherwise have no caller anywhere in the Fase 1 plan.
    """

    async def _run():
        logger = _logger()
        pool = await get_open_pool()
        settings_path = CONFIG_DIR / "settings.yaml"
        settings_data = yaml.safe_load(settings_path.read_text())
        extra_locales = settings_data.get("tier4_google_news", {}).get("extra_locales", {})
        brands_config = load_brands_config(CONFIG_DIR / "brands.yaml")

        fixed_sources = load_fixed_sources(settings_path)
        google_news_sources = build_google_news_sources(brands_config, extra_locales)
        stats = await seed_fixed_sources(pool, fixed_sources + google_news_sources, logger)
        await close_pool()
        return stats

    typer.echo(asyncio.run(_run()))


@app.command()
def ingest(once: bool = typer.Option(False, "--once")):
    async def _run():
        logger = _logger()
        pool = await get_open_pool()
        stats = await run_ingest(pool, logger)
        await close_pool()
        return stats

    typer.echo(asyncio.run(_run()))


@app.command()
def classify(limit: int = typer.Option(100, "--limit")):
    async def _run():
        logger = _logger()
        pool = await get_open_pool()
        brands_config = load_brands_config(CONFIG_DIR / "brands.yaml")
        keywords_config = load_keywords_config(CONFIG_DIR / "keywords.yaml")
        prefilter_stats = await run_prefilter(pool, brands_config, keywords_config, logger)
        classify_stats = await run_classify(pool, logger, limit=limit)
        await close_pool()
        return {"prefilter": prefilter_stats, "classify": classify_stats}

    typer.echo(asyncio.run(_run()))


@app.command()
def extract(limit: int = typer.Option(50, "--limit")):
    async def _run():
        logger = _logger()
        pool = await get_open_pool()
        settings = get_settings()
        stats = await run_extract(
            pool, logger, settings.telegram_bot_token, settings.telegram_chat_id, limit=limit
        )
        await close_pool()
        return stats

    typer.echo(asyncio.run(_run()))


@app.command()
def review(limit: int = typer.Option(15, "--limit")):
    async def _run():
        pool = await get_open_pool()
        counts = await run_review(pool, limit, input_fn=input, print_fn=typer.echo)
        await close_pool()
        return counts

    typer.echo(asyncio.run(_run()))


@app.command()
def publish(dry_run: bool = typer.Option(False, "--dry-run")):
    async def _run():
        logger = _logger()
        pool = await get_open_pool()
        if dry_run:
            events = await get_pending_events(pool)
            await close_pool()
            return {"would_send": len(events)}
        settings = get_settings()
        stats = await _publish_and_write_feed(pool, settings, logger)
        await close_pool()
        return stats

    typer.echo(asyncio.run(_run()))


@app.command()
def curate(confirm_retirement_id: int = typer.Option(None, "--confirm-retirement")):
    """Full source-curation pass (metrics + promote/demote/retire + digest), or,
    with --confirm-retirement <id>, apply a single previously-flagged
    retirement instead of running the full pass -- mirrors weekly-run's
    isolated-stage pattern (own get_open_pool()/close_pool() lifecycle) so it
    can also be invoked standalone between weekly-run cycles.
    """

    async def _run():
        pool = await get_open_pool()
        if confirm_retirement_id is not None:
            confirmed = await confirm_retirement(pool, confirm_retirement_id)
            await close_pool()
            if not confirmed:
                return {"confirmed_retirement": None, "reason": "not flagged for retirement"}
            return {"confirmed_retirement": confirm_retirement_id}
        logger = _logger()
        settings = get_settings()
        result = await run_curate(pool, settings.telegram_bot_token, settings.telegram_chat_id, logger)
        await close_pool()
        return result

    result = asyncio.run(_run())
    typer.echo(result)
    if confirm_retirement_id is not None and result.get("confirmed_retirement") is None:
        raise typer.Exit(code=1)


@app.command()
def discover():
    """Standalone continuous source-discovery pass (scoop + outbound-link
    candidates), also run as a weekly-run stage.
    """

    async def _run():
        logger = _logger()
        pool = await get_open_pool()
        stats = await run_discovery(pool, logger)
        await close_pool()
        return stats

    typer.echo(asyncio.run(_run()))


@app.command()
def stats():
    async def _run():
        pool = await get_open_pool()
        async with pool.connection() as conn:
            result = await conn.execute("SELECT status, count(*) FROM sources GROUP BY status")
            sources_by_status = dict(await result.fetchall())
            result = await conn.execute("SELECT status, count(*) FROM raw_items GROUP BY status")
            items_by_status = dict(await result.fetchall())
            result = await conn.execute(
                "SELECT day, items_ingested, events_created, llm_cost_usd "
                "FROM daily_stats ORDER BY day DESC LIMIT 7"
            )
            recent_days = await result.fetchall()
        month_cost = await month_to_date_cost_usd(pool)
        await close_pool()
        return {
            "sources": sources_by_status,
            "raw_items": items_by_status,
            "recent_days": recent_days,
            "month_to_date_cost_usd": month_cost,
        }

    typer.echo(asyncio.run(_run()))


@app.command(name="weekly-run")
def weekly_run():
    """Single composite pass: ingest -> prefilter -> classify -> extract ->
    publish -> curate -> discover -> daily_stats.

    DESIGN.md §1: replaces SPEC.md's APScheduler daemon (`carwatch run`) with one
    synchronous run per systemd timer trigger. dedupe.py has no separate CLI
    entrypoint -- it's invoked per item inside run_extract (SPEC.md §3
    architecture diagram: extract -> dedupe -> launch_events). Each pipeline
    stage is isolated in its own try/except: one stage crashing must not skip
    the stages after it (in particular, publish must still get a chance to
    send launch_events left over from a prior week) and must not skip
    close_pool() (a pool leaked on every unhandled exception would never be
    reclaimed for the life of the process). Exits non-zero when publish
    itself failed to run to completion (`failed_stages` -- this must hold
    regardless of the zeroed publish stats a crash leaves behind) or when it
    ran but sent fewer events than were pending -- a quiet week with zero
    pending events, or a week where every pending event sent, is not a
    failure. The other stages (ingest/prefilter/classify/extract) failing
    alone is tolerated: nothing is lost, there's a next run. Fase 3 adds
    curate (source metrics + promote/demote/retirement-flagging + digest),
    discover (continuous source discovery), and daily_stats (aggregation)
    after publish, at the same tolerance level -- none of the three failing
    alone forces a non-zero exit; only publish's own success/failure decides
    that, unchanged from Fase 1/2.
    """

    async def _run():
        logger = _logger()
        pool = await get_open_pool()
        failed_stages: list[str] = []
        ingest_stats = {"sources_checked": 0, "sources_failed": 0, "items_new": 0, "ms": 0}
        prefilter_stats = {"in": 0, "out": 0, "pass_rate": 0.0}
        classify_stats = {"in": 0, "approved": 0, "rejected": 0, "parse_errors": 0}
        extract_stats = {"in": 0, "extracted": 0, "error": 0}
        publish_stats = {"pending": 0, "sent": 0}
        curate_stats = {
            "transitions": {"promoted": [], "demoted": [], "retirement_candidates": []},
            "stale_brands": [],
            "digest_sent": False,
        }
        discover_stats = {
            "scoop_candidates": {"attempted": 0, "registered": 0},
            "outbound_candidates": {"attempted": 0, "registered": 0},
            "total_registered": 0,
        }
        daily_stats = {
            "items_ingested": 0, "items_approved": 0, "items_extracted": 0,
            "events_created": 0, "events_published": 0, "llm_calls": 0,
            "llm_tokens_in": 0, "llm_tokens_out": 0, "llm_cost_usd": 0.0,
            "sources_active": 0, "sources_blocked": 0,
        }

        try:
            settings = get_settings()
            brands_config = load_brands_config(CONFIG_DIR / "brands.yaml")
            keywords_config = load_keywords_config(CONFIG_DIR / "keywords.yaml")

            await run_migrations(pool, MIGRATIONS_DIR)

            try:
                ingest_stats = await run_ingest(pool, logger)
            except Exception as exc:
                failed_stages.append("ingest")
                logger.error("weekly_run.stage_failed", stage="ingest", error=f"{type(exc).__name__}: {exc}")

            try:
                prefilter_stats = await run_prefilter(pool, brands_config, keywords_config, logger)
            except Exception as exc:
                failed_stages.append("prefilter")
                logger.error("weekly_run.stage_failed", stage="prefilter", error=f"{type(exc).__name__}: {exc}")

            try:
                classify_stats = await run_classify(pool, logger, limit=200)
            except Exception as exc:
                failed_stages.append("classify")
                logger.error("weekly_run.stage_failed", stage="classify", error=f"{type(exc).__name__}: {exc}")

            try:
                extract_stats = await run_extract(
                    pool, logger, settings.telegram_bot_token, settings.telegram_chat_id, limit=200
                )
            except Exception as exc:
                failed_stages.append("extract")
                logger.error("weekly_run.stage_failed", stage="extract", error=f"{type(exc).__name__}: {exc}")

            try:
                publish_stats = await _publish_and_write_feed(pool, settings, logger)
            except Exception as exc:
                failed_stages.append("publish")
                logger.error("weekly_run.stage_failed", stage="publish", error=f"{type(exc).__name__}: {exc}")

            try:
                curate_stats = await run_curate(
                    pool, settings.telegram_bot_token, settings.telegram_chat_id, logger
                )
            except Exception as exc:
                failed_stages.append("curate")
                logger.error("weekly_run.stage_failed", stage="curate", error=f"{type(exc).__name__}: {exc}")

            try:
                discover_stats = await run_discovery(pool, logger)
            except Exception as exc:
                failed_stages.append("discover")
                logger.error("weekly_run.stage_failed", stage="discover", error=f"{type(exc).__name__}: {exc}")

            try:
                daily_stats = await aggregate_daily_stats(pool)
            except Exception as exc:
                failed_stages.append("daily_stats")
                logger.error("weekly_run.stage_failed", stage="daily_stats", error=f"{type(exc).__name__}: {exc}")
        finally:
            await close_pool()

        return {
            "ingest": ingest_stats,
            "prefilter": prefilter_stats,
            "classify": classify_stats,
            "extract": extract_stats,
            "publish": publish_stats,
            "curate": curate_stats,
            "discover": discover_stats,
            "daily_stats": daily_stats,
            "failed_stages": failed_stages,
        }

    result = asyncio.run(_run())
    typer.echo(result)
    publish_crashed = "publish" in result["failed_stages"]
    if publish_crashed or result["publish"]["sent"] < result["publish"]["pending"]:
        raise typer.Exit(code=1)
