"""tests/test_cli.py"""
import importlib
import os
from pathlib import Path

import httpx
import pytest
import respx
from typer.testing import CliRunner

from carwatch import cli as cli_module
from carwatch.cli import app

runner = CliRunner()

PROJECT_ROOT = Path(__file__).resolve().parents[1]  # agents/carwatch/


def _reload_cli():
    return importlib.reload(cli_module)


def test_config_and_migrations_resolve_from_carwatch_root(monkeypatch):
    """CRITICAL 1: PACKAGE_ROOT = Path(__file__).parents[2] only holds for a
    source-tree checkout. Under the Dockerfile's non-editable
    `uv pip install --system .`, __file__ lives in site-packages and that
    expression pointed outside the project — `db migrate` then silently
    applied ZERO migrations and `weekly-run` crashed on a missing
    config/brands.yaml. CARWATCH_ROOT is what the Dockerfile sets to /app.
    """
    monkeypatch.setenv("CARWATCH_ROOT", str(PROJECT_ROOT))
    try:
        reloaded = _reload_cli()
        assert reloaded.CARWATCH_ROOT == PROJECT_ROOT
        sql_files = list(reloaded.MIGRATIONS_DIR.glob("*.sql"))
        assert sql_files, f"no *.sql found under {reloaded.MIGRATIONS_DIR}"
        assert (reloaded.CONFIG_DIR / "brands.yaml").is_file()
        assert (reloaded.CONFIG_DIR / "keywords.yaml").is_file()
        assert (reloaded.CONFIG_DIR / "settings.yaml").is_file()
    finally:
        monkeypatch.delenv("CARWATCH_ROOT", raising=False)
        _reload_cli()


def test_carwatch_root_env_var_overrides_the_source_tree_fallback(monkeypatch, tmp_path):
    monkeypatch.setenv("CARWATCH_ROOT", str(tmp_path))
    try:
        reloaded = _reload_cli()
        assert reloaded.CONFIG_DIR == tmp_path / "config"
        assert reloaded.MIGRATIONS_DIR == tmp_path / "migrations"
    finally:
        monkeypatch.delenv("CARWATCH_ROOT", raising=False)
        _reload_cli()


def test_dockerfile_sets_carwatch_root_to_its_workdir():
    dockerfile = (PROJECT_ROOT / "Dockerfile").read_text()
    workdir = next(
        line.split(maxsplit=1)[1].strip()
        for line in dockerfile.splitlines()
        if line.startswith("WORKDIR ")
    )
    assert f"ENV CARWATCH_ROOT={workdir}" in dockerfile


def test_help_lists_all_fase1_commands():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for command in ("db", "probe", "seed-sources", "ingest", "classify", "publish", "stats", "weekly-run"):
        assert command in result.output


def test_db_migrate_applies_migrations(monkeypatch, db_pool):
    from carwatch.settings import get_settings

    get_settings.cache_clear()
    result = runner.invoke(app, ["db", "migrate"])

    assert result.exit_code == 0
    assert "migration" in result.output.lower()


def test_stats_reports_counts_by_status(db_pool):
    result = runner.invoke(app, ["stats"])
    assert result.exit_code == 0
    assert "sources" in result.output
    assert "raw_items" in result.output


