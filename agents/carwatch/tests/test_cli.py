"""tests/test_cli.py"""
import importlib
import os
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx
import psycopg
import respx
from typer.testing import CliRunner

from carwatch import cli as cli_module
from carwatch import db as db_module
from carwatch.cli import app

runner = CliRunner()

PROJECT_ROOT = Path(__file__).resolve().parents[1]  # agents/carwatch/

# Mirrors tests/conftest.py's TEST_DB_URL / tests/test_e2e_fase1.py's pattern:
# `publish` runs its own asyncio.run() internally, so a sync test can't reuse
# the `db_pool` fixture's AsyncConnectionPool (opened on pytest-asyncio's own
# event loop) for setup/assertion queries -- it talks to the same physical
# test database directly via a plain synchronous psycopg connection instead.
TEST_DB_URL = os.environ.get(
    "DATABASE_URL_TEST", "postgresql://carwatch:carwatch@localhost:5433/carwatch_test"
)


def _execute(sql: str, params: tuple = ()) -> None:
    with psycopg.connect(TEST_DB_URL) as conn:
        conn.execute(sql, params)


def _fetchall(sql: str, params: tuple = ()) -> list:
    with psycopg.connect(TEST_DB_URL) as conn:
        return conn.execute(sql, params).fetchall()


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


def test_help_lists_fase2_commands():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for command in ("extract", "review"):
        assert command in result.output


def test_publish_dry_run_counts_pending_events_without_sending(db_pool):
    result = runner.invoke(app, ["publish", "--dry-run"])
    assert result.exit_code == 0
    assert "would_send" in result.output


@respx.mock
def test_publish_sends_pending_event_and_writes_atom_feed(db_pool, monkeypatch, tmp_path):
    """Direct, isolated coverage of `publish`'s non-dry-run path (previously
    only exercised indirectly, mixed in with ingest/classify/extract, by
    test_e2e_fase1.py's weekly-run end-to-end test). Also exercises the
    _publish_and_write_feed helper shared with weekly-run.
    """
    monkeypatch.setenv("ATOM_FEED_PATH", str(tmp_path / "feed.atom"))
    # env default from conftest.py's session-scoped _cli_test_env fixture.
    respx.post("https://api.telegram.org/bottest-bot-token/sendMessage").mock(
        return_value=httpx.Response(200, json={"ok": True})
    )

    _execute(
        "INSERT INTO launch_events (dedupe_key, brand, model, model_slug, stage, "
        "highlights, confidence, published) VALUES "
        "('k1', 'BYD', 'Seal 06', 'seal-06', 'world_premiere', ARRAY['h'], 0.9, FALSE)"
    )

    cli_result = runner.invoke(app, ["publish"])

    assert cli_result.exit_code == 0, cli_result.output
    assert "'sent': 1" in cli_result.output

    rows = _fetchall("SELECT published FROM launch_events WHERE dedupe_key = 'k1'")
    assert rows == [(True,)]

    atom_path = tmp_path / "feed.atom"
    assert atom_path.is_file()
    assert "Seal 06" in atom_path.read_text()


def _insert_pending_event(dedupe_key: str, model: str, model_slug: str) -> None:
    _execute(
        "INSERT INTO launch_events (dedupe_key, brand, model, model_slug, stage, "
        "highlights, confidence, published) VALUES "
        "(%s, 'BYD', %s, %s, 'world_premiere', ARRAY['h'], 0.9, FALSE)",
        (dedupe_key, model, model_slug),
    )


def test_weekly_run_exits_nonzero_on_partial_telegram_send_failure(db_pool, monkeypatch, tmp_path):
    """Fix 1: `publish_pending_events` can report `sent < pending` (some but
    not all pending events sent) without `sent == 0`. The old check
    (`result["publish"]["pending"] > 0 and result["publish"]["sent"] == 0`)
    only failed when EVERY pending event failed to send -- a run where 1 of
    2 events silently failed to notify still exited 0. `send_telegram_message`
    is patched directly (rather than routed through respx) so the two calls
    can be given different outcomes deterministically.
    """
    monkeypatch.setenv("ATOM_FEED_PATH", str(tmp_path / "feed.atom"))
    _insert_pending_event("k1", "Seal 06", "seal-06")
    _insert_pending_event("k2", "Seal 07", "seal-07")

    with patch(
        "carwatch.publishers.telegram.send_telegram_message",
        new=AsyncMock(side_effect=[True, False]),
    ):
        result = runner.invoke(app, ["weekly-run"])

    assert result.exit_code == 1, result.output
    assert "'pending': 2" in result.output
    assert "'sent': 1" in result.output


def test_weekly_run_exits_zero_when_all_pending_events_send(db_pool, monkeypatch, tmp_path):
    """Companion to the partial-failure test above: `sent < pending` must
    stay False (exit 0) when every pending event sends, confirming Fix 1
    didn't flip the check into always failing.
    """
    monkeypatch.setenv("ATOM_FEED_PATH", str(tmp_path / "feed.atom"))
    _insert_pending_event("k1", "Seal 06", "seal-06")

    with patch(
        "carwatch.publishers.telegram.send_telegram_message",
        new=AsyncMock(return_value=True),
    ):
        result = runner.invoke(app, ["weekly-run"])

    assert result.exit_code == 0, result.output
    assert "'pending': 1" in result.output
    assert "'sent': 1" in result.output


def test_weekly_run_tolerates_a_single_upstream_stage_failure(db_pool, monkeypatch, tmp_path):
    """Fix 2 (a): ingest/prefilter+classify/extract failing alone must not
    crash weekly-run, and must not by itself force a non-zero exit -- their
    work simply doesn't happen this run (nothing pending, so publish itself
    still reports a clean 0/0 and the run exits 0).
    """
    monkeypatch.setenv("ATOM_FEED_PATH", str(tmp_path / "feed.atom"))

    with patch("carwatch.cli.run_ingest", new=AsyncMock(side_effect=RuntimeError("ingest boom"))):
        result = runner.invoke(app, ["weekly-run"])

    assert result.exit_code == 0, result.output
    assert "'ingest'" in result.output
    assert "'sources_checked': 0" in result.output


def test_weekly_run_exits_nonzero_when_publish_stage_itself_raises(db_pool, monkeypatch, tmp_path):
    """Fix 2 (b): if `_publish_and_write_feed` raises outright (as opposed to
    completing and merely reporting nothing sent), weekly-run must exit
    non-zero even though the zeroed publish stats fallback
    (`{"pending": 0, "sent": 0}`) would otherwise read as "nothing pending"
    (0 < 0 is False) and be mistaken for a clean, quiet week.
    """
    monkeypatch.setenv("ATOM_FEED_PATH", str(tmp_path / "feed.atom"))

    with patch(
        "carwatch.cli._publish_and_write_feed",
        new=AsyncMock(side_effect=RuntimeError("telegram is down")),
    ):
        result = runner.invoke(app, ["weekly-run"])

    assert result.exit_code == 1, result.output
    assert "'pending': 0" in result.output
    assert "'sent': 0" in result.output


def test_weekly_run_closes_pool_even_when_a_stage_raises(db_pool, monkeypatch, tmp_path):
    """Fix 2 (c): close_pool() must run in a `finally`, regardless of which
    stage raised, so the module-level pool is never leaked across the life
    of the process.
    """
    monkeypatch.setenv("ATOM_FEED_PATH", str(tmp_path / "feed.atom"))

    with patch("carwatch.cli.run_extract", new=AsyncMock(side_effect=RuntimeError("extract boom"))):
        runner.invoke(app, ["weekly-run"])

    assert db_module._pool is None
