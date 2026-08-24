"""src/carwatch/curate.py"""
from datetime import datetime, timedelta, timezone

from carwatch.publishers.telegram import send_telegram_message

PROMOTE_YIELD_THRESHOLD = 5.0
DEMOTE_MIN_AGE_DAYS = 30
RETIRE_PROBATION_DAYS = 60
STALE_BRAND_DAYS = 90


async def recompute_source_metrics(pool, now: datetime | None = None) -> int:
    now = now or datetime.now(timezone.utc)
    window_start = now - timedelta(days=30)

    async with pool.connection() as conn:
        result = await conn.execute("SELECT id FROM sources")
        source_ids = [r[0] for r in await result.fetchall()]

        for source_id in source_ids:
            items_result = await conn.execute(
                "SELECT count(*), count(*) FILTER (WHERE prefilter_ok = TRUE) "
                "FROM raw_items WHERE source_id = %s AND fetched_at >= %s",
                (source_id, window_start),
            )
            items_30d, passed_30d = await items_result.fetchone()

            events_result = await conn.execute(
                "SELECT count(DISTINCT event_id) FROM event_sources "
                "WHERE source_id = %s AND seen_at >= %s",
                (source_id, window_start),
            )
            events_30d = (await events_result.fetchone())[0]

            # Uniqueness is a fact about the event's ENTIRE source history, not
            # about what happens to still be inside the 30-day window — an
            # event either has one source ever or it doesn't, and that doesn't
            # change as older rows age out. Mirrors first_seen_30d below:
            # compute the unrestricted global count per event, then filter the
            # outer condition (this source's own row) by the window. Filtering
            # event_sources to the window BEFORE the count(*) = 1 check would
            # let an echo/republishing source get credited as "unique" once
            # the original reporting source's row ages out — exactly the
            # anti-gaming case SPEC.md §13 calls out.
            unique_result = await conn.execute(
                "SELECT count(*) FROM event_sources es WHERE es.source_id = %s AND es.seen_at >= %s "
                "AND (SELECT count(*) FROM event_sources es2 WHERE es2.event_id = es.event_id) = 1",
                (source_id, window_start),
            )
            unique_events_30d = (await unique_result.fetchone())[0]

            first_seen_result = await conn.execute(
                "SELECT count(*) FROM event_sources es WHERE es.source_id = %s AND es.seen_at >= %s "
                "AND es.seen_at = (SELECT min(seen_at) FROM event_sources es2 WHERE es2.event_id = es.event_id)",
                (source_id, window_start),
            )
            first_seen_30d = (await first_seen_result.fetchone())[0]

            precision_result = await conn.execute(
                "SELECT count(*) FILTER (WHERE le.review_status = 'confirmed')::float "
                "  / NULLIF(count(*) FILTER (WHERE le.review_status IN ('confirmed','rejected')), 0) * 100 "
                "FROM event_sources es JOIN launch_events le ON le.id = es.event_id "
                "WHERE es.source_id = %s AND es.seen_at >= %s",
                (source_id, window_start),
            )
            precision_30d = (await precision_result.fetchone())[0]

            yield_pct = round(events_30d / items_30d * 100, 2) if items_30d else None

            await conn.execute(
                "INSERT INTO source_metrics "
                "(source_id, items_30d, passed_prefilter_30d, events_30d, unique_events_30d, "
                " first_seen_30d, yield_pct, precision_30d, computed_at) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, now()) "
                "ON CONFLICT (source_id) DO UPDATE SET "
                "items_30d = EXCLUDED.items_30d, passed_prefilter_30d = EXCLUDED.passed_prefilter_30d, "
                "events_30d = EXCLUDED.events_30d, unique_events_30d = EXCLUDED.unique_events_30d, "
                "first_seen_30d = EXCLUDED.first_seen_30d, yield_pct = EXCLUDED.yield_pct, "
                "precision_30d = EXCLUDED.precision_30d, computed_at = now()",
                (source_id, items_30d, passed_30d, events_30d, unique_events_30d,
                 first_seen_30d, yield_pct, precision_30d),
            )

    return len(source_ids)


