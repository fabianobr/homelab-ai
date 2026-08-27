"""tests/test_telegram.py"""
import json
from datetime import datetime, timedelta, timezone

import httpx
import respx

from carwatch.publishers import telegram
from carwatch.publishers.telegram import (
    fetch_usd_rates,
    format_event_message,
    get_pending_events,
    mark_published,
    publish_pending_events,
    send_telegram_message,
)


class _ListLogger:
    """Minimal stand-in for structlog's logger, just enough to assert on calls."""

    def __init__(self):
        self.warnings = []
        self.infos = []

    def warning(self, event, **kwargs):
        self.warnings.append((event, kwargs))

    def info(self, event, **kwargs):
        self.infos.append((event, kwargs))


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


def test_format_event_message_omits_stray_empty_parenthetical_when_price_status_is_none():
    # `status` is a valid None value on the Price model even when `amount` is
    # present (e.g. extraction couldn't determine official/estimated/starting_from).
    # PRICE_STATUS_LABEL.get(None, "") returns "", so the parenthetical must be
    # omitted entirely rather than rendered as a stray "()".
    event = {
        "brand": "Acme", "model": "X", "stage": "teaser", "markets": [],
        "highlights": [], "powertrain": None,
        "price": {"amount": 109800, "currency": "CNY", "status": None},
        "sales_start": None,
    }
    text = format_event_message(event, source_count=1, primary_url="https://x.com/a")
    assert "CNY 109,800" in text
    assert "()" not in text


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


def test_format_event_message_shows_flag_and_country_name_for_known_markets():
    event = {
        "brand": "BYD", "model": "Seal 06", "stage": "world_premiere",
        "markets": ["CN", "DE"], "highlights": [], "powertrain": None,
        "price": None, "sales_start": None,
    }
    text = format_event_message(event, source_count=1, primary_url="https://x.com/a")
    assert "🇨🇳 China" in text
    assert "🇩🇪 Alemanha" in text
    # raw ISO codes should no longer be shown standalone
    assert "CN, DE" not in text


def test_format_event_message_falls_back_to_flag_and_code_for_unknown_market():
    event = {
        "brand": "Acme", "model": "X", "stage": "teaser", "markets": ["XX"],
        "highlights": [], "powertrain": None, "price": None, "sales_start": None,
    }
    text = format_event_message(event, source_count=1, primary_url="https://x.com/a")
    assert "🇽🇽 XX" in text


def test_format_event_message_shows_no_markets_as_global():
    event = {
        "brand": "Acme", "model": "X", "stage": "teaser", "markets": [],
        "highlights": [], "powertrain": None, "price": None, "sales_start": None,
    }
    text = format_event_message(event, source_count=1, primary_url="https://x.com/a")
    assert "Global" in text


def test_format_event_message_normalizes_lowercase_market_code():
    # extract.py's prompt asks for ISO-3166-1 alpha-2 but nothing in the
    # Pydantic schema enforces case -- a lowercase code from the LLM must
    # still resolve to the right flag and country name, not silently fall
    # back to the raw-code path.
    event = {
        "brand": "Acme", "model": "X", "stage": "teaser", "markets": ["cn"],
        "highlights": [], "powertrain": None, "price": None, "sales_start": None,
    }
    text = format_event_message(event, source_count=1, primary_url="https://x.com/a")
    assert "🇨🇳 China" in text


def test_format_event_message_handles_malformed_market_code_without_crashing():
    # markets is LLM free text (see the escaping test above), not a validated
    # vocabulary -- a code that isn't exactly 2 letters must degrade
    # gracefully (no flag, escaped raw label) instead of raising.
    event = {
        "brand": "Acme", "model": "X", "stage": "teaser", "markets": ["", "5A", "USA"],
        "highlights": [], "powertrain": None, "price": None, "sales_start": None,
    }
    text = format_event_message(event, source_count=1, primary_url="https://x.com/a")
    assert "5A" in text
    assert "USA" in text


