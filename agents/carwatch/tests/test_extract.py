"""tests/test_extract.py"""
import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

from carwatch.llm.extract import (
    extract_article_text,
    parse_extract_response,
    run_extract,
    truncate_for_llm,
)

FIXTURES = Path(__file__).parent / "fixtures" / "articles"

_USAGE = {"tokens_in": 100, "tokens_out": 60, "stop_reason": "end_turn"}


def test_extract_article_text_prefers_ld_json_when_present():
    html = (FIXTURES / "ld_json_article.html").read_text()
    text = extract_article_text(html)
    assert "109800 CNY" in text
    assert "messier" not in text


def test_extract_article_text_falls_back_to_article_tag():
    html = (FIXTURES / "simple_article.html").read_text()
    text = extract_article_text(html)
    assert "Shenzhen" in text
    assert "109,800 CNY" in text


def test_truncate_for_llm_caps_at_24000_chars():
    text = "x" * 30000
    assert len(truncate_for_llm(text)) == 24000


def test_parse_extract_response_accepts_well_formed_json():
    raw = json.dumps(
        {
            "brand": "BYD", "model": "Seal 06", "generation": None, "body_type": "sedan",
            "stage": "world_premiere", "is_new_generation": False, "markets": ["CN"],
            "global_debut": True, "event_date": "2026-01-15", "sales_start": "2026-Q2",
            "powertrain": {"type": "bev", "power_hp": 212, "range_km": 520, "range_cycle": "WLTP"},
            "price": {"amount": 109800, "currency": "CNY", "status": "official"},
            "highlights": ["Estreia mundial em Shenzhen"], "confidence": 0.9,
        }
    )
    event = parse_extract_response(raw)
    assert event is not None
    assert event.powertrain.power_hp == 212


def test_parse_extract_response_rejects_invalid_json():
    assert parse_extract_response("not json") is None


def test_parse_extract_response_ignores_trailing_chatter_with_stray_braces():
    """The old `re.search(r"\\{.*\\}", cleaned, re.DOTALL)` is greedy: it
    matches from the FIRST `{` to the LAST `}` in the whole cleaned text. A
    well-formed JSON object followed by trailing LLM chatter that itself
    contains a `{`/`}` (e.g. "Nota: {sic}") would make the old regex capture
    through the stray closing brace in "sic}", producing
    `{...well-formed...} Nota: {sic}` -- not valid JSON, so json.loads()
    would raise and parse_extract_response would return None even though the
    real JSON object was perfectly parseable on its own.
    JSONDecoder().raw_decode() instead parses only the first complete JSON
    value and ignores everything after it, so this must still succeed.
    """
    well_formed = json.dumps(
        {
            "brand": "BYD", "model": "Seal 06", "generation": None, "body_type": "sedan",
            "stage": "world_premiere", "is_new_generation": False, "markets": ["CN"],
            "global_debut": True, "event_date": "2026-01-15", "sales_start": None,
            "powertrain": None, "price": None, "highlights": ["Estreia mundial"], "confidence": 0.9,
        }
    )
    raw = well_formed + " Nota: {sic} dados incompletos"

    event = parse_extract_response(raw)

    assert event is not None
    assert event.brand == "BYD"
    assert event.model == "Seal 06"


def test_parse_extract_response_never_invents_missing_numeric_fields():
    raw = json.dumps(
        {
            "brand": "BYD", "model": "Seal 06", "generation": None, "body_type": "sedan",
            "stage": "teaser", "is_new_generation": False, "markets": [],
            "global_debut": False, "event_date": None, "sales_start": None,
            "powertrain": {"type": "bev"}, "price": None,
            "highlights": ["Teaser oficial divulgado"], "confidence": 0.6,
        }
    )
    event = parse_extract_response(raw)
    assert event.powertrain.power_hp is None
    assert event.price is None


