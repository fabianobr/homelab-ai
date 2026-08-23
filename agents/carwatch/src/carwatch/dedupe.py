"""src/carwatch/dedupe.py

Two-stage match/merge/progression engine (SPEC.md §12).

process_extracted_event() is the single entrypoint extract.py (Task 5) calls
per successfully extracted item:

1. Exact `dedupe_key` match within 14 days -> merge (Etapa 3).
2. No exact match -> fuzzy match (same brand + stage, trigram similarity(model)
   >= 0.55 AND cosine similarity >= 0.86, 14-day window) -> merge (Etapa 3).
   Both thresholds are required together: either alone produces false
   positives between sibling models (e.g. "Seal 05" vs "Seal 06").
   A third gate, not in SPEC.md, is also required: the incoming and
   candidate model strings' digit-groups must match exactly (see
   `_digit_signature`). Verified against the real embedding model that
   SPEC.md's own two thresholds both pass for "Seal 05" vs "Seal 06" (and
   for the digit-vs-no-digit case "Model 3" vs "Model Y"), so this guard is
   load-bearing, not decorative.
3. No match at either stage-preserving check -> look for a prior event with
   the same brand + model_slug but an earlier stage in STAGE_ORDER (no time
   window) -> stage progression: create a NEW row with previous_event_id set
   (Etapa 4).
4. Nothing matches at all -> create a new standalone event.

Deviation from SPEC.md, noted explicitly: `previous_event_id` (added to the
schema in Task 1) is what "vincula ao anterior" (§12 Etapa 4) is stored in;
SPEC.md's own launch_events table in §5.4 has no such column.
"""
import re
import unicodedata

from carwatch.embeddings import embed_text
from carwatch.models import ExtractedEvent

# SPEC.md §12 Etapa 4 progression order -- NOT the DB enum's declaration
# order (migrations/004_events.sql lists `concept` last; that's just enum
# member order and irrelevant to progression comparisons).
STAGE_ORDER = [
    "spy", "teaser", "concept", "world_premiere",
    "specs_release", "pricing", "on_sale", "market_launch",
]
EXACT_MATCH_WINDOW_DAYS = 14
FUZZY_MATCH_WINDOW_DAYS = 14
TRIGRAM_THRESHOLD = 0.55
COSINE_THRESHOLD = 0.86


def slug(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text)
    without_accents = "".join(c for c in normalized if not unicodedata.combining(c))
    lowered = without_accents.lower()
    cleaned = re.sub(r"[^a-z0-9\s-]", "", lowered)
    return re.sub(r"[\s-]+", "-", cleaned).strip("-")


def compute_dedupe_key(brand: str, model: str, markets: list[str], stage: str) -> str:
    market_part = ",".join(sorted(m.lower() for m in markets)) if markets else "global"
    return f"{slug(brand)}|{slug(model)}|{market_part}|{stage}"


def _embedding_text(extracted: ExtractedEvent) -> str:
    return f"{extracted.brand} {extracted.model} {extracted.generation or ''} {' '.join(extracted.highlights)}"


async def _find_exact_match(pool, dedupe_key: str) -> int | None:
    async with pool.connection() as conn:
        result = await conn.execute(
            "SELECT id FROM launch_events WHERE dedupe_key = %s "
            "AND first_seen_at > now() - make_interval(days => %s) "
            "ORDER BY first_seen_at DESC LIMIT 1",
            (dedupe_key, EXACT_MATCH_WINDOW_DAYS),
        )
        row = await result.fetchone()
        return row[0] if row else None