def test_format_event_message_joins_known_and_unknown_markets_together():
    event = {
        "brand": "Acme", "model": "X", "stage": "teaser", "markets": ["CN", "XX"],
        "highlights": [], "powertrain": None, "price": None, "sales_start": None,
    }
    text = format_event_message(event, source_count=1, primary_url="https://x.com/a")
    assert "🇨🇳 China, 🇽🇽 XX" in text


def test_format_event_message_shows_usd_conversion_when_rate_available():
    event = {
        "brand": "BYD", "model": "Seal 06", "stage": "pricing", "markets": [],
        "highlights": [], "powertrain": None,
        "price": {"amount": 109800, "currency": "CNY", "status": "official"},
        "sales_start": None,
    }
    text = format_event_message(
        event, source_count=1, primary_url="https://x.com/a", usd_rates={"CNY": 7.32}
    )
    assert "CNY 109,800" in text
    assert "≈ US$ 15,000" in text
    # Full composed substring, so an ordering bug between the USD-conversion
    # append and the status append (e.g. status landing before the amount)
    # would fail here even though the two pieces individually look right.
    assert "CNY 109,800 (≈ US$ 15,000) · oficial" in text


def test_format_event_message_normalizes_lowercase_currency_code_for_usd_conversion():
    event = {
        "brand": "BYD", "model": "Seal 06", "stage": "pricing", "markets": [],
        "highlights": [], "powertrain": None,
        "price": {"amount": 109800, "currency": "cny", "status": None},
        "sales_start": None,
    }
    text = format_event_message(
        event, source_count=1, primary_url="https://x.com/a", usd_rates={"CNY": 7.32}
    )
    assert "≈ US$ 15,000" in text


def test_format_event_message_omits_usd_conversion_when_no_rate_for_currency():
    event = {
        "brand": "BYD", "model": "Seal 06", "stage": "pricing", "markets": [],
        "highlights": [], "powertrain": None,
        "price": {"amount": 109800, "currency": "CNY", "status": "official"},
        "sales_start": None,
    }
    text = format_event_message(event, source_count=1, primary_url="https://x.com/a", usd_rates={})
    assert "CNY 109,800" in text
    assert "US$" not in text


def test_format_event_message_omits_redundant_usd_conversion_when_price_already_usd():
    event = {
        "brand": "Acme", "model": "X", "stage": "pricing", "markets": [],
        "highlights": [], "powertrain": None,
        "price": {"amount": 50000, "currency": "USD", "status": "official"},
        "sales_start": None,
    }
    text = format_event_message(
        event, source_count=1, primary_url="https://x.com/a", usd_rates={"CNY": 7.32}
    )
    assert "USD 50,000" in text
    assert "≈ US$" not in text


@respx.mock
async def test_fetch_usd_rates_returns_rates_on_success():
    # Mock URL is derived from the module constant rather than hardcoded, so
    # if FRANKFURTER_API ever moves again (as it already has once -- see the
    # comment on the constant) this test breaks loudly instead of passing
    # against a stub the real code no longer calls.
    respx.get(telegram.FRANKFURTER_API, params={"from": "USD", "to": "CNY,EUR"}).mock(
        return_value=httpx.Response(200, json={"amount": 1.0, "base": "USD", "rates": {"CNY": 7.32, "EUR": 0.92}})
    )
    rates = await fetch_usd_rates({"CNY", "EUR"})
    assert rates == {"CNY": 7.32, "EUR": 0.92}


@respx.mock
async def test_fetch_usd_rates_follows_redirects(monkeypatch):
    # Regression test for the real bug this shipped with: the old
    # frankfurter.app host now 301-redirects, and httpx doesn't follow
    # redirects by default, so an unmocked-for-redirects client would
    # raise_for_status() on the 3xx and silently degrade to {}. This pins
    # follow_redirects=True actually working, independent of which host the
    # constant currently points at.
    respx.get("https://old-host.example/latest").mock(
        return_value=httpx.Response(301, headers={"location": "https://new-host.example/latest"})
    )
    respx.get("https://new-host.example/latest").mock(
        return_value=httpx.Response(200, json={"rates": {"CNY": 7.32}})
    )
    monkeypatch.setattr(telegram, "FRANKFURTER_API", "https://old-host.example/latest")
    rates = await fetch_usd_rates({"CNY"})
    assert rates == {"CNY": 7.32}


