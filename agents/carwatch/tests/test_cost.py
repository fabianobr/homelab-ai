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