async def apply_transitions(pool, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)

    async with pool.connection() as conn:
        promoted = await conn.execute(
            "UPDATE sources SET status = 'active', probation_since = NULL "
            "FROM source_metrics sm WHERE sources.id = sm.source_id "
            "AND sources.status = 'probation' "
            "AND sm.yield_pct > %s AND sm.unique_events_30d > 0 "
            "RETURNING sources.id",
            (PROMOTE_YIELD_THRESHOLD,),
        )
        promoted_ids = [r[0] for r in await promoted.fetchall()]

        demoted = await conn.execute(
            "UPDATE sources SET status = 'probation', probation_since = %s "
            "FROM source_metrics sm WHERE sources.id = sm.source_id "
            "AND sources.status = 'active' "
            "AND sm.unique_events_30d = 0 AND sm.first_seen_30d = 0 "
            "AND sources.added_at < %s "
            "RETURNING sources.id",
            (now, now - timedelta(days=DEMOTE_MIN_AGE_DAYS)),
        )
        demoted_ids = [r[0] for r in await demoted.fetchall()]

        retire_cutoff = now - timedelta(days=RETIRE_PROBATION_DAYS)
        candidates = await conn.execute(
            "SELECT id FROM sources WHERE status = 'probation' "
            "AND probation_since IS NOT NULL AND probation_since < %s "
            "AND id NOT IN (SELECT source_id FROM pending_retirements)",
            (retire_cutoff,),
        )
        retirement_candidate_ids = [r[0] for r in await candidates.fetchall()]
        for source_id in retirement_candidate_ids:
            await conn.execute(
                "INSERT INTO pending_retirements (source_id) VALUES (%s) ON CONFLICT DO NOTHING",
                (source_id,),
            )

    return {
        "promoted": promoted_ids,
        "demoted": demoted_ids,
        "retirement_candidates": retirement_candidate_ids,
    }


async def find_stale_brands(pool, now: datetime | None = None) -> list[str]:
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(days=STALE_BRAND_DAYS)
    async with pool.connection() as conn:
        all_brands_result = await conn.execute("SELECT DISTINCT unnest(brand_scope) FROM sources")
        all_brands = {r[0] for r in await all_brands_result.fetchall()}
        recent_result = await conn.execute(
            "SELECT DISTINCT brand FROM launch_events WHERE first_seen_at >= %s", (cutoff,)
        )
        recent_brands = {r[0] for r in await recent_result.fetchall()}
    return sorted(b for b in all_brands if b not in recent_brands)


async def confirm_retirement(pool, source_id: int) -> None:
    async with pool.connection() as conn:
        await conn.execute("UPDATE sources SET status = 'retired' WHERE id = %s", (source_id,))
        await conn.execute("DELETE FROM pending_retirements WHERE source_id = %s", (source_id,))


async def send_curation_digest(
    pool, bot_token: str, chat_id: str, transitions: dict, stale_brands: list[str], logger
) -> bool:
    lines = ["📊 CarWatch — Curadoria semanal", ""]
    lines.append(f"Promovidas: {len(transitions['promoted'])}")
    lines.append(f"Rebaixadas: {len(transitions['demoted'])}")
    lines.append(
        f"Candidatas a aposentadoria (aguardando confirmação manual): "
        f"{len(transitions['retirement_candidates'])}"
    )
    if transitions["retirement_candidates"]:
        ids = ", ".join(str(i) for i in transitions["retirement_candidates"])
        lines.append(f"  IDs: {ids}")
        lines.append("  Confirme com: carwatch curate --confirm-retirement <id>")
    if stale_brands:
        lines.append("")
        lines.append(f"⚠️ Marcas sem lançamento em {STALE_BRAND_DAYS} dias: " + ", ".join(stale_brands))

    ok = await send_telegram_message(bot_token, chat_id, "\n".join(lines))
    if logger is not None:
        logger.info(
            "curate.digest", ok=ok,
            promoted=len(transitions["promoted"]), demoted=len(transitions["demoted"]),
            retirement_candidates=len(transitions["retirement_candidates"]), stale_brands=len(stale_brands),
        )
    return ok


async def run_curate(pool, bot_token: str, chat_id: str, logger, now: datetime | None = None) -> dict:
    await recompute_source_metrics(pool, now)
    transitions = await apply_transitions(pool, now)
    stale_brands = await find_stale_brands(pool, now)
    digest_sent = await send_curation_digest(pool, bot_token, chat_id, transitions, stale_brands, logger)
    return {"transitions": transitions, "stale_brands": stale_brands, "digest_sent": digest_sent}
