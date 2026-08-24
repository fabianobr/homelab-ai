"""src/carwatch/cost.py"""
from datetime import datetime, timezone
from pathlib import Path

import yaml

MONTHLY_COST_CAP_USD = 30.0


def compute_cost_usd(
    tokens_in: int, tokens_out: int, *, input_usd_per_million: float, output_usd_per_million: float
) -> float:
    return round(
        tokens_in / 1_000_000 * input_usd_per_million
        + tokens_out / 1_000_000 * output_usd_per_million,
        6,
    )


def load_llm_pricing(settings_path: Path, model: str) -> tuple[float, float]:
    data = yaml.safe_load(settings_path.read_text())
    pricing = data["llm_pricing"][model]
    return pricing["input_usd_per_million"], pricing["output_usd_per_million"]


async def record_llm_usage(pool, op: str, model: str, tokens_in: int, tokens_out: int, cost_usd: float) -> None:
    async with pool.connection() as conn:
        await conn.execute(
            "INSERT INTO llm_usage (op, model, tokens_in, tokens_out, cost_usd) VALUES (%s, %s, %s, %s, %s)",
            (op, model, tokens_in, tokens_out, cost_usd),
        )


async def month_to_date_cost_usd(pool, now: datetime | None = None) -> float:
    now = now or datetime.now(timezone.utc)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    async with pool.connection() as conn:
        result = await conn.execute(
            "SELECT COALESCE(sum(cost_usd), 0) FROM llm_usage WHERE called_at >= %s",
            (month_start,),
        )
        return float((await result.fetchone())[0])


async def is_extraction_cost_capped(pool, now: datetime | None = None) -> bool:
    return await month_to_date_cost_usd(pool, now) > MONTHLY_COST_CAP_USD
