"""tests/test_classify.py"""
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from carwatch.llm.classify import BATCH_SIZE, parse_classify_response, run_classify
from carwatch.models import LaunchStage

_USAGE = {"tokens_in": 100, "tokens_out": 60, "stop_reason": "end_turn"}
_TRUNCATED_USAGE = {"tokens_in": 100, "tokens_out": 1200, "stop_reason": "max_tokens"}


def _reply(payload: list[dict], usage: dict | None = None) -> tuple[str, dict]:
    """call_classify's (text, usage) contract."""
    return json.dumps(payload), usage or _USAGE


def _item(i: int, *, is_launch: bool = True, confidence: float = 0.92) -> dict:
    return {
        "i": i,
        "is_launch": is_launch,
        "stage": "world_premiere" if is_launch else None,
        "brand": "BYD" if is_launch else None,
        "model": f"Seal {i}" if is_launch else None,
        "confidence": confidence,
    }


async def _insert_items(db_pool, titles: list[str]) -> None:
    async with db_pool.connection() as conn:
        source = await conn.execute(
            "INSERT INTO sources (domain, feed_url, kind, tier, status) "
            "VALUES ('example.com', 'https://example.com/feed', 'rss', 1, 'active') RETURNING id"
        )
        source_id = (await source.fetchone())[0]
        for n, title in enumerate(titles):
            await conn.execute(
                "INSERT INTO raw_items (source_id, url, url_hash, title, status, prefilter_ok) "
                "VALUES (%s, %s, %s, %s, 'new', TRUE)",
                (source_id, f"https://example.com/{n}", f"hash-{n}", title),
            )


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

    fake_response = _reply([_item(0, confidence=0.4)])
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

    fake_response = _reply([_item(0)])
    with patch("carwatch.llm.classify.call_classify", new=AsyncMock(return_value=fake_response)):
        stats = await run_classify(db_pool, logger=None, limit=100)

    assert stats["approved"] == 1
    async with db_pool.connection() as conn:
        result = await conn.execute("SELECT status FROM raw_items")
        row = await result.fetchone()
    assert row[0] == "new"


async def _call_classify_against_fake_sdk() -> tuple[tuple[str, dict], dict]:
    """Drive the real call_classify against a fake SDK client, returning its
    result plus the kwargs it actually sent to messages.create()."""
    from carwatch.llm import client

    fake_response = SimpleNamespace(
        content=[SimpleNamespace(type="text", text='[{"i":0}]')],
        usage=SimpleNamespace(input_tokens=321, output_tokens=123),
        stop_reason="max_tokens",
    )
    create = AsyncMock(return_value=fake_response)
    fake_client = SimpleNamespace(messages=SimpleNamespace(create=create))
    with patch.object(client, "get_anthropic_client", return_value=fake_client):
        result = await client.call_classify("sys", "user")
    return result, create.await_args.kwargs


async def test_max_tokens_fits_a_full_batch():
    """Guards CRITICAL 3: BATCH_SIZE x ~40 output tokens must stay well under
    call_classify's max_tokens, or every full batch truncates, fails to parse,
    and is silently dropped + re-billed on the next weekly run. The old pair
    (BATCH_SIZE=20, max_tokens=300) failed this by a factor of ~2.5.
    """
    _result, kwargs = await _call_classify_against_fake_sdk()

    assert kwargs["max_tokens"] >= BATCH_SIZE * 40, (
        f"BATCH_SIZE={BATCH_SIZE} needs ~{BATCH_SIZE * 40} output tokens "
        f"but max_tokens={kwargs['max_tokens']}"
    )


async def test_call_classify_returns_text_and_token_usage():
    """CRITICAL 3 / IMPORTANT 7: the SDK response's usage + stop_reason must
    reach the caller so llm.call can log cost and truncation can be told apart
    from a malformed response."""
    (text, usage), _kwargs = await _call_classify_against_fake_sdk()

    assert text == '[{"i":0}]'
    assert usage == {"tokens_in": 321, "tokens_out": 123, "stop_reason": "max_tokens"}


async def test_unparseable_batch_is_split_in_half_and_both_halves_processed(db_pool):
    """CRITICAL 3: a truncated/malformed batch response used to discard the
    WHOLE batch (leaving the rows at status='new' AND prefilter_ok=TRUE, so
    the next weekly run re-attempted and re-billed them forever). It must now
    split and retry, so only a genuinely broken single item is lost."""
    await _insert_items(db_pool, ["BYD Seal 0 premiere", "BYD Seal 1 premiere",
                                  "BYD Seal 2 premiere", "BYD Seal 3 premiere"])

    calls: list[int] = []

    async def fake_call(system_prompt, user_content):
        batch = json.loads(user_content)
        calls.append(len(batch))
        if len(batch) == 4:
            # Truncated mid-array, exactly like a max_tokens cutoff.
            return '[{"i":0,"is_launch":true,"stage":"world_prem', _TRUNCATED_USAGE
        return _reply([_item(i) for i in range(len(batch))])

    with patch("carwatch.llm.classify.call_classify", new=AsyncMock(side_effect=fake_call)):
        stats = await run_classify(db_pool, logger=None, limit=100)

    assert calls == [4, 2, 2]
    assert stats == {"in": 4, "approved": 4, "rejected": 0, "parse_errors": 0}
    async with db_pool.connection() as conn:
        result = await conn.execute("SELECT count(*) FROM raw_items WHERE classified IS NOT NULL")
        assert (await result.fetchone())[0] == 4


async def test_split_isolates_the_single_bad_item_and_counts_it_as_parse_error(db_pool):
    """The other half of the split must still be processed even when one item
    is genuinely unclassifiable — the damage is bounded to that one row."""
    await _insert_items(db_pool, ["BYD Seal 0 premiere", "BYD Seal 1 premiere"])

    async def fake_call(system_prompt, user_content):
        batch = json.loads(user_content)
        if len(batch) > 1:
            return "garbage, not json", _USAGE
        if "Seal 0" in user_content:
            return "still garbage", _USAGE
        return _reply([_item(0)])

    with patch("carwatch.llm.classify.call_classify", new=AsyncMock(side_effect=fake_call)):
        stats = await run_classify(db_pool, logger=None, limit=100)

    assert stats == {"in": 2, "approved": 1, "rejected": 0, "parse_errors": 1}


async def test_rows_are_batched_by_batch_size(db_pool):
    """A batch never exceeds BATCH_SIZE items (the value the token budget above
    is sized against)."""
    await _insert_items(db_pool, [f"BYD Seal {n} premiere" for n in range(BATCH_SIZE + 3)])

    sizes: list[int] = []

    async def fake_call(system_prompt, user_content):
        batch = json.loads(user_content)
        sizes.append(len(batch))
        return _reply([_item(i) for i in range(len(batch))])

    with patch("carwatch.llm.classify.call_classify", new=AsyncMock(side_effect=fake_call)):
        stats = await run_classify(db_pool, logger=None, limit=100)

    assert sizes == [BATCH_SIZE, 3]
    assert stats["approved"] == BATCH_SIZE + 3
