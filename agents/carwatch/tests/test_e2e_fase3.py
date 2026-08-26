"""tests/test_e2e_fase3.py"""
import os
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx
import psycopg
import respx
from typer.testing import CliRunner

from carwatch.cli import app

runner = CliRunner()

TEST_DB_URL = os.environ.get(
    "DATABASE_URL_TEST", "postgresql://carwatch:carwatch@localhost:5433/carwatch_test"
)


def _execute(sql: str, params: tuple = ()) -> None:
    with psycopg.connect(TEST_DB_URL) as conn:
        conn.execute(sql, params)


def _fetchall(sql: str, params: tuple = ()) -> list:
    with psycopg.connect(TEST_DB_URL) as conn:
        return conn.execute(sql, params).fetchall()


@respx.mock
def test_weekly_run_completes_through_curate_discover_and_daily_stats(db_pool, monkeypatch, tmp_path):
    """Fase 3 end-to-end test: verify that weekly-run executes the full
    pipeline including curate, discover, and daily_stats stages, and that
    daily_stats writes a row to the database.

    This test:
    1. Mocks HTTP requests (robots.txt, RSS feed, Telegram)
    2. Inserts a test source into the database
    3. Mocks the LLM classify call (returns empty classification)
    4. Invokes `weekly-run`
    5. Verifies that daily_stats wrote a row to the database
    """
    monkeypatch.setenv("ATOM_FEED_PATH", str(tmp_path / "feed.atom"))

    # Mock HTTP requests
    respx.get("https://x.com/robots.txt").mock(
        return_value=httpx.Response(200, text="User-agent: *\nAllow: /\n")
    )
    respx.get("https://x.com/feed.xml").mock(return_value=httpx.Response(200, text=(
        "<?xml version='1.0'?><rss><channel></channel></rss>"  # empty feed: no items this run
    )))
    respx.post("https://api.telegram.org/bottest-bot-token/sendMessage").mock(
        return_value=httpx.Response(200, json={"ok": True})
    )

    # Insert a test source
    _execute(
        "INSERT INTO sources (domain, feed_url, kind, tier, status) "
        "VALUES (%s, %s, %s, %s, %s)",
        ("x.com", "https://x.com/feed.xml", "rss", 1, "active")
    )

    # Mock the LLM classify call
    with patch("carwatch.llm.classify.call_classify", new=AsyncMock(return_value=("[]", {"tokens_in": 0, "tokens_out": 0}))):
        result = runner.invoke(app, ["weekly-run"])

    assert result.exit_code == 0, result.output

    # Verify that daily_stats wrote a row
    rows = _fetchall("SELECT count(*) FROM daily_stats")
    assert rows[0][0] == 1, "aggregate_daily_stats should have written exactly one row"
