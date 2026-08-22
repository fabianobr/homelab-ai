"""src/carwatch/prefilter.py"""
from carwatch.models import BrandsConfig, KeywordsConfig


def _find_matching_brand(text_lower: str, brands: BrandsConfig) -> str | None:
    for brand in brands.brands:
        candidates = [brand.name, *brand.aliases]
        if any(candidate.lower() in text_lower for candidate in candidates):
            return brand.name
    return None


def _matches_any(text_lower: str, terms: list[str]) -> bool:
    return any(term.lower() in text_lower for term in terms)


def passes_prefilter(
    title: str, summary: str | None, brands: BrandsConfig, keywords: KeywordsConfig
) -> tuple[bool, str | None]:
    text_lower = f"{title} {summary or ''}".lower()

    brand = _find_matching_brand(text_lower, brands)
    if brand is None:
        return False, None

    all_positive_terms = [term for terms in keywords.positive.values() for term in terms]
    if not _matches_any(text_lower, all_positive_terms):
        return False, brand

    if _matches_any(text_lower, keywords.negative_strong):
        return False, brand

    return True, brand


async def run_prefilter(pool, brands: BrandsConfig, keywords: KeywordsConfig, logger) -> dict:
    async with pool.connection() as conn:
        result = await conn.execute(
            "SELECT id, title, summary FROM raw_items WHERE status = 'new'"
        )
        rows = await result.fetchall()

        passed = 0
        for row_id, title, summary in rows:
            ok, _brand = passes_prefilter(title, summary, brands, keywords)
            if ok:
                passed += 1
                await conn.execute(
                    "UPDATE raw_items SET prefilter_ok = TRUE WHERE id = %s", (row_id,)
                )
            else:
                await conn.execute(
                    "UPDATE raw_items SET prefilter_ok = FALSE, status = 'filtered' WHERE id = %s",
                    (row_id,),
                )

    total = len(rows)
    pass_rate = round((passed / total * 100), 2) if total else 0.0
    stats = {"in": total, "out": passed, "pass_rate": pass_rate}
    if logger is not None:
        logger.info("prefilter.batch", **stats)
    return stats