@respx.mock
async def test_fetch_usd_rates_returns_empty_dict_on_http_error():
    respx.get(telegram.FRANKFURTER_API).mock(return_value=httpx.Response(500))
    rates = await fetch_usd_rates({"CNY"})
    assert rates == {}


@respx.mock
async def test_fetch_usd_rates_returns_empty_dict_on_invalid_json_body():
    respx.get(telegram.FRANKFURTER_API).mock(return_value=httpx.Response(200, content=b"not json"))
    rates = await fetch_usd_rates({"CNY"})
    assert rates == {}


@respx.mock
async def test_fetch_usd_rates_logs_warning_on_failure():
    respx.get(telegram.FRANKFURTER_API).mock(return_value=httpx.Response(500))
    logger = _ListLogger()
    rates = await fetch_usd_rates({"CNY"}, logger)
    assert rates == {}
    assert len(logger.warnings) == 1
    event, kwargs = logger.warnings[0]
    assert event == "publish.usd_rates_failed"
    assert kwargs["currencies"] == ["CNY"]


@respx.mock
async def test_fetch_usd_rates_skips_network_call_when_only_usd_requested():
    # @respx.mock with no routes registered means an unexpected HTTP call
    # raises instead of silently hitting the real network -- this proves
    # fetch_usd_rates short-circuits before making any request when nothing
    # needs converting.
    rates = await fetch_usd_rates({"USD"})
    assert rates == {}


@respx.mock
async def test_fetch_usd_rates_normalizes_lowercase_currency_codes():
    respx.get(telegram.FRANKFURTER_API, params={"from": "USD", "to": "CNY"}).mock(
        return_value=httpx.Response(200, json={"rates": {"CNY": 7.32}})
    )
    rates = await fetch_usd_rates({"cny", " Cny "})
    assert rates == {"CNY": 7.32}


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


async def test_mark_published_sets_published_at_to_now_not_first_seen_at(db_pool):
    """Regression test: mark_published() used to only flip `published`,
    never touching `published_at` (a new column) or `updated_at`. daily_stats
    counts events_published off published_at, so this must actually be set
    to "now", distinct from the row's original first_seen_at.
    """
    old_first_seen = datetime.now(timezone.utc) - timedelta(days=10)
    async with db_pool.connection() as conn:
        result = await conn.execute(
            "INSERT INTO launch_events (dedupe_key, brand, model, model_slug, stage, "
            "highlights, confidence, published, first_seen_at) VALUES "
            "('k1', 'BYD', 'Seal 06', 'seal-06', 'world_premiere', ARRAY['h'], 0.9, FALSE, %s) "
            "RETURNING id",
            (old_first_seen,),
        )
        event_id = (await result.fetchone())[0]

    before = datetime.now(timezone.utc)
    await mark_published(db_pool, event_id)
    after = datetime.now(timezone.utc)

    async with db_pool.connection() as conn:
        result = await conn.execute(
            "SELECT published, published_at, first_seen_at FROM launch_events WHERE id = %s", (event_id,)
        )
        published, published_at, first_seen_at = await result.fetchone()

    assert published is True
    assert published_at is not None
    assert before - timedelta(seconds=5) <= published_at <= after + timedelta(seconds=5)
    assert published_at != first_seen_at


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


