"""src/carwatch/cli.py"""
import asyncio
import os
from pathlib import Path

import typer
import yaml

from carwatch.db import close_pool, get_open_pool, run_migrations
from carwatch.discovery_seed import build_google_news_sources, load_fixed_sources, seed_fixed_sources
from carwatch.ingest import run_ingest
from carwatch.llm.classify import run_classify
from carwatch.logging_setup import configure_logging
from carwatch.models import load_brands_config, load_keywords_config
from carwatch.prefilter import run_prefilter
from carwatch.probe import run_probe
from carwatch.publishers.telegram import get_approved_items_for_notification, run_publish_smoke
from carwatch.settings import get_settings

app = typer.Typer()
db_app = typer.Typer()
app.add_typer(db_app, name="db")

# `config/` and `migrations/` are DATA directories that live next to the
# package, not inside it, so they are not part of the installed wheel. Under
# an editable/source-tree checkout `parents[2]` is `agents/carwatch/` and the
# fallback works; under the Dockerfile's non-editable
# `uv pip install --system .` `__file__` resolves inside site-packages and
# `parents[2]` lands outside the project entirely (`db migrate` would then
# silently apply zero migrations and `weekly-run` would crash on a missing
# `config/brands.yaml`). CARWATCH_ROOT makes the deployment declare where
# those directories actually are — the Dockerfile sets it to its WORKDIR.
CARWATCH_ROOT = Path(os.environ.get("CARWATCH_ROOT", Path(__file__).resolve().parents[2]))
CONFIG_DIR = CARWATCH_ROOT / "config"
MIGRATIONS_DIR = CARWATCH_ROOT / "migrations"


def _logger():
    return configure_logging(get_settings().log_level)


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
def publish(dry_run: bool = typer.Option(False, "--dry-run")):
    async def _run():
        logger = _logger()
        pool = await get_open_pool()
        if dry_run:
            items = await get_approved_items_for_notification(pool)
            await close_pool()
            return {"would_send": len(items)}
        settings = get_settings()
        stats = await run_publish_smoke(pool, settings.telegram_bot_token, settings.telegram_chat_id, logger)
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
        await close_pool()
        return {"sources": sources_by_status, "raw_items": items_by_status}

    typer.echo(asyncio.run(_run()))


_EMPTY_INGEST_STATS = {"sources_checked": 0, "sources_failed": 0, "items_new": 0, "ms": 0}
_EMPTY_PREFILTER_STATS = {"in": 0, "out": 0, "pass_rate": 0.0}
_EMPTY_CLASSIFY_STATS = {"in": 0, "approved": 0, "rejected": 0, "parse_errors": 0}
_EMPTY_PUBLISH_STATS = {"sent": 0, "item_count": 0}


@app.command(name="weekly-run")
def weekly_run():
    """Single composite pass: ingest -> prefilter -> classify -> publish.

    DESIGN.md §1: replaces SPEC.md's APScheduler daemon (`carwatch run`) with one
    synchronous run per systemd timer trigger. Exits non-zero when there WERE
    items eligible for notification but none of them got sent, OR when the
    publish stage itself raised -- a quiet week with nothing to notify is not
    a failure, but publish crashing means "we may have had things to tell
    someone and didn't," which must never exit 0 even though its zeroed
    fallback stats (`{"sent": 0, "item_count": 0}`) look identical to a quiet
    week's. ingest/prefilter/classify failing alone is more tolerable (that
    stage's work just doesn't happen this run, and there's usually a next
    run), so only publish's own failure is treated as always-fatal.

    Each stage is isolated in its own try/except: a crash in one stage (e.g. a
    DB error inside run_classify that Fix 3's per-batch handling doesn't
    catch, or a bug in run_prefilter) must not prevent the OTHER stages from
    still attempting to run -- in particular, publish alone can still
    successfully notify about items approved in a prior week even if this
    week's classify pass melts down. close_pool() is wrapped in try/finally
    so the pool is always released, even when every stage above it raised.
    """

    async def _run():
        logger = _logger()
        pool = await get_open_pool()
        failed_stages: list[str] = []
        try:
            settings = get_settings()
            brands_config = load_brands_config(CONFIG_DIR / "brands.yaml")
            keywords_config = load_keywords_config(CONFIG_DIR / "keywords.yaml")

            await run_migrations(pool, MIGRATIONS_DIR)

            try:
                ingest_stats = await run_ingest(pool, logger)
            except Exception as exc:
                logger.error("weekly_run.stage_failed", stage="ingest", error=f"{type(exc).__name__}: {exc}")
                ingest_stats = dict(_EMPTY_INGEST_STATS)
                failed_stages.append("ingest")

            try:
                prefilter_stats = await run_prefilter(pool, brands_config, keywords_config, logger)
            except Exception as exc:
                logger.error("weekly_run.stage_failed", stage="prefilter", error=f"{type(exc).__name__}: {exc}")
                prefilter_stats = dict(_EMPTY_PREFILTER_STATS)
                failed_stages.append("prefilter")

            try:
                classify_stats = await run_classify(pool, logger, limit=200)
            except Exception as exc:
                logger.error("weekly_run.stage_failed", stage="classify", error=f"{type(exc).__name__}: {exc}")
                classify_stats = dict(_EMPTY_CLASSIFY_STATS)
                failed_stages.append("classify")

            try:
                publish_stats = await run_publish_smoke(
                    pool, settings.telegram_bot_token, settings.telegram_chat_id, logger
                )
            except Exception as exc:
                logger.error("weekly_run.stage_failed", stage="publish", error=f"{type(exc).__name__}: {exc}")
                publish_stats = dict(_EMPTY_PUBLISH_STATS)
                failed_stages.append("publish")

            return {
                "ingest": ingest_stats,
                "prefilter": prefilter_stats,
                "classify": classify_stats,
                "publish": publish_stats,
                "failed_stages": failed_stages,
            }
        finally:
            await close_pool()

    result = asyncio.run(_run())
    typer.echo(result)
    publish_had_unsent_items = result["publish"]["item_count"] > 0 and result["publish"]["sent"] == 0
    # A lone publish-stage crash zeroes publish_stats to the exact same
    # {"sent": 0, "item_count": 0} shape as a legitimate quiet week, so
    # publish_had_unsent_items alone can never catch it (item_count > 0 is
    # required, and a crash-before-counting-anything can't satisfy that).
    # Check whether publish specifically raised, independent of item_count,
    # so this failure mode is never silently reported as a clean exit 0.
    # This also subsumes the "every stage raised" total-meltdown case, since
    # that can only happen when publish is among the failed stages too.
    publish_stage_crashed = "publish" in result["failed_stages"]
    if publish_had_unsent_items or publish_stage_crashed:
        raise typer.Exit(code=1)