async def test_run_extract_marks_success_as_extracted_and_calls_dedupe(db_pool):
    async with db_pool.connection() as conn:
        source = await conn.execute(
            "INSERT INTO sources (domain, feed_url, kind, tier, status) "
            "VALUES ('x.com', 'https://x.com/feed', 'rss', 1, 'active') RETURNING id"
        )
        source_id = (await source.fetchone())[0]
        classified = json.dumps({"i": 0, "is_launch": True, "stage": "world_premiere", "brand": "BYD", "model": "Seal 06", "confidence": 0.9})
        item = await conn.execute(
            "INSERT INTO raw_items (source_id, url, url_hash, title, status, classified) "
            "VALUES (%s, 'https://x.com/article', 'hash-1', 'BYD reveals Seal 06', 'new', %s) RETURNING id",
            (source_id, classified),
        )
        item_id = (await item.fetchone())[0]

    fake_extracted_json = json.dumps(
        {
            "brand": "BYD", "model": "Seal 06", "generation": None, "body_type": "sedan",
            "stage": "world_premiere", "is_new_generation": False, "markets": ["CN"],
            "global_debut": True, "event_date": "2026-01-15", "sales_start": None,
            "powertrain": None, "price": None, "highlights": ["Estreia mundial"], "confidence": 0.9,
        }
    )

    with patch("carwatch.llm.extract.fetcher.fetch", new=AsyncMock(
        return_value=type("R", (), {"status": 200, "body": "x" * 1000, "blocked": False})()
    )), patch("carwatch.llm.extract.call_extract", new=AsyncMock(return_value=(fake_extracted_json, _USAGE))):
        stats = await run_extract(db_pool, logger=None, limit=10)

    assert stats == {"in": 1, "extracted": 1, "error": 0}
    async with db_pool.connection() as conn:
        result = await conn.execute("SELECT status FROM raw_items WHERE id = %s", (item_id,))
        assert (await result.fetchone())[0] == "extracted"
        result = await conn.execute("SELECT count(*) FROM launch_events")
        assert (await result.fetchone())[0] == 1


async def test_run_extract_marks_unparseable_response_as_error_after_one_retry(db_pool):
    async with db_pool.connection() as conn:
        source = await conn.execute(
            "INSERT INTO sources (domain, feed_url, kind, tier, status) "
            "VALUES ('x.com', 'https://x.com/feed', 'rss', 1, 'active') RETURNING id"
        )
        source_id = (await source.fetchone())[0]
        classified = json.dumps({"i": 0, "is_launch": True, "stage": "world_premiere", "brand": "BYD", "model": "Seal 06", "confidence": 0.9})
        item = await conn.execute(
            "INSERT INTO raw_items (source_id, url, url_hash, title, status, classified) "
            "VALUES (%s, 'https://x.com/article', 'hash-1', 'BYD reveals Seal 06', 'new', %s) RETURNING id",
            (source_id, classified),
        )
        item_id = (await item.fetchone())[0]

    with patch("carwatch.llm.extract.fetcher.fetch", new=AsyncMock(
        return_value=type("R", (), {"status": 200, "body": "x" * 1000, "blocked": False})()
    )), patch("carwatch.llm.extract.call_extract", new=AsyncMock(return_value=("not json, ever", _USAGE))):
        stats = await run_extract(db_pool, logger=None, limit=10)

    assert stats == {"in": 1, "extracted": 0, "error": 1}
    async with db_pool.connection() as conn:
        result = await conn.execute("SELECT status FROM raw_items WHERE id = %s", (item_id,))
        assert (await result.fetchone())[0] == "error"


async def _insert_approved_item(db_pool, *, title="BYD reveals Seal 06", summary=None) -> tuple[int, int]:
    async with db_pool.connection() as conn:
        source = await conn.execute(
            "INSERT INTO sources (domain, feed_url, kind, tier, status) "
            "VALUES ('x.com', 'https://x.com/feed', 'rss', 1, 'active') RETURNING id"
        )
        source_id = (await source.fetchone())[0]
        classified = json.dumps({"i": 0, "is_launch": True, "stage": "world_premiere", "brand": "BYD", "model": "Seal 06", "confidence": 0.9})
        item = await conn.execute(
            "INSERT INTO raw_items (source_id, url, url_hash, title, summary, status, classified) "
            "VALUES (%s, 'https://x.com/article', 'hash-1', %s, %s, 'new', %s) RETURNING id",
            (source_id, title, summary, classified),
        )
        item_id = (await item.fetchone())[0]
    return item_id, source_id


def _fake_extracted(confidence: float) -> tuple[str, dict]:
    """call_extract's (text, usage) contract."""
    text = json.dumps(
        {
            "brand": "BYD", "model": "Seal 06", "generation": None, "body_type": "sedan",
            "stage": "world_premiere", "is_new_generation": False, "markets": ["CN"],
            "global_debut": True, "event_date": "2026-01-15", "sales_start": None,
            "powertrain": None, "price": None, "highlights": ["Estreia mundial"],
            "confidence": confidence,
        }
    )
    return text, _USAGE


