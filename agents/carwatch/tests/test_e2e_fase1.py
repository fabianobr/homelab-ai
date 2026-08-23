"""tests/test_e2e_fase1.py"""
import json
import os
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import httpx
import psycopg
import respx
from typer.testing import CliRunner

from carwatch.cli import app

runner = CliRunner()

# Mirrors tests/conftest.py's TEST_DB_URL. Every CLI invocation under test
# manages its own asyncio event loop internally (cli.py's commands each call
# asyncio.run()), so this test must be a plain sync `def` (matching the
# existing CliRunner-based tests in tests/test_cli.py) rather than `async
# def` -- nesting a second asyncio.run() inside a running event loop raises
# RuntimeError. That in turn means this test can't reuse the `db_pool`
# fixture's AsyncConnectionPool for its own setup/assertion queries (that
# pool is opened inside pytest-asyncio's fixture event loop, not this test's
# synchronous body), so it talks to the same physical test database directly
# via a plain synchronous psycopg connection instead. The `db_pool` fixture
# is still requested purely for its migration + truncate-on-teardown side
# effects, keeping this test isolated from others.
TEST_DB_URL = os.environ.get(
    "DATABASE_URL_TEST", "postgresql://carwatch:carwatch@localhost:5433/carwatch_test"
)


def _execute(sql: str, params: tuple = ()) -> None:
    with psycopg.connect(TEST_DB_URL) as conn:
        conn.execute(sql, params)


def _fetchall(sql: str, params: tuple = ()) -> list:
    with psycopg.connect(TEST_DB_URL) as conn:
        return conn.execute(sql, params).fetchall()


def _feed(items: list[tuple[str, str, int]]) -> str:
    now = datetime.now(timezone.utc)
    entries = "".join(
        f"<item><title>{title}</title><link>{link}</link>"
        f"<pubDate>{(now - timedelta(days=days_ago)).strftime('%a, %d %b %Y %H:%M:%S +0000')}</pubDate></item>"
        for title, link, days_ago in items
    )
    # carwatch.fetcher._is_blocked() treats any 200 response body under 500
    # chars as a silent-block false positive (Task 7's heuristic -- see the
    # same "x" * 500 padding trick in tests/test_fetcher.py and
    # tests/test_ingest.py's _rss() helper). A bare 2-item RSS body is only
    # ~380 chars, so pad with an XML comment feedparser ignores rather than
    # shrink the scenario to a single item.
    padding = "<!-- " + ("padding " * 30) + " -->"
    return f"<?xml version='1.0'?><rss version='2.0'><channel>{entries}{padding}</channel></rss>"


@respx.mock
def test_weekly_run_end_to_end_ingests_classifies_and_publishes(db_pool):
    respx.get("https://press.example.com/robots.txt").mock(
        return_value=httpx.Response(200, text="User-agent: *\nAllow: /\n")
    )
    body = _feed(
        [
            ("BYD unveils Seal 06 world premiere", "https://press.example.com/byd-seal-06", 1),
            ("Random unrelated corporate news", "https://press.example.com/boring", 1),
        ]
    )
    feed_route = respx.get("https://press.example.com/feed.xml").mock(
        return_value=httpx.Response(200, text=body, headers={"ETag": '"v1"'})
    )
    # No sendMessage route registered here on purpose: `publish` now reads
    # pending events from `launch_events` (Task 6), and `weekly-run` doesn't
    # yet run the `extract` step that populates it from a classified raw_item
    # (that pipeline wiring is Fase 2 Task 9) -- so this run always has zero
    # pending events and never calls Telegram. A registered-but-unused respx
    # route would fail this test on teardown (assert_all_called).

    _execute(
        "INSERT INTO sources (domain, feed_url, kind, tier, status, brand_scope) "
        "VALUES ('press.example.com', 'https://press.example.com/feed.xml', 'rss', 1, 'active', %s)",
        (["BYD"],),
    )

    async def fake_classify(system_prompt, user_content):
        payload = json.loads(user_content)
        results = []
        for item in payload:
            is_byd = "BYD" in item["title"]
            results.append(
                {
                    "i": item["i"],
                    "is_launch": is_byd,
                    "stage": "world_premiere" if is_byd else None,
                    "brand": "BYD" if is_byd else None,
                    "model": "Seal 06" if is_byd else None,
                    "confidence": 0.92 if is_byd else 0.05,
                }
            )
        # call_classify returns (text, usage) since the Fase 1 final review
        # (SPEC.md §18's llm.call event needs tokens_in/tokens_out).
        return json.dumps(results), {
            "tokens_in": 120,
            "tokens_out": 80,
            "stop_reason": "end_turn",
        }

    with patch("carwatch.llm.classify.call_classify", new=AsyncMock(side_effect=fake_classify)):
        result = runner.invoke(app, ["weekly-run"])

    assert result.exit_code == 0, result.output

    rows = _fetchall("SELECT title, status, classified FROM raw_items ORDER BY id")
    statuses = {title: status for title, status, _ in rows}
    classified = {title: data for title, _, data in rows}
    # Approved by classify and left 'new' -- raw_items.status no longer tracks
    # notification state (Fase 1's 'notified' status/mark_notified was removed
    # in Fase 2 Task 6, replaced by launch_events.published; see this task's
    # report for the full removal). Nothing currently promotes this item past
    # 'new' because `extract` (which reads classified 'new' items and creates
    # the launch_events row publish.py acts on) isn't wired into `weekly-run`
    # yet -- that's Fase 2 Task 9.
    assert statuses["BYD unveils Seal 06 world premiere"] == "new"
    assert classified["BYD unveils Seal 06 world premiere"]["brand"] == "BYD"
    assert statuses["Random unrelated corporate news"] == "filtered"  # no positive keyword term

    # No launch_events exist yet (extract isn't wired in), so publish has
    # nothing pending and never calls Telegram.
    telegram_calls = [c for c in respx.calls if "sendMessage" in str(c.request.url)]
    assert len(telegram_calls) == 0

    # Second run: same feed, unchanged -> conditional GET must short-circuit via 304.
    feed_route.side_effect = None
    respx.get("https://press.example.com/feed.xml").mock(return_value=httpx.Response(304))

    with patch("carwatch.llm.classify.call_classify", new=AsyncMock(side_effect=fake_classify)):
        second_result = runner.invoke(app, ["weekly-run"])

    assert second_result.exit_code == 0, second_result.output
    count = _fetchall("SELECT count(*) FROM raw_items")[0][0]
    assert count == 2  # no duplicates inserted on the second run
