"""tests/test_dedupe.py"""
import uuid
from datetime import date

from carwatch.dedupe import STAGE_ORDER, compute_dedupe_key, process_extracted_event, slug
from carwatch.models import ExtractedEvent


def test_slug_removes_accents_punctuation_and_collapses_spaces():
    assert slug("Seal 06 DM-i!") == "seal-06-dm-i"
    assert slug("Citroën C3") == "citroen-c3"


def test_compute_dedupe_key_sorts_markets_and_defaults_to_global():
    key = compute_dedupe_key("BYD", "Seal 06", ["US", "cn"], "world_premiere")
    assert key == "byd|seal-06|cn,us|world_premiere"
    assert compute_dedupe_key("BYD", "Seal 06", [], "world_premiere") == "byd|seal-06|global|world_premiere"


def test_stage_order_matches_spec_progression_order():
    assert STAGE_ORDER == [
        "spy", "teaser", "concept", "world_premiere",
        "specs_release", "pricing", "on_sale", "market_launch",
    ]


async def _make_extracted(**overrides) -> ExtractedEvent:
    defaults = dict(
        brand="BYD", model="Seal 06", generation=None, body_type="sedan",
        stage="world_premiere", markets=["CN"], event_date=date(2026, 1, 1),
        sales_start=None, powertrain=None, price=None,
        highlights=["Estreia mundial"], confidence=0.9,
    )
    defaults.update(overrides)
    return ExtractedEvent(**defaults)


async def _insert_source_and_item(db_pool, tier: int = 1):
    # uuid4 rather than id(object()) for the uniqueness suffix: two objects
    # created in quick succession can be garbage-collected and have their
    # memory address (and thus id()) reused by CPython, which intermittently
    # collided with the UNIQUE constraint on sources.feed_url under pytest.
    async with db_pool.connection() as conn:
        source = await conn.execute(
            "INSERT INTO sources (domain, feed_url, kind, tier, status) "
            "VALUES ('x.com', %s, 'rss', %s, 'active') RETURNING id",
            (f"https://x.com/feed-{tier}-{uuid.uuid4()}", tier),
        )
        source_id = (await source.fetchone())[0]
        item = await conn.execute(
            "INSERT INTO raw_items (source_id, url, url_hash, title) "
            "VALUES (%s, 'https://x.com/a', %s, 'title') RETURNING id",
            (source_id, f"hash-{uuid.uuid4()}"),
        )
        item_id = (await item.fetchone())[0]
    return source_id, item_id


async def test_first_occurrence_creates_new_standalone_event(db_pool):
    extracted = await _make_extracted()
    source_id, item_id = await _insert_source_and_item(db_pool)

    event_id = await process_extracted_event(
        db_pool, extracted, source_id=source_id, raw_item_id=item_id, source_tier=1
    )

    async with db_pool.connection() as conn:
        result = await conn.execute(
            "SELECT brand, model, stage, previous_event_id FROM launch_events WHERE id = %s",
            (event_id,),
        )
        row = await result.fetchone()
    assert row == ("BYD", "Seal 06", "world_premiere", None)


async def test_exact_duplicate_merges_instead_of_creating_new_row(db_pool):
    first = await _make_extracted()
    source_id_a, item_id_a = await _insert_source_and_item(db_pool)
    first_id = await process_extracted_event(
        db_pool, first, source_id=source_id_a, raw_item_id=item_id_a, source_tier=3
    )

    second = await _make_extracted(price={"amount": 109800, "currency": "CNY", "status": "official"})
    source_id_b, item_id_b = await _insert_source_and_item(db_pool)
    second_id = await process_extracted_event(
        db_pool, second, source_id=source_id_b, raw_item_id=item_id_b, source_tier=3
    )

    assert second_id == first_id
    async with db_pool.connection() as conn:
        result = await conn.execute("SELECT count(*) FROM launch_events")
        assert (await result.fetchone())[0] == 1
        result = await conn.execute("SELECT count(*) FROM event_sources WHERE event_id = %s", (first_id,))
        assert (await result.fetchone())[0] == 2
        result = await conn.execute("SELECT price FROM launch_events WHERE id = %s", (first_id,))
        assert (await result.fetchone())[0]["amount"] == 109800  # null field enriched


async def test_sibling_models_do_not_collapse(db_pool):
    seal_05 = await _make_extracted(model="Seal 05")
    source_id_a, item_id_a = await _insert_source_and_item(db_pool)
    id_a = await process_extracted_event(
        db_pool, seal_05, source_id=source_id_a, raw_item_id=item_id_a, source_tier=1
    )

    seal_06 = await _make_extracted(model="Seal 06")
    source_id_b, item_id_b = await _insert_source_and_item(db_pool)
    id_b = await process_extracted_event(
        db_pool, seal_06, source_id=source_id_b, raw_item_id=item_id_b, source_tier=1
    )

    assert id_a != id_b