def _digit_signature(text: str) -> tuple[str, ...]:
    """The ordered digit-groups in a model name (e.g. "Seal 05" -> ("05",)).

    Trigram similarity and this project's multilingual sentence embeddings
    both fail to discriminate short automotive model codes that differ only
    in a trailing number: empirically, similarity('Seal 05', 'Seal 06') via
    pg_trgm is 0.6 (above the 0.55 gate) and their cosine similarity under
    `_embedding_text` is ~0.95-0.97 (above the 0.86 gate, and *worse* with
    the real ExtractedEvent default `highlights=[]`) -- both SPEC.md §12
    thresholds pass for a pair SPEC.md itself names as the canonical
    sibling-model false positive. Numbers are highly discriminating in car
    naming (Seal 05 and Seal 06 are different products), so a fuzzy
    candidate whose digit groups differ from the incoming event's is
    rejected even if it clears both similarity gates.

    The empty tuple `()` (no digits at all, e.g. "Model Y") is itself a
    valid signature and must be compared like any other -- not treated as a
    wildcard. An earlier version of this guard only compared signatures
    when *both* sides had at least one digit group, which let "Model 3" and
    "Model Y" (trgm 0.6, cosine ~0.90, one side digit-less) merge into one
    launch event. Comparing unconditionally catches that: ("3",) != ().
    """
    return tuple(re.findall(r"\d+", text))


async def _find_fuzzy_match(pool, brand: str, model: str, stage: str, embedding: list[float]) -> int | None:
    incoming_digits = _digit_signature(model)
    async with pool.connection() as conn:
        result = await conn.execute(
            "SELECT id, model FROM launch_events "
            "WHERE brand = %s AND stage = %s "
            "AND first_seen_at > now() - make_interval(days => %s) "
            "AND similarity(model, %s) >= %s "
            "AND 1 - (embedding <=> %s::vector) >= %s "
            "ORDER BY first_seen_at DESC",
            (brand, stage, FUZZY_MATCH_WINDOW_DAYS, model, TRIGRAM_THRESHOLD, embedding, COSINE_THRESHOLD),
        )
        rows = await result.fetchall()
    for candidate_id, candidate_model in rows:
        candidate_digits = _digit_signature(candidate_model)
        if incoming_digits != candidate_digits:
            continue
        return candidate_id
    return None


async def _find_earlier_stage_event(pool, brand: str, model_slug: str, stage: str) -> int | None:
    incoming_rank = STAGE_ORDER.index(stage)
    earlier_stages = STAGE_ORDER[:incoming_rank]
    if not earlier_stages:
        return None
    async with pool.connection() as conn:
        result = await conn.execute(
            "SELECT id FROM launch_events "
            "WHERE brand = %s AND model_slug = %s AND stage = ANY(%s) "
            "ORDER BY first_seen_at DESC LIMIT 1",
            (brand, model_slug, earlier_stages),
        )
        row = await result.fetchone()
        return row[0] if row else None


async def _insert_event_source(pool, event_id: int, item_id: int, source_id: int, is_primary: bool) -> None:
    async with pool.connection() as conn:
        await conn.execute(
            "INSERT INTO event_sources (event_id, item_id, source_id, is_primary) "
            "VALUES (%s, %s, %s, %s) ON CONFLICT DO NOTHING",
            (event_id, item_id, source_id, is_primary),
        )


async def _create_new_event(
    pool, extracted: ExtractedEvent, *, source_id: int, raw_item_id: int, previous_event_id: int | None
) -> int:
    embedding = embed_text(_embedding_text(extracted))
    dedupe_key = compute_dedupe_key(extracted.brand, extracted.model, extracted.markets, extracted.stage.value)
    async with pool.connection() as conn:
        result = await conn.execute(
            "INSERT INTO launch_events "
            "(dedupe_key, brand, model, model_slug, generation, body_type, stage, "
            "is_new_generation, markets, global_debut, event_date, sales_start, "
            "powertrain, price, highlights, embedding, confidence, previous_event_id) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
            "RETURNING id",
            (
                dedupe_key, extracted.brand, extracted.model, slug(extracted.model),
                extracted.generation, extracted.body_type, extracted.stage.value,
                extracted.is_new_generation, extracted.markets, extracted.global_debut,
                extracted.event_date, extracted.sales_start,
                extracted.powertrain.model_dump_json() if extracted.powertrain else None,
                extracted.price.model_dump_json() if extracted.price else None,
                extracted.highlights, embedding, extracted.confidence, previous_event_id,
            ),
        )
        event_id = (await result.fetchone())[0]
    await _insert_event_source(pool, event_id, raw_item_id, source_id, is_primary=True)
    return event_id