async def test_run_extract_degraded_short_body_caps_confidence_and_uses_title_summary(db_pool):
    item_id, _source_id = await _insert_approved_item(db_pool, title="BYD reveals Seal 06", summary="Short teaser summary.")

    call_extract_mock = AsyncMock(return_value=_fake_extracted(confidence=0.9))
    with patch("carwatch.llm.extract.fetcher.fetch", new=AsyncMock(
        # Real HTML but with no <article>/<main>/<p> content of any length,
        # so extract_article_text() returns text shorter than
        # MIN_TEXT_LEN_FOR_FULL_EXTRACT and the degraded path kicks in.
        return_value=type("R", (), {"status": 200, "body": "<html><body>tiny</body></html>", "blocked": False})()
    )), patch("carwatch.llm.extract.call_extract", new=call_extract_mock):
        stats = await run_extract(db_pool, logger=None, limit=10)

    assert stats == {"in": 1, "extracted": 1, "error": 0}

    call_text = call_extract_mock.await_args_list[0].args[0]
    assert "BYD reveals Seal 06" in call_text
    assert "Short teaser summary." in call_text

    async with db_pool.connection() as conn:
        result = await conn.execute("SELECT status, body FROM raw_items WHERE id = %s", (item_id,))
        status, body = await result.fetchone()
        assert status == "extracted"
        assert body is None
        result = await conn.execute("SELECT confidence FROM launch_events")
        confidence = (await result.fetchone())[0]
        assert confidence == 0.5


async def test_run_extract_blocked_fetch_degrades_to_title_summary_without_parsing_body(db_pool):
    item_id, _source_id = await _insert_approved_item(db_pool, title="BYD reveals Seal 06", summary="Blocked-page summary.")

    call_extract_mock = AsyncMock(return_value=_fake_extracted(confidence=0.9))
    with patch("carwatch.llm.extract.fetcher.fetch", new=AsyncMock(
        # blocked=True short-circuits straight to the degraded branch, with
        # no body to even attempt extract_article_text() on.
        return_value=type("R", (), {"status": 200, "body": None, "blocked": True})()
    )), patch("carwatch.llm.extract.call_extract", new=call_extract_mock):
        stats = await run_extract(db_pool, logger=None, limit=10)

    assert stats == {"in": 1, "extracted": 1, "error": 0}

    call_text = call_extract_mock.await_args_list[0].args[0]
    assert "BYD reveals Seal 06" in call_text
    assert "Blocked-page summary." in call_text

    async with db_pool.connection() as conn:
        result = await conn.execute("SELECT status, body FROM raw_items WHERE id = %s", (item_id,))
        status, body = await result.fetchone()
        assert status == "extracted"
        assert body is None
        result = await conn.execute("SELECT confidence FROM launch_events")
        confidence = (await result.fetchone())[0]
        assert confidence == 0.5


async def test_run_extract_full_article_path_preserves_confidence_and_uses_article_text(db_pool):
    item_id, _source_id = await _insert_approved_item(db_pool)
    long_article_html = (
        "<html><body><article><p>"
        + "BYD unveiled the Seal 06 today in Shenzhen. " * 15
        + "</p></article></body></html>"
    )

    call_extract_mock = AsyncMock(return_value=_fake_extracted(confidence=0.9))
    with patch("carwatch.llm.extract.fetcher.fetch", new=AsyncMock(
        return_value=type("R", (), {"status": 200, "body": long_article_html, "blocked": False})()
    )), patch("carwatch.llm.extract.call_extract", new=call_extract_mock):
        stats = await run_extract(db_pool, logger=None, limit=10)

    assert stats == {"in": 1, "extracted": 1, "error": 0}

    call_text = call_extract_mock.await_args_list[0].args[0]
    assert "Shenzhen" in call_text

    async with db_pool.connection() as conn:
        result = await conn.execute("SELECT status, body FROM raw_items WHERE id = %s", (item_id,))
        status, body = await result.fetchone()
        assert status == "extracted"
        assert body == long_article_html
        result = await conn.execute("SELECT confidence FROM launch_events")
        confidence = (await result.fetchone())[0]
        assert float(confidence) == 0.9


async def test_run_extract_retries_once_with_error_appended_then_succeeds(db_pool):
    await _insert_approved_item(db_pool)

    call_extract_mock = AsyncMock(side_effect=[("not json at all", _USAGE), _fake_extracted(confidence=0.8)])
    with patch("carwatch.llm.extract.fetcher.fetch", new=AsyncMock(
        return_value=type("R", (), {"status": 200, "body": "x" * 1000, "blocked": False})()
    )), patch("carwatch.llm.extract.call_extract", new=call_extract_mock):
        stats = await run_extract(db_pool, logger=None, limit=10)

    assert stats == {"in": 1, "extracted": 1, "error": 0}
    assert call_extract_mock.await_count == 2
    retry_text = call_extract_mock.await_args_list[1].args[0]
    assert "não pôde ser validada" in retry_text
