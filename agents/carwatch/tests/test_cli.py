"""tests/test_cli.py"""
import os

import httpx
import respx
from typer.testing import CliRunner

from carwatch.cli import app

runner = CliRunner()


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
