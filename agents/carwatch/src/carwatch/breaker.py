"""src/carwatch/breaker.py"""
from datetime import datetime, timedelta, timezone

import structlog

logger = structlog.get_logger()

# Statuses that mean "stop fetching this source". 'blocked' is terminal;
# 'broken'/'retired' are handled by the callers' source selection, while an
# unexpired blocked_until is a temporary pause that applies to any status.
_TERMINAL_STATUSES = ("blocked",)


async def is_source_paused(pool, source_id: int, now: datetime | None = None) -> bool:
    """True when the circuit breaker says this source must not be fetched.

    Reading breaker state back before a request is what turns the recorded
    state into actual enforcement — ingest.py's source-selection SQL used to
    be the only place honouring it, so probe.py/discovery_seed.py kept
    hammering sources the breaker had already given up on.
    """
    now = now or datetime.now(timezone.utc)
    async with pool.connection() as conn:
        result = await conn.execute(
            "SELECT status, blocked_until FROM sources WHERE id = %s", (source_id,)
        )
        row = await result.fetchone()
    if row is None:
        return False
    status, blocked_until = row
    if status in _TERMINAL_STATUSES:
        return True
    return blocked_until is not None and blocked_until > now


def _log_trip(source_id: int, previous_status: str, new_status: str, reason: str) -> None:
    """SPEC.md §18's `breaker.trip` event — only on an actual transition."""
    if new_status == previous_status:
        return
    if new_status not in ("probation", "blocked", "broken"):
        return
    logger.warning(
        "breaker.trip",
        source_id=source_id,
        previous_status=previous_status,
        status=new_status,
        reason=reason,
    )


async def record_fetch_result(
    pool, source_id: int, *, status: int, blocked: bool, now: datetime | None = None
) -> str:
    now = now or datetime.now(timezone.utc)
    is_failure = status >= 500 or status == 0
    is_pause_signal = blocked or status in (403, 429)

    async with pool.connection() as conn:
        result = await conn.execute(
            "SELECT status, consecutive_failures FROM sources WHERE id = %s FOR UPDATE",
            (source_id,),
        )
        row = await result.fetchone()
        current_status, consecutive_failures = row[0], row[1]

        if is_pause_signal:
            await conn.execute(
                "INSERT INTO source_incidents (source_id, kind, occurred_at) VALUES (%s, %s, %s)",
                (source_id, "block" if current_status == "probation" else "pause", now),
            )
            if current_status == "probation":
                new_status = "blocked"
                await conn.execute(
                    "UPDATE sources SET status = %s, blocked_until = NULL WHERE id = %s",
                    (new_status, source_id),
                )
                _log_trip(source_id, current_status, new_status, "block_signal_on_probation")
                return new_status

            recent_pauses = await conn.execute(
                "SELECT count(*) FROM source_incidents "
                "WHERE source_id = %s AND kind = 'pause' AND occurred_at > %s",
                (source_id, now - timedelta(days=7)),
            )
            pause_count = (await recent_pauses.fetchone())[0]

            new_status = "probation" if pause_count >= 2 else current_status
            blocked_until = now + timedelta(hours=24)
            await conn.execute(
                "UPDATE sources SET status = %s, blocked_until = %s, consecutive_failures = 0 "
                "WHERE id = %s",
                (new_status, blocked_until, source_id),
            )
            _log_trip(source_id, current_status, new_status, "repeated_pause_signals")
            return new_status

        if is_failure:
            consecutive_failures += 1
            new_status = "broken" if consecutive_failures >= 3 else current_status
            await conn.execute(
                "UPDATE sources SET status = %s, consecutive_failures = %s WHERE id = %s",
                (new_status, consecutive_failures, source_id),
            )
            _log_trip(source_id, current_status, new_status, "consecutive_failures")
            return new_status

        # success
        await conn.execute(
            "UPDATE sources SET consecutive_failures = 0, last_ok_at = %s WHERE id = %s",
            (now, source_id),
        )
        return current_status


async def check_stale_sources(pool, *, max_days: int = 21, now: datetime | None = None) -> list[int]:
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(days=max_days)
    async with pool.connection() as conn:
        result = await conn.execute(
            "SELECT id FROM sources "
            "WHERE status IN ('active', 'probation') "
            "AND (last_item_at IS NULL OR last_item_at < %s)",
            (cutoff,),
        )
        return [row[0] for row in await result.fetchall()]
