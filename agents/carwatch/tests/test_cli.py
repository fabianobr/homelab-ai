"""tests/test_cli.py"""
import importlib
import os
from pathlib import Path

import httpx
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