async def test_tier1_source_overwrites_conflicting_fields_from_lower_tier(db_pool):
    first = await _make_extracted(body_type="sedan")
    source_id_a, item_id_a = await _insert_source_and_item(db_pool, tier=3)
    event_id = await process_extracted_event(
        db_pool, first, source_id=source_id_a, raw_item_id=item_id_a, source_tier=3
    )

    corrected = await _make_extracted(body_type="hatchback")
    source_id_b, item_id_b = await _insert_source_and_item(db_pool, tier=1)
    await process_extracted_event(
        db_pool, corrected, source_id=source_id_b, raw_item_id=item_id_b, source_tier=1
    )

    async with db_pool.connection() as conn:
        result = await conn.execute("SELECT body_type FROM launch_events WHERE id = %s", (event_id,))
        assert (await result.fetchone())[0] == "hatchback"
        result = await conn.execute(
            "SELECT is_primary FROM event_sources WHERE event_id = %s AND source_id = %s",
            (event_id, source_id_b),
        )
        assert (await result.fetchone())[0] is True


async def test_second_tier1_source_does_not_overwrite_existing_tier1_fields(db_pool):
    """Once a tier-1 source has already set the record, a *second* tier-1
    source's merge should fall into the COALESCE-only branch (not overwrite
    the already-tier1-sourced fields), and its event_sources row should not
    be marked is_primary (there's already a tier-1 primary source)."""
    first = await _make_extracted(body_type="sedan")
    source_id_a, item_id_a = await _insert_source_and_item(db_pool, tier=1)
    event_id = await process_extracted_event(
        db_pool, first, source_id=source_id_a, raw_item_id=item_id_a, source_tier=1
    )

    second = await _make_extracted(body_type="hatchback")
    source_id_b, item_id_b = await _insert_source_and_item(db_pool, tier=1)
    await process_extracted_event(
        db_pool, second, source_id=source_id_b, raw_item_id=item_id_b, source_tier=1
    )

    async with db_pool.connection() as conn:
        result = await conn.execute("SELECT body_type FROM launch_events WHERE id = %s", (event_id,))
        assert (await result.fetchone())[0] == "sedan"  # not overwritten
        result = await conn.execute(
            "SELECT is_primary FROM event_sources WHERE event_id = %s AND source_id = %s",
            (event_id, source_id_b),
        )
        assert (await result.fetchone())[0] is False


async def test_fuzzy_match_merges_naming_variation_of_same_model(db_pool):
    """"Seal 06 DM-i" and "Seal 06" have different dedupe_keys (no exact
    match) but clear both the trigram (>=0.55) and cosine (>=0.86) gates,
    and share the same distinguishing digit group ("06"), so they should be
    treated as the same underlying launch event."""
    first = await _make_extracted(model="Seal 06 DM-i")
    source_id_a, item_id_a = await _insert_source_and_item(db_pool)
    first_id = await process_extracted_event(
        db_pool, first, source_id=source_id_a, raw_item_id=item_id_a, source_tier=1
    )

    second = await _make_extracted(model="Seal 06")
    source_id_b, item_id_b = await _insert_source_and_item(db_pool)
    second_id = await process_extracted_event(
        db_pool, second, source_id=source_id_b, raw_item_id=item_id_b, source_tier=1
    )

    assert second_id == first_id
    async with db_pool.connection() as conn:
        result = await conn.execute("SELECT count(*) FROM launch_events")
        assert (await result.fetchone())[0] == 1


async def test_spy_stage_has_no_earlier_stage_to_link_to(db_pool):
    """"spy" is STAGE_ORDER[0]; there is no earlier stage to look up, so
    the earlier-stage-event lookup must short-circuit without matching
    anything, producing a standalone event with previous_event_id = NULL."""
    spy = await _make_extracted(stage="spy")
    source_id, item_id = await _insert_source_and_item(db_pool)

    event_id = await process_extracted_event(
        db_pool, spy, source_id=source_id, raw_item_id=item_id, source_tier=1
    )

    async with db_pool.connection() as conn:
        result = await conn.execute(
            "SELECT previous_event_id FROM launch_events WHERE id = %s", (event_id,)
        )
        assert (await result.fetchone())[0] is None


async def test_stage_progression_creates_new_linked_event(db_pool):
    teaser = await _make_extracted(stage="teaser")
    source_id_a, item_id_a = await _insert_source_and_item(db_pool)
    teaser_id = await process_extracted_event(
        db_pool, teaser, source_id=source_id_a, raw_item_id=item_id_a, source_tier=1
    )

    premiere = await _make_extracted(stage="world_premiere")
    source_id_b, item_id_b = await _insert_source_and_item(db_pool)
    premiere_id = await process_extracted_event(
        db_pool, premiere, source_id=source_id_b, raw_item_id=item_id_b, source_tier=1
    )

    assert premiere_id != teaser_id
    async with db_pool.connection() as conn:
        result = await conn.execute(
            "SELECT previous_event_id FROM launch_events WHERE id = %s", (premiere_id,)
        )
        assert (await result.fetchone())[0] == teaser_id