async def _merge_into_existing(
    pool, event_id: int, extracted: ExtractedEvent, *, source_id: int, raw_item_id: int, source_tier: int
) -> None:
    async with pool.connection() as conn:
        had_tier1_source = await conn.execute(
            "SELECT EXISTS (SELECT 1 FROM event_sources es JOIN sources s ON s.id = es.source_id "
            "WHERE es.event_id = %s AND s.tier = 1)",
            (event_id,),
        )
        already_has_tier1 = (await had_tier1_source.fetchone())[0]

        is_primary = source_tier == 1 and not already_has_tier1

        if is_primary:
            # SPEC.md §12 Etapa 3: a tier-1 source overwrites *conflicting*
            # fields. A field the new source didn't extract (None on the
            # incoming ExtractedEvent) is an absence, not a conflict -- it
            # must not wipe out a value a previous (lower-tier) source
            # already supplied. COALESCE(new, old) here means "new value
            # wins when present, old value survives when the tier-1 source
            # is simply silent on that field" -- same pattern as the
            # non-primary branch below, just also applied when is_primary.
            await conn.execute(
                "UPDATE launch_events SET "
                "body_type = COALESCE(%s, body_type), generation = COALESCE(%s, generation), "
                "is_new_generation = %s, "
                "event_date = COALESCE(%s, event_date), sales_start = COALESCE(%s, sales_start), "
                "powertrain = COALESCE(%s, powertrain), price = COALESCE(%s, price), "
                "updated_at = now() WHERE id = %s",
                (
                    extracted.body_type, extracted.generation, extracted.is_new_generation,
                    extracted.event_date, extracted.sales_start,
                    extracted.powertrain.model_dump_json() if extracted.powertrain else None,
                    extracted.price.model_dump_json() if extracted.price else None,
                    event_id,
                ),
            )
        else:
            await conn.execute(
                "UPDATE launch_events SET "
                "body_type = COALESCE(body_type, %s), generation = COALESCE(generation, %s), "
                "event_date = COALESCE(event_date, %s), sales_start = COALESCE(sales_start, %s), "
                "powertrain = COALESCE(powertrain, %s), price = COALESCE(price, %s), "
                "updated_at = now() WHERE id = %s",
                (
                    extracted.body_type, extracted.generation,
                    extracted.event_date, extracted.sales_start,
                    extracted.powertrain.model_dump_json() if extracted.powertrain else None,
                    extracted.price.model_dump_json() if extracted.price else None,
                    event_id,
                ),
            )

    await _insert_event_source(pool, event_id, raw_item_id, source_id, is_primary=is_primary)


async def process_extracted_event(
    pool, extracted: ExtractedEvent, *, source_id: int, raw_item_id: int, source_tier: int
) -> int:
    dedupe_key = compute_dedupe_key(extracted.brand, extracted.model, extracted.markets, extracted.stage.value)

    exact_match = await _find_exact_match(pool, dedupe_key)
    if exact_match is not None:
        await _merge_into_existing(
            pool, exact_match, extracted, source_id=source_id, raw_item_id=raw_item_id, source_tier=source_tier
        )
        return exact_match

    embedding = embed_text(_embedding_text(extracted))
    fuzzy_match = await _find_fuzzy_match(pool, extracted.brand, extracted.model, extracted.stage.value, embedding)
    if fuzzy_match is not None:
        await _merge_into_existing(
            pool, fuzzy_match, extracted, source_id=source_id, raw_item_id=raw_item_id, source_tier=source_tier
        )
        return fuzzy_match

    previous_event_id = await _find_earlier_stage_event(
        pool, extracted.brand, slug(extracted.model), extracted.stage.value
    )
    return await _create_new_event(
        pool, extracted, source_id=source_id, raw_item_id=raw_item_id, previous_event_id=previous_event_id
    )