@respx.mock
async def test_publish_pending_events_includes_usd_conversion_in_sent_message(db_pool):
    # This is the integration seam the PR actually added: publish_pending_events
    # gathering currencies and fetching rates *before* the send loop. A test
    # that only calls format_event_message directly (as all the earlier tests
    # in this file do) can't catch a regression here -- e.g. forgetting to
    # thread usd_rates through, or filtering the currency set wrong.
    telegram_route = respx.post("https://api.telegram.org/bottoken123/sendMessage").mock(
        return_value=httpx.Response(200, json={"ok": True})
    )
    fx_route = respx.get(telegram.FRANKFURTER_API, params={"from": "USD", "to": "CNY"}).mock(
        return_value=httpx.Response(200, json={"rates": {"CNY": 7.32}})
    )
    async with db_pool.connection() as conn:
        await conn.execute(
            "INSERT INTO launch_events (dedupe_key, brand, model, model_slug, stage, "
            "highlights, price, confidence, published) VALUES "
            "('k1', 'BYD', 'Seal 06', 'seal-06', 'pricing', ARRAY['h'], %s, 0.9, FALSE)",
            (json.dumps({"amount": 109800, "currency": "CNY", "status": "official"}),),
        )

    stats = await publish_pending_events(db_pool, "token123", "chat1", logger=None)

    assert stats == {"pending": 1, "sent": 1}
    assert fx_route.call_count == 1
    sent_text = json.loads(telegram_route.calls.last.request.content)["text"]
    assert "≈ US$ 15,000" in sent_text


@respx.mock
async def test_publish_pending_events_fetches_usd_rates_once_for_shared_currency(db_pool):
    fx_route = respx.get(telegram.FRANKFURTER_API, params={"from": "USD", "to": "CNY"}).mock(
        return_value=httpx.Response(200, json={"rates": {"CNY": 7.32}})
    )
    respx.post("https://api.telegram.org/bottoken123/sendMessage").mock(
        return_value=httpx.Response(200, json={"ok": True})
    )
    async with db_pool.connection() as conn:
        for key in ("k1", "k2"):
            await conn.execute(
                "INSERT INTO launch_events (dedupe_key, brand, model, model_slug, stage, "
                "highlights, price, confidence, published) VALUES "
                f"('{key}', 'BYD', 'Seal 06', 'seal-06-{key}', 'pricing', ARRAY['h'], %s, 0.9, FALSE)",
                (json.dumps({"amount": 100000, "currency": "CNY", "status": None}),),
            )

    stats = await publish_pending_events(db_pool, "token123", "chat1", logger=None)

    assert stats == {"pending": 2, "sent": 2}
    # One fetch for the batch, not one per event that shares the currency.
    assert fx_route.call_count == 1


@respx.mock
async def test_publish_pending_events_still_sends_when_usd_rate_fetch_fails(db_pool):
    # Pins the design intent stated in fetch_usd_rates's own docstring: an FX
    # outage must not block the Telegram send it has nothing to do with.
    respx.get(telegram.FRANKFURTER_API).mock(return_value=httpx.Response(500))
    respx.post("https://api.telegram.org/bottoken123/sendMessage").mock(
        return_value=httpx.Response(200, json={"ok": True})
    )
    async with db_pool.connection() as conn:
        result = await conn.execute(
            "INSERT INTO launch_events (dedupe_key, brand, model, model_slug, stage, "
            "highlights, price, confidence, published) VALUES "
            "('k1', 'BYD', 'Seal 06', 'seal-06', 'pricing', ARRAY['h'], %s, 0.9, FALSE) RETURNING id",
            (json.dumps({"amount": 109800, "currency": "CNY", "status": "official"}),),
        )
        event_id = (await result.fetchone())[0]

    logger = _ListLogger()
    stats = await publish_pending_events(db_pool, "token123", "chat1", logger=logger)

    assert stats == {"pending": 1, "sent": 1}
    assert any(event == "publish.usd_rates_failed" for event, _ in logger.warnings)
    async with db_pool.connection() as conn:
        result = await conn.execute("SELECT published FROM launch_events WHERE id = %s", (event_id,))
        assert (await result.fetchone())[0] is True
    async with db_pool.connection() as conn:
        result = await conn.execute("SELECT published FROM launch_events WHERE id = %s", (event_id,))
        assert (await result.fetchone())[0] is True