@respx.mock
def test_weekly_run_survives_a_raising_stage_and_still_closes_the_pool(db_pool, monkeypatch):
    """CRITICAL: weekly_run had no exception handling around any pipeline
    stage, and close_pool() only ran on the happy path. An unhandled
    exception from any stage used to leak the connection pool (close_pool()
    skipped entirely) AND abort every later stage, even ones that don't
    depend on the failing one -- e.g. publish alone could otherwise still
    successfully notify about items approved in a prior week. Simulate
    run_ingest raising and confirm: the CLI still exits cleanly (no unhandled
    traceback), the LATER stages (prefilter onward) still ran, and the pool
    was closed."""
    respx.post("https://api.telegram.org/bottest-bot-token/sendMessage").mock(
        return_value=httpx.Response(200, json={"ok": True})
    )

    from carwatch import db as db_module

    async def raising_ingest(pool, logger):
        raise RuntimeError("simulated stage crash")

    real_run_prefilter = cli_module.run_prefilter
    prefilter_calls: list[bool] = []

    async def spying_prefilter(pool, brands, keywords, logger):
        prefilter_calls.append(True)
        return await real_run_prefilter(pool, brands, keywords, logger)

    monkeypatch.setattr(cli_module, "run_ingest", raising_ingest)
    monkeypatch.setattr(cli_module, "run_prefilter", spying_prefilter)

    result = runner.invoke(app, ["weekly-run"])

    assert result.exc_info is None or not isinstance(result.exc_info[1], RuntimeError), (
        "the stage exception must be caught inside weekly-run, not propagate to the CLI runner"
    )
    # Nothing was eligible to notify (empty DB) and not every stage failed,
    # so this is not a reportable failure.
    assert result.exit_code == 0, result.output
    assert prefilter_calls, "the stage after the failing one must still have run"
    assert db_module._pool is None, "close_pool() must run even when an earlier stage raised"


@pytest.mark.parametrize("stage_attr", ["run_ingest", "run_prefilter", "run_classify"])
@respx.mock
def test_weekly_run_exits_zero_when_ingest_prefilter_or_classify_fails_alone(db_pool, monkeypatch, stage_attr):
    """ingest/prefilter/classify failing alone is tolerable -- that stage's
    work just doesn't happen this run, no data is lost, and there's usually a
    next run -- so it must NOT force a non-zero exit on its own. Companion to
    the publish-crash test below, which asserts the opposite for the one
    stage whose failure IS always fatal."""
    respx.post("https://api.telegram.org/bottest-bot-token/sendMessage").mock(
        return_value=httpx.Response(200, json={"ok": True})
    )

    async def raising_stage(*args, **kwargs):
        raise RuntimeError(f"simulated {stage_attr} crash")

    monkeypatch.setattr(cli_module, stage_attr, raising_stage)

    result = runner.invoke(app, ["weekly-run"])

    assert result.exit_code == 0, result.output


@respx.mock
def test_weekly_run_exits_nonzero_when_publish_stage_crashes_alone(db_pool, monkeypatch):
    """Post-review Finding 1: a lone run_publish_smoke crash zeroes
    publish_stats to the exact same {"sent": 0, "item_count": 0} shape as a
    legitimate quiet week, so the item_count>0 check can never catch it, and
    the total-meltdown check requires all 4 stages to fail. Pre-Fix4 this
    crash propagated loudly (non-zero exit, traceback); after stage isolation
    it must still fail the run rather than going silent, since publish
    crashing means "we may have had things to tell someone and didn't"."""
    from carwatch import db as db_module

    async def raising_publish(*args, **kwargs):
        raise RuntimeError("simulated publish crash")

    monkeypatch.setattr(cli_module, "run_publish_smoke", raising_publish)

    result = runner.invoke(app, ["weekly-run"])

    assert result.exc_info is None or not isinstance(result.exc_info[1], RuntimeError), (
        "the stage exception must be caught inside weekly-run, not propagate to the CLI runner"
    )
    assert result.exit_code == 1, result.output
    assert db_module._pool is None, "close_pool() must still run even though the run exits non-zero"


@respx.mock
def test_seed_sources_wires_fixed_and_google_news_sources_into_db(db_pool):
    """Task 14's seed_fixed_sources/build_google_news_sources/load_fixed_sources
    otherwise have no caller anywhere in the plan; this exercises the `seed-sources`
    CLI command that wires them together against config/brands.yaml and
    config/settings.yaml (real config files, real fixed + Google News feed URLs).

    Every outbound feed/robots.txt call is mocked to fail closed (404), so the
    command should run to completion, validate nothing, and insert nothing —
    verifying the wiring without depending on network access or exact source
    counts baked into the fixture config files.
    """
    respx.get(url__regex=r".*").mock(return_value=httpx.Response(404))

    result = runner.invoke(app, ["seed-sources"])

    assert result.exit_code == 0
    assert "attempted" in result.output
    assert "seeded" in result.output
