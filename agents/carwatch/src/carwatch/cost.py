"""src/carwatch/cost.py"""
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

import structlog
import yaml

MONTHLY_COST_CAP_USD = 30.0

logger = structlog.get_logger()


def compute_cost_usd(
    tokens_in: int, tokens_out: int, *, input_usd_per_million: float, output_usd_per_million: float
) -> float:
    return round(
        tokens_in / 1_000_000 * input_usd_per_million
        + tokens_out / 1_000_000 * output_usd_per_million,
        6,
    )


@lru_cache(maxsize=None)
def _load_pricing_table(settings_path: Path) -> dict:
    """Parse settings.yaml's `llm_pricing` table once per process.

    load_llm_pricing() below is called once per classify batch and up to
    twice per extract item -- re-reading and re-parsing settings.yaml from
    disk on every single call is wasted I/O for content that never changes
    within a process's lifetime. Cached by settings_path so tests pointing at
    a different file still get correct, independent results.
    """
    data = yaml.safe_load(settings_path.read_text())
    return data.get("llm_pricing", {})


def load_llm_pricing(settings_path: Path, model: str) -> tuple[float, float]:
    """Return (input_usd_per_million, output_usd_per_million) for `model`.

    Falls back to (0.0, 0.0) -- with a loud error log -- instead of raising
    when `model` has no pricing entry in settings.yaml (e.g. after
    llm/client.py's MODEL constant is bumped to a new dated snapshot without
    a matching pricing entry being added). This is called from inside the
    try/except-protected code paths in llm/classify.py and llm/extract.py
    that exist specifically so a paid, already-billed API call's results are
    never discarded just because of a bookkeeping gap -- cost
    under-reporting (temporarily $0 for one model's calls) is strictly
    better than losing already-paid-for extraction/classification results.
    """
    pricing_table = _load_pricing_table(settings_path)
    pricing = pricing_table.get(model)
    if pricing is None:
        logger.error(
            "cost.pricing_missing",
            model=model,
            settings_path=str(settings_path),
            impact="cost_under_reported_as_zero_for_this_model",
        )
        return 0.0, 0.0
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
