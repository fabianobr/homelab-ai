"""tests/test_telegram.py"""
import httpx
import respx

from carwatch.publishers.telegram import (
    format_event_message,
    get_pending_events,
    mark_published,
    publish_pending_events,
    send_telegram_message,
)


@respx.mock
async def test_send_telegram_message_returns_true_on_success():
    respx.post("https://api.telegram.org/bottoken123/sendMessage").mock(
        return_value=httpx.Response(200, json={"ok": True})
    )
    assert await send_telegram_message("token123", "chat1", "hello") is True


@respx.mock
async def test_send_telegram_message_returns_false_on_http_error():
    respx.post("https://api.telegram.org/bottoken123/sendMessage").mock(return_value=httpx.Response(500))
    assert await send_telegram_message("token123", "chat1", "hello") is False


def test_format_event_message_includes_brand_model_stage_and_source_link():
    event = {
        "brand": "BYD", "model": "Seal 06", "stage": "world_premiere",
        "markets": ["CN"], "highlights": ["Estreia mundial em Shenzhen"],
        "powertrain": {"type": "bev", "power_hp": 212, "range_km": 520, "range_cycle": "WLTP"},
        "price": {"amount": 109800, "currency": "CNY", "status": "official"},
        "sales_start": "2026-Q2",
    }
    text = format_event_message(event, source_count=3, primary_url="https://x.com/a")

    assert "BYD Seal 06" in text
    assert "🌍" in text
    assert "Estreia mundial em Shenzhen" in text
    assert "212 cv" in text
    assert "CNY" in text
    assert "3 fonte(s)" in text
    assert 'href="https://x.com/a"' in text


def test_format_event_message_handles_missing_powertrain_and_price():
    event = {
        "brand": "Acme", "model": "X", "stage": "teaser", "markets": [],
        "highlights": [], "powertrain": None, "price": None, "sales_start": None,
    }
    text = format_event_message(event, source_count=1, primary_url="https://x.com/a")
    assert "não informado" in text
    assert "não divulgado" in text


def test_format_event_message_escapes_html_special_characters_in_llm_controlled_fields():
    # brand/model/highlights/markets/sales_start come from the LLM extraction
    # pipeline, not a fixed vocabulary, and the message is sent with
    # parse_mode="HTML" -- unescaped '<'/'>'/'&' would corrupt Telegram's
    # HTML parsing and fail the send.
    event = {
        "brand": "Foo & <Bar>", "model": "X < 5 & Y > 3", "stage": "teaser",
        "markets": ["CN & TW"], "highlights": ["Power < 300 hp & torque > 400 Nm"],
        "powertrain": {"type": "bev", "power_hp": None, "range_km": None, "range_cycle": None},
        "price": {"amount": 1000, "currency": "R$ <fake>", "status": "official"},
        "sales_start": "Q2 <2026> & beyond",
    }
    text = format_event_message(event, source_count=1, primary_url="https://x.com/a?x=1&y=2")

    assert "Foo &amp; &lt;Bar&gt;" in text
    assert "X &lt; 5 &amp; Y &gt; 3" in text
    assert "CN &amp; TW" in text
    assert "Power &lt; 300 hp &amp; torque &gt; 400 Nm" in text
    assert "Q2 &lt;2026&gt; &amp; beyond" in text
    assert "R$ &lt;fake&gt;" in text
    assert 'href="https://x.com/a?x=1&amp;y=2"' in text

    # No raw '<' or '>' should survive anywhere in the message -- the only
    # unescaped angle brackets allowed are the literal tags we build
    # ourselves (<b>, </b>, <a href="...">, </a>).
    import re

    stripped = re.sub(r"</?(b|a)( href=\"[^\"]*\")?>", "", text)
    assert "<" not in stripped
    assert ">" not in stripped


async def test_get_pending_events_excludes_published_and_low_confidence(db_pool):
    async with db_pool.connection() as conn:
        source = await conn.execute(
            "INSERT INTO sources (domain, feed_url, kind, tier, status) "
            "VALUES ('x.com', 'https://x.com/feed', 'rss', 1, 'active') RETURNING id"
        )
        source_id = (await source.fetchone())[0]
        item = await conn.execute(
            "INSERT INTO raw_items (source_id, url, url_hash, title) "
            "VALUES (%s, 'https://x.com/a', 'h1', 't') RETURNING id",
            (source_id,),
        )
        item_id = (await item.fetchone())[0]

        pending = await conn.execute(
            "INSERT INTO launch_events (dedupe_key, brand, model, model_slug, stage, "
            "highlights, confidence, published) VALUES "
            "('k1', 'BYD', 'Seal 06', 'seal-06', 'world_premiere', ARRAY['h'], 0.9, FALSE) RETURNING id"
        )
        pending_id = (await pending.fetchone())[0]
        await conn.execute(
            "INSERT INTO launch_events (dedupe_key, brand, model, model_slug, stage, "
            "highlights, confidence, published) VALUES "
            "('k2', 'BYD', 'Seal 07', 'seal-07', 'world_premiere', ARRAY['h'], 0.9, TRUE)"
        )
        await conn.execute(
            "INSERT INTO launch_events (dedupe_key, brand, model, model_slug, stage, "
            "highlights, confidence, published) VALUES "
            "('k3', 'BYD', 'Seal 08', 'seal-08', 'world_premiere', ARRAY['h'], 0.5, FALSE)"
        )
        await conn.execute(
            "INSERT INTO event_sources (event_id, item_id, source_id, is_primary) VALUES (%s, %s, %s, TRUE)",
            (pending_id, item_id, source_id),
        )

    events = await get_pending_events(db_pool)

    assert len(events) == 1
    assert events[0]["id"] == pending_id
    assert events[0]["primary_url"] == "https://x.com/a"
    assert events[0]["source_count"] == 1


@respx.mock
async def test_publish_pending_events_marks_published_only_on_success(db_pool):
    respx.post("https://api.telegram.org/bottoken123/sendMessage").mock(
        return_value=httpx.Response(200, json={"ok": True})
    )
    async with db_pool.connection() as conn:
        result = await conn.execute(
            "INSERT INTO launch_events (dedupe_key, brand, model, model_slug, stage, "
            "highlights, confidence, published) VALUES "
            "('k1', 'BYD', 'Seal 06', 'seal-06', 'world_premiere', ARRAY['h'], 0.9, FALSE) RETURNING id"
        )
        event_id = (await result.fetchone())[0]

    stats = await publish_pending_events(db_pool, "token123", "chat1", logger=None)

    assert stats == {"pending": 1, "sent": 1}
    async with db_pool.connection() as conn:
        result = await conn.execute("SELECT published FROM launch_events WHERE id = %s", (event_id,))
        assert (await result.fetchone())[0] is True
