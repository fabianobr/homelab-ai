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


@app.command(name="weekly-run")
def weekly_run():
    """Single composite pass: ingest -> prefilter -> classify -> publish.

    DESIGN.md §1: replaces SPEC.md's APScheduler daemon (`carwatch run`) with one
    synchronous run per systemd timer trigger. Exits non-zero if the Telegram send
    failed, so systemd doesn't mask a broken run.
    """

    async def _run():
        logger = _logger()
        pool = await get_open_pool()
        settings = get_settings()
        brands_config = load_brands_config(CONFIG_DIR / "brands.yaml")
        keywords_config = load_keywords_config(CONFIG_DIR / "keywords.yaml")

        await run_migrations(pool, MIGRATIONS_DIR)
        ingest_stats = await run_ingest(pool, logger)
        prefilter_stats = await run_prefilter(pool, brands_config, keywords_config, logger)
        classify_stats = await run_classify(pool, logger, limit=200)
        publish_stats = await run_publish_smoke(
            pool, settings.telegram_bot_token, settings.telegram_chat_id, logger
        )
        await close_pool()
        return {
            "ingest": ingest_stats,
            "prefilter": prefilter_stats,
            "classify": classify_stats,
            "publish": publish_stats,
        }

    result = asyncio.run(_run())
    typer.echo(result)
    if not result["publish"]["sent"]:
        raise typer.Exit(code=1)
