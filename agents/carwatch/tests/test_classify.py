"""tests/test_classify.py"""
import json
from unittest.mock import AsyncMock, patch

from carwatch.llm.classify import parse_classify_response, run_classify
from carwatch.models import LaunchStage


def test_parse_classify_response_accepts_well_formed_array():
    raw = json.dumps(
        [
            {"i": 0, "is_launch": True, "stage": "world_premiere", "brand": "BYD", "model": "Seal 06", "confidence": 0.92},
            {"i": 1, "is_launch": False, "stage": None, "brand": None, "model": None, "confidence": 0.1},
        ]
    )
    items = parse_classify_response(raw, batch_size=2)

    assert items is not None
    assert items[0].stage is LaunchStage.world_premiere
    assert items[1].is_launch is False


def test_parse_classify_response_strips_markdown_fences():
    raw = "```json\n" + json.dumps([{"i": 0, "is_launch": False, "stage": None, "brand": None, "model": None, "confidence": 0.0}]) + "\n```"
    items = parse_classify_response(raw, batch_size=1)
    assert items is not None
    assert len(items) == 1


def test_parse_classify_response_rejects_wrong_length():
    raw = json.dumps([{"i": 0, "is_launch": False, "stage": None, "brand": None, "model": None, "confidence": 0.0}])
    assert parse_classify_response(raw, batch_size=2) is None


def test_parse_classify_response_rejects_invalid_json():
    assert parse_classify_response("not json at all", batch_size=1) is None


async def test_run_classify_marks_low_confidence_as_rejected(db_pool):
    async with db_pool.connection() as conn:
        source = await conn.execute(
            "INSERT INTO sources (domain, feed_url, kind, tier, status) "
            "VALUES ('example.com', 'https://example.com/feed', 'rss', 1, 'active') RETURNING id"
        )
        source_id = (await source.fetchone())[0]
        await conn.execute(
            "INSERT INTO raw_items (source_id, url, url_hash, title, status, prefilter_ok) "
            "VALUES (%s, 'https://example.com/a', 'hash-a', 'BYD Seal 06 world premiere', 'new', TRUE)",
            (source_id,),
        )

    fake_response = json.dumps(
        [{"i": 0, "is_launch": True, "stage": "world_premiere", "brand": "BYD", "model": "Seal 06", "confidence": 0.4}]
    )
    with patch("carwatch.llm.classify.call_classify", new=AsyncMock(return_value=fake_response)):
        stats = await run_classify(db_pool, logger=None, limit=100)

    assert stats == {"in": 1, "approved": 0, "rejected": 1, "parse_errors": 0}
    async with db_pool.connection() as conn:
        result = await conn.execute("SELECT status, classified FROM raw_items")
        row = await result.fetchone()
    assert row[0] == "rejected"
    assert row[1]["confidence"] == 0.4


async def test_run_classify_keeps_approved_items_as_new_with_classified_payload(db_pool):
    async with db_pool.connection() as conn:
        source = await conn.execute(
            "INSERT INTO sources (domain, feed_url, kind, tier, status) "
            "VALUES ('example.com', 'https://example.com/feed', 'rss', 1, 'active') RETURNING id"
        )
        source_id = (await source.fetchone())[0]
        await conn.execute(
            "INSERT INTO raw_items (source_id, url, url_hash, title, status, prefilter_ok) "
            "VALUES (%s, 'https://example.com/a', 'hash-a', 'BYD Seal 06 world premiere', 'new', TRUE)",
            (source_id,),
        )

    fake_response = json.dumps(
        [{"i": 0, "is_launch": True, "stage": "world_premiere", "brand": "BYD", "model": "Seal 06", "confidence": 0.92}]
    )
    with patch("carwatch.llm.classify.call_classify", new=AsyncMock(return_value=fake_response)):
        stats = await run_classify(db_pool, logger=None, limit=100)

    assert stats["approved"] == 1
    async with db_pool.connection() as conn:
        result = await conn.execute("SELECT status FROM raw_items")
        row = await result.fetchone()
    assert row[0] == "new"
