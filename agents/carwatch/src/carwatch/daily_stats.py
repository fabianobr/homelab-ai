"""src/carwatch/daily_stats.py"""
from datetime import date, datetime, timedelta, timezone


async def aggregate_daily_stats(pool, day: date | None = None) -> dict:
    day = day or datetime.now(timezone.utc).date()
    day_start = datetime(day.year, day.month, day.day, tzinfo=timezone.utc)
    day_end = day_start + timedelta(days=1)

    async with pool.connection() as conn:
        result = await conn.execute(
            "SELECT count(*), "
            "count(*) FILTER (WHERE classified->>'is_launch' = 'true'), "
            "count(*) FILTER (WHERE status = 'extracted') "
            "FROM raw_items WHERE fetched_at >= %s AND fetched_at < %s",
            (day_start, day_end),
        )
        items_ingested, items_approved, items_extracted = await result.fetchone()

        result = await conn.execute(
            "SELECT count(*) FILTER (WHERE first_seen_at >= %s AND first_seen_at < %s), "
            "count(*) FILTER (WHERE published = TRUE AND updated_at >= %s AND updated_at < %s) "
            "FROM launch_events",
            (day_start, day_end, day_start, day_end),
        )
        events_created, events_published = await result.fetchone()

        result = await conn.execute(
            "SELECT count(*), COALESCE(sum(tokens_in), 0), COALESCE(sum(tokens_out), 0), "
            "COALESCE(sum(cost_usd), 0) FROM llm_usage WHERE called_at >= %s AND called_at < %s",
            (day_start, day_end),
        )
        llm_calls, llm_tokens_in, llm_tokens_out, llm_cost_usd = await result.fetchone()

        result = await conn.execute(
            "SELECT count(*) FILTER (WHERE status = 'active'), "
            "count(*) FILTER (WHERE status = 'blocked') FROM sources"
        )
        sources_active, sources_blocked = await result.fetchone()

        stats = {
            "items_ingested": items_ingested,
            "items_approved": items_approved,
            "items_extracted": items_extracted,
            "events_created": events_created,
            "events_published": events_published,
            "llm_calls": llm_calls,
            "llm_tokens_in": llm_tokens_in,
            "llm_tokens_out": llm_tokens_out,
            "llm_cost_usd": float(llm_cost_usd),
            "sources_active": sources_active,
            "sources_blocked": sources_blocked,
        }

        await conn.execute(
            "INSERT INTO daily_stats (day, items_ingested, items_approved, items_extracted, "
            "events_created, events_published, llm_calls, llm_tokens_in, llm_tokens_out, "
            "llm_cost_usd, sources_active, sources_blocked, computed_at) "
            "VALUES (%(day)s, %(items_ingested)s, %(items_approved)s, %(items_extracted)s, "
            "%(events_created)s, %(events_published)s, %(llm_calls)s, %(llm_tokens_in)s, "
            "%(llm_tokens_out)s, %(llm_cost_usd)s, %(sources_active)s, %(sources_blocked)s, now()) "
            "ON CONFLICT (day) DO UPDATE SET "
            "items_ingested = EXCLUDED.items_ingested, items_approved = EXCLUDED.items_approved, "
            "items_extracted = EXCLUDED.items_extracted, events_created = EXCLUDED.events_created, "
            "events_published = EXCLUDED.events_published, llm_calls = EXCLUDED.llm_calls, "
            "llm_tokens_in = EXCLUDED.llm_tokens_in, llm_tokens_out = EXCLUDED.llm_tokens_out, "
            "llm_cost_usd = EXCLUDED.llm_cost_usd, sources_active = EXCLUDED.sources_active, "
            "sources_blocked = EXCLUDED.sources_blocked, computed_at = now()",
            {**stats, "day": day},
        )

    return stats
