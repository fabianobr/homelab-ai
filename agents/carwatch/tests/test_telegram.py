"""tests/test_telegram.py"""
import json
from unittest.mock import MagicMock

import httpx
import respx

from carwatch.publishers.telegram import (
    format_smoke_summary,
    get_approved_items_for_notification,
    mark_notified,
    run_publish_smoke,
    send_telegram_message,
)


def test_format_smoke_summary_lists_each_approved_item():
    items = [
        {"title": "BYD reveals Seal 06", "url": "https://x/1", "brand": "BYD", "model": "Seal 06", "stage": "world_premiere", "confidence": 0.92},
    ]
    text = format_smoke_summary(items)
    assert "BYD" in text
    assert "Seal 06" in text
    assert "https://x/1" in text


def test_format_smoke_summary_handles_empty_list():
    text = format_smoke_summary([])
    assert "Nenhum" in text


@respx.mock
async def test_send_telegram_message_returns_true_on_success():
    respx.post("https://api.telegram.org/bottoken123/sendMessage").mock(
        return_value=httpx.Response(200, json={"ok": True})
    )
    ok = await send_telegram_message("token123", "chat1", "hello")
    assert ok is True


@respx.mock
async def test_send_telegram_message_returns_false_on_http_error():
    respx.post("https://api.telegram.org/bottoken123/sendMessage").mock(
        return_value=httpx.Response(500)
    )
    ok = await send_telegram_message("token123", "chat1", "hello")
    assert ok is False


async def test_get_approved_items_excludes_rejected_and_unclassified(db_pool):
    async with db_pool.connection() as conn:
        source = await conn.execute(
            "INSERT INTO sources (domain, feed_url, kind, tier, status) "
            "VALUES ('example.com', 'https://example.com/feed', 'rss', 1, 'active') RETURNING id"
        )
        source_id = (await source.fetchone())[0]
        approved = json.dumps({"i": 0, "is_launch": True, "stage": "world_premiere", "brand": "BYD", "model": "Seal 06", "confidence": 0.92})
        rejected = json.dumps({"i": 0, "is_launch": False, "stage": None, "brand": None, "model": None, "confidence": 0.1})
        await conn.execute(
            "INSERT INTO raw_items (source_id, url, url_hash, title, status, classified) VALUES "
            "(%s, 'https://x/1', 'h1', 'Approved item', 'new', %s), "
            "(%s, 'https://x/2', 'h2', 'Rejected item', 'rejected', %s), "
            "(%s, 'https://x/3', 'h3', 'Unclassified item', 'new', NULL)",
            (source_id, approved, source_id, rejected, source_id),
        )

    items = await get_approved_items_for_notification(db_pool)

    assert len(items) == 1
    assert items[0]["brand"] == "BYD"


@respx.mock
async def test_run_publish_smoke_sends_and_reports_count(db_pool):
    respx.post("https://api.telegram.org/bottoken123/sendMessage").mock(
        return_value=httpx.Response(200, json={"ok": True})
    )
    async with db_pool.connection() as conn:
        source = await conn.execute(
            "INSERT INTO sources (domain, feed_url, kind, tier, status) "
            "VALUES ('example.com', 'https://example.com/feed', 'rss', 1, 'active') RETURNING id"
        )
        source_id = (await source.fetchone())[0]
        approved = json.dumps({"i": 0, "is_launch": True, "stage": "world_premiere", "brand": "BYD", "model": "Seal 06", "confidence": 0.92})
        await conn.execute(
            "INSERT INTO raw_items (source_id, url, url_hash, title, status, classified) "
            "VALUES (%s, 'https://x/1', 'h1', 'Approved item', 'new', %s)",
            (source_id, approved),
        )

    stats = await run_publish_smoke(db_pool, "token123", "chat1", logger=None)

    assert stats == {"sent": True, "item_count": 1}


@respx.mock
async def test_run_publish_smoke_marks_items_notified_and_excludes_from_next_run(db_pool):
    respx.post("https://api.telegram.org/bottoken123/sendMessage").mock(
        return_value=httpx.Response(200, json={"ok": True})
    )
    async with db_pool.connection() as conn:
        source = await conn.execute(
            "INSERT INTO sources (domain, feed_url, kind, tier, status) "
            "VALUES ('example.com', 'https://example.com/feed', 'rss', 1, 'active') RETURNING id"
        )
        source_id = (await source.fetchone())[0]
        approved = json.dumps({"i": 0, "is_launch": True, "stage": "world_premiere", "brand": "BYD", "model": "Seal 06", "confidence": 0.92})
        row = await conn.execute(
            "INSERT INTO raw_items (source_id, url, url_hash, title, status, classified) "
            "VALUES (%s, 'https://x/1', 'h1', 'Approved item', 'new', %s) RETURNING id",
            (source_id, approved),
        )
        item_id = (await row.fetchone())[0]

    stats = await run_publish_smoke(db_pool, "token123", "chat1", logger=None)
    assert stats == {"sent": True, "item_count": 1}

    async with db_pool.connection() as conn:
        result = await conn.execute("SELECT status FROM raw_items WHERE id = %s", (item_id,))
        (status,) = await result.fetchone()
    assert status == "notified"

    # A second run must not re-select or re-send the now-notified item.
    second_stats = await run_publish_smoke(db_pool, "token123", "chat1", logger=None)
    assert second_stats == {"sent": True, "item_count": 0}


@respx.mock
async def test_run_publish_smoke_leaves_status_new_when_send_fails(db_pool):
    respx.post("https://api.telegram.org/bottoken123/sendMessage").mock(
        return_value=httpx.Response(500)
    )
    async with db_pool.connection() as conn:
        source = await conn.execute(
            "INSERT INTO sources (domain, feed_url, kind, tier, status) "
            "VALUES ('example.com', 'https://example.com/feed', 'rss', 1, 'active') RETURNING id"
        )
        source_id = (await source.fetchone())[0]
        approved = json.dumps({"i": 0, "is_launch": True, "stage": "world_premiere", "brand": "BYD", "model": "Seal 06", "confidence": 0.92})
        row = await conn.execute(
            "INSERT INTO raw_items (source_id, url, url_hash, title, status, classified) "
            "VALUES (%s, 'https://x/1', 'h1', 'Approved item', 'new', %s) RETURNING id",
            (source_id, approved),
        )
        item_id = (await row.fetchone())[0]

    stats = await run_publish_smoke(db_pool, "token123", "chat1", logger=None)
    assert stats == {"sent": False, "item_count": 1}

    async with db_pool.connection() as conn:
        result = await conn.execute("SELECT status FROM raw_items WHERE id = %s", (item_id,))
        (status,) = await result.fetchone()
    assert status == "new"


async def test_mark_notified_with_empty_list_is_a_noop(db_pool):
    # An empty item_ids list must short-circuit before ever touching the
    # database -- not merely produce a query that happens to match zero
    # rows. Spy on pool.connection (wrapping the real bound method so any
    # call that does slip through still works) and assert it's never
    # entered.
    spy = MagicMock(side_effect=db_pool.connection)
    db_pool.connection = spy

    await mark_notified(db_pool, [])

    spy.assert_not_called()
