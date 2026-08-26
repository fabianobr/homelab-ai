"""src/carwatch/review.py"""
DECISION_MAP = {"c": "confirmed", "r": "rejected"}


async def get_events_for_review(pool, limit: int = 15) -> list[dict]:
    async with pool.connection() as conn:
        result = await conn.execute(
            "SELECT le.id, le.brand, le.model, le.stage, "
            "(SELECT ri.url FROM event_sources es JOIN raw_items ri ON ri.id = es.item_id "
            " WHERE es.event_id = le.id ORDER BY es.is_primary DESC LIMIT 1) AS primary_url "
            "FROM launch_events le WHERE le.review_status = 'pending' "
            "ORDER BY le.first_seen_at DESC LIMIT %s",
            (limit,),
        )
        rows = await result.fetchall()
    return [{"id": r[0], "brand": r[1], "model": r[2], "stage": r[3], "primary_url": r[4]} for r in rows]


async def set_review_status(pool, event_id: int, status: str) -> None:
    async with pool.connection() as conn:
        await conn.execute("UPDATE launch_events SET review_status = %s WHERE id = %s", (status, event_id))


async def run_review(pool, limit: int, input_fn, print_fn) -> dict:
    events = await get_events_for_review(pool, limit)
    counts = {"confirmed": 0, "rejected": 0, "skipped": 0}

    for event in events:
        print_fn(f"{event['brand']} {event['model']} ({event['stage']}) — {event['primary_url']}")
        while True:
            answer = input_fn("[c]onfirmar / [r]ejeitar / [s]kip: ").strip().lower()
            if answer in DECISION_MAP or answer == "s":
                break
            print_fn("Resposta inválida, use c/r/s.")

        if answer == "s":
            counts["skipped"] += 1
            continue
        await set_review_status(pool, event["id"], DECISION_MAP[answer])
        counts["confirmed" if answer == "c" else "rejected"] += 1

    return counts
