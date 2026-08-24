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

    # "sent" is the int count of items actually marked notified, not a bool
    # of "did the API call succeed" (True == 1 made the old literal pass by
    # coincidence).
    assert stats == {"sent": 1, "item_count": 1}


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
    # "sent" is the int count of items marked notified (True == 1 made the
    # old literal pass by coincidence, not because it was re-verified
    # against the new int contract).
    assert stats == {"sent": 1, "item_count": 1}

    async with db_pool.connection() as conn:
        result = await conn.execute("SELECT status FROM raw_items WHERE id = %s", (item_id,))
        (status,) = await result.fetchone()
    assert status == "notified"

    # A second run must not re-select or re-send the now-notified item. This
    # is the zero-eligible-items ("quiet week") case, which sends the
    # heartbeat text successfully but has zero items to mark notified --
    # "sent" now counts items marked notified (not "did the API call
    # succeed"), so this must be 0 rather than the old True.
    second_stats = await run_publish_smoke(db_pool, "token123", "chat1", logger=None)
    assert second_stats == {"sent": 0, "item_count": 0}


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
    # "sent" is the int count of items marked notified -- 0 here because the
    # send failed (False == 0 made the old literal pass by coincidence, not
    # because it was re-verified against the new int contract).
    assert stats == {"sent": 0, "item_count": 1}

    async with db_pool.connection() as conn:
        result = await conn.execute("SELECT status FROM raw_items WHERE id = %s", (item_id,))
        (status,) = await result.fetchone()
    assert status == "new"


async def _insert_bulky_approved_items(db_pool, count: int) -> list[int]:
    """Insert `count` approved-and-unnotified raw_items rows with a long
    enough `model` field that the combined single-message summary exceeds
    the chunk budget, forcing run_publish_smoke to split across multiple
    Telegram messages."""
    long_highlight = "x" * 400
    item_ids: list[int] = []
    async with db_pool.connection() as conn:
        source = await conn.execute(
            "INSERT INTO sources (domain, feed_url, kind, tier, status) "
            "VALUES ('example.com', 'https://example.com/feed', 'rss', 1, 'active') RETURNING id"
        )
        source_id = (await source.fetchone())[0]
        for n in range(count):
            classified = json.dumps(
                {
                    "i": 0,
                    "is_launch": True,
                    "stage": "world_premiere",
                    "brand": "BYD",
                    "model": f"Seal {n} {long_highlight}",
                    "confidence": 0.9,
                }
            )
            row = await conn.execute(
                "INSERT INTO raw_items (source_id, url, url_hash, title, status, classified) "
                "VALUES (%s, %s, %s, %s, 'new', %s) RETURNING id",
                (source_id, f"https://x/{n}", f"h{n}", f"Bulky item {n}", classified),
            )
            item_ids.append((await row.fetchone())[0])
    return item_ids


@respx.mock
async def test_run_publish_smoke_chunks_large_backlog_into_multiple_messages_and_marks_all_notified(db_pool):
    """CRITICAL: a single-message summary has no 4096-char chunking, so a
    large enough backlog (worsened by the classify.py re-billing bug, but
    possible even after that fix on the first run after an outage) made the
    ENTIRE send fail as one giant rejected message -- mark_notified never ran
    for ANY item, and they stayed 'new' forever. A large backlog must now be
    split across multiple Telegram messages, with every item across every
    chunk ending up notified when every chunk sends successfully."""
    respx.post("https://api.telegram.org/bottoken123/sendMessage").mock(
        return_value=httpx.Response(200, json={"ok": True})
    )
    item_ids = await _insert_bulky_approved_items(db_pool, 15)

    stats = await run_publish_smoke(db_pool, "token123", "chat1", logger=None)

    telegram_calls = [c for c in respx.calls if "sendMessage" in str(c.request.url)]
    assert len(telegram_calls) > 1, "expected the backlog to be split across more than one message"
    assert stats == {"sent": 15, "item_count": 15}

    async with db_pool.connection() as conn:
        result = await conn.execute(
            "SELECT count(*) FROM raw_items WHERE id = ANY(%s) AND status = 'notified'", (item_ids,)
        )
        assert (await result.fetchone())[0] == 15


@respx.mock
async def test_run_publish_smoke_marks_only_the_successfully_sent_chunk_when_one_chunk_fails(db_pool):
    """A failed chunk must not block a different, successfully-sent chunk's
    items from being marked notified -- the failed chunk's items must stay
    'new' (retried next week) while the other chunk's items become
    'notified'."""

    def _responder(request: httpx.Request) -> httpx.Response:
        # Fail exactly the first part; succeed every other part.
        if b"parte 1/" in request.content:
            return httpx.Response(500)
        return httpx.Response(200, json={"ok": True})

    respx.post("https://api.telegram.org/bottoken123/sendMessage").mock(side_effect=_responder)
    item_ids = await _insert_bulky_approved_items(db_pool, 15)

    stats = await run_publish_smoke(db_pool, "token123", "chat1", logger=None)

    telegram_calls = [c for c in respx.calls if "sendMessage" in str(c.request.url)]
    assert len(telegram_calls) > 1
    assert stats["item_count"] == 15
    # Not everything got notified (the failed chunk's items didn't)...
    assert 0 < stats["sent"] < 15

    async with db_pool.connection() as conn:
        result = await conn.execute(
            "SELECT status, count(*) FROM raw_items WHERE id = ANY(%s) GROUP BY status", (item_ids,)
        )
        counts = dict(await result.fetchall())
    # ...and exactly matches the DB: sent items are 'notified', the rest are
    # still 'new' (unaffected by the other chunk's failure) and will be
    # retried on the next weekly-run.
    assert counts.get("notified", 0) == stats["sent"]
    assert counts.get("new", 0) == 15 - stats["sent"]


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
