"""src/carwatch/prefilter.py"""
import re
from functools import lru_cache

from carwatch.models import BrandsConfig, KeywordsConfig


@lru_cache(maxsize=8192)
def _word_boundary_pattern(term: str) -> re.Pattern:
    # Plain `\b` is defined in terms of `\w`, and Python's `\w` (Unicode mode)
    # treats CJK ideographs/kana as word characters too — so `\bBYD\b` finds
    # no boundary between "D" and an immediately adjacent "海" and fails to
    # match "BYD海豹06首发". A naive ASCII-only boundary class over-corrects
    # the other way: it would also treat accented Latin letters (é, ó, ã, ñ,
    # ç — common in this project's pt/es sources) as non-word, so "Ram" would
    # wrongly match inside "Ramón". The boundary class below adds the Latin-1
    # Supplement accented-letter ranges (À-ÖØ-öø-ÿ) so accented Latin still
    # counts as a word character — matching `\w`'s original behavior there —
    # while deliberately leaving CJK/kana (an entirely different Unicode
    # range) out of the class. This keeps the false-positive rejections
    # ("gm" inside "segment", "ram" inside "program"/"framework", "Ram"
    # inside "Ramón") while still matching when the term is glued directly
    # to CJK/kana text.
    return re.compile(
        rf"(?<![A-Za-zÀ-ÖØ-öø-ÿ0-9_]){re.escape(term)}(?![A-Za-zÀ-ÖØ-öø-ÿ0-9_])",
        re.IGNORECASE,
    )


def _term_in_text(term: str, text: str, text_lower: str) -> bool:
    """Match `term` in `text`, word-bounded for ASCII/Latin terms.

    Plain substring containment produced real false positives: the "GM" alias
    matched inside "segment", "Ram" matched inside "program"/"framework", and
    the negative term "shares" matched inside "shareable". Python's `\\b`
    assumes whitespace/punctuation-delimited words, which CJK text does not
    have — a `\\b` around 首发 would never match inside 比亚迪海豹06首发 — so
    any term with non-ASCII characters keeps substring containment.
    """
    if not term.isascii():
        return term.lower() in text_lower
    return _word_boundary_pattern(term).search(text) is not None


def _find_matching_brand(text: str, brands: BrandsConfig) -> str | None:
    text_lower = text.lower()
    for brand in brands.brands:
        for candidate in (brand.name, *brand.aliases):
            if _term_in_text(candidate, text, text_lower):
                return brand.name
    return None


def _matches_any(text: str, terms: list[str]) -> bool:
    text_lower = text.lower()
    return any(_term_in_text(term, text, text_lower) for term in terms)


def passes_prefilter(
    title: str, summary: str | None, brands: BrandsConfig, keywords: KeywordsConfig
) -> tuple[bool, str | None]:
    text = f"{title} {summary or ''}"

    brand = _find_matching_brand(text, brands)
    if brand is None:
        return False, None

    all_positive_terms = [term for terms in keywords.positive.values() for term in terms]
    if not _matches_any(text, all_positive_terms):
        return False, brand

    if _matches_any(text, keywords.negative_strong):
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
