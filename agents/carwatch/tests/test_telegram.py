"""tests/test_telegram.py"""
import json

import httpx
import respx

from carwatch.publishers.telegram import (
    format_smoke_summary,
    get_approved_items_for_notification,
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
