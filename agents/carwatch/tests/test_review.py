"""tests/test_review.py"""
from carwatch.review import get_events_for_review, run_review, set_review_status


async def _insert_pending_event(db_pool, dedupe_key: str) -> int:
    async with db_pool.connection() as conn:
        result = await conn.execute(
            "INSERT INTO launch_events (dedupe_key, brand, model, model_slug, stage, "
            "highlights, confidence, review_status) VALUES "
            "(%s, 'BYD', 'Seal 06', 'seal-06', 'world_premiere', ARRAY['h'], 0.9, 'pending') RETURNING id",
            (dedupe_key,),
        )
        return (await result.fetchone())[0]


async def test_get_events_for_review_only_returns_pending(db_pool):
    pending_id = await _insert_pending_event(db_pool, "k1")
    async with db_pool.connection() as conn:
        await conn.execute(
            "INSERT INTO launch_events (dedupe_key, brand, model, model_slug, stage, "
            "highlights, confidence, review_status) VALUES "
            "('k2', 'BYD', 'Seal 07', 'seal-07', 'teaser', ARRAY['h'], 0.9, 'confirmed')"
        )

    events = await get_events_for_review(db_pool, limit=15)

    assert len(events) == 1
    assert events[0]["id"] == pending_id


async def test_run_review_records_confirm_reject_and_skip(db_pool):
    id_a = await _insert_pending_event(db_pool, "k1")
    id_b = await _insert_pending_event(db_pool, "k2")
    id_c = await _insert_pending_event(db_pool, "k3")

    answers = iter(["c", "r", "s"])
    printed = []
    counts = await run_review(
        db_pool, limit=15, input_fn=lambda _prompt: next(answers), print_fn=printed.append
    )

    assert counts == {"confirmed": 1, "rejected": 1, "skipped": 1}
    async with db_pool.connection() as conn:
        result = await conn.execute(
            "SELECT id, review_status FROM launch_events ORDER BY id"
        )
        rows = dict(await result.fetchall())
    assert rows[id_c] == "confirmed"  # newest-first ordering: id_c received first answer "c"
    assert rows[id_b] == "rejected"   # id_b received second answer "r"
    assert rows[id_a] == "pending"    # skip leaves it untouched; id_a received third answer "s"
    assert any("BYD" in line for line in printed)


async def test_run_review_reprompts_on_invalid_input(db_pool):
    await _insert_pending_event(db_pool, "k1")
    answers = iter(["x", "c"])
    printed = []

    counts = await run_review(
        db_pool, limit=15, input_fn=lambda _prompt: next(answers), print_fn=printed.append
    )

    assert counts == {"confirmed": 1, "rejected": 0, "skipped": 0}
    assert any("inválida" in line for line in printed)
