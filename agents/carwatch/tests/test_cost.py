"""tests/test_cost.py"""
from datetime import datetime, timedelta, timezone
from pathlib import Path

from carwatch.cost import (
    MONTHLY_COST_CAP_USD,
    compute_cost_usd,
    is_extraction_cost_capped,
    load_llm_pricing,
    month_to_date_cost_usd,
    record_llm_usage,
)

CONFIG_DIR = Path(__file__).resolve().parents[1] / "config"


def test_compute_cost_usd_matches_haiku_pricing():
    cost = compute_cost_usd(1_000_000, 1_000_000, input_usd_per_million=1.0, output_usd_per_million=5.0)
    assert cost == 6.0


def test_load_llm_pricing_reads_settings_yaml():
    input_price, output_price = load_llm_pricing(CONFIG_DIR / "settings.yaml", "claude-haiku-4-5-20251001")
    assert input_price == 1.00
    assert output_price == 5.00


async def test_month_to_date_cost_sums_only_current_month(db_pool):
    now = datetime(2026, 8, 15, tzinfo=timezone.utc)
    await record_llm_usage(db_pool, "classify", "claude-haiku-4-5-20251001", 1000, 500, 0.0035)
    async with db_pool.connection() as conn:
        await conn.execute(
            "INSERT INTO llm_usage (called_at, op, model, tokens_in, tokens_out, cost_usd) "
            "VALUES (%s, 'extract', 'claude-haiku-4-5-20251001', 1000, 500, 5.0)",
            (now - timedelta(days=40),),  # previous month — must be excluded
        )

    total = await month_to_date_cost_usd(db_pool, now=now)

    assert abs(total - 0.0035) < 1e-6


async def test_is_extraction_cost_capped_true_above_30_usd(db_pool):
    now = datetime(2026, 8, 15, tzinfo=timezone.utc)
    await record_llm_usage(db_pool, "extract", "claude-haiku-4-5-20251001", 1_000_000, 6_000_000, 31.0)

    assert await is_extraction_cost_capped(db_pool, now=now) is True


async def test_is_extraction_cost_capped_false_below_30_usd(db_pool):
    now = datetime(2026, 8, 15, tzinfo=timezone.utc)
    await record_llm_usage(db_pool, "extract", "claude-haiku-4-5-20251001", 1000, 500, 5.0)

    assert await is_extraction_cost_capped(db_pool, now=now) is False


def test_monthly_cost_cap_matches_spec_value():
    assert MONTHLY_COST_CAP_USD == 30.0


def test_load_llm_pricing_returns_zero_fallback_instead_of_raising_for_unknown_model(tmp_path, capsys):
    """Regression test: load_llm_pricing() used to do a bare dict[key]
    lookup and raise KeyError for a model missing from settings.yaml's
    llm_pricing table. It's called from inside classify.py/extract.py's
    try/except-protected paths AFTER the (already billed) Anthropic API call
    -- a raised KeyError there would discard a paid-for result instead of
    just under-reporting its cost as $0.

    Asserts on stdout (structlog's PrintLoggerFactory default sink), mirroring
    test_fetcher.py::test_fetch_emits_fetch_result_event's convention for
    checking structlog output -- caplog doesn't capture it since structlog
    isn't routed through stdlib logging here.
    """
    settings_path = tmp_path / "settings.yaml"
    settings_path.write_text(
        "llm_pricing:\n"
        '  "claude-haiku-4-5-20251001":\n'
        "    input_usd_per_million: 1.00\n"
        "    output_usd_per_million: 5.00\n"
    )

    input_price, output_price = load_llm_pricing(settings_path, "claude-opus-4-9-nonexistent")

    assert (input_price, output_price) == (0.0, 0.0)
    out = capsys.readouterr().out
    assert "cost.pricing_missing" in out
    assert "claude-opus-4-9-nonexistent" in out


def test_load_llm_pricing_caches_parsed_settings_across_calls(tmp_path):
    """load_llm_pricing() is called once per classify batch and up to twice
    per extract item -- it must not re-read the file from disk every time.
    Overwriting the file after the first call and confirming the second call
    still returns the ORIGINAL value proves the cache is actually being hit
    (a non-cached implementation would return the new value instead).
    """
    settings_path = tmp_path / "settings.yaml"
    settings_path.write_text(
        "llm_pricing:\n"
        '  "cached-model":\n'
        "    input_usd_per_million: 2.00\n"
        "    output_usd_per_million: 10.00\n"
    )

    first = load_llm_pricing(settings_path, "cached-model")
    assert first == (2.00, 10.00)

    settings_path.write_text(
        "llm_pricing:\n"
        '  "cached-model":\n'
        "    input_usd_per_million: 999.00\n"
        "    output_usd_per_million: 999.00\n"
    )

    second = load_llm_pricing(settings_path, "cached-model")
    assert second == (2.00, 10.00)  # still the cached value, not re-read from disk
