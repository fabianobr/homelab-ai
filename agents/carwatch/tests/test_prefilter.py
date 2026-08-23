"""tests/test_prefilter.py"""
from carwatch.models import BrandsConfig, KeywordsConfig
from carwatch.prefilter import passes_prefilter, run_prefilter

BRANDS = BrandsConfig.model_validate(
    {
        "brands": [
            {"name": "Volkswagen", "aliases": ["VW"]},
            {"name": "BYD", "aliases": ["比亚迪"]},
        ]
    }
)
KEYWORDS = KeywordsConfig.model_validate(
    {
        "positive": {
            "en": ["unveils", "world premiere"],
            "pt": ["lançamento", "revela"],
            "zh": ["首发", "上市"],
        },
        "negative_strong": ["recall", "quarterly results"],
    }
)


def test_passes_with_brand_and_positive_term_in_english():
    passes, brand = passes_prefilter("VW unveils new Golf", None, BRANDS, KEYWORDS)
    assert passes is True
    assert brand == "Volkswagen"


def test_passes_with_brand_and_positive_term_in_portuguese():
    passes, brand = passes_prefilter("Volkswagen revela novo modelo", None, BRANDS, KEYWORDS)
    assert passes is True


def test_passes_with_chinese_brand_and_term():
    passes, brand = passes_prefilter("比亚迪海豹06首发", None, BRANDS, KEYWORDS)
    assert passes is True
    assert brand == "BYD"


def test_fails_without_known_brand():
    passes, brand = passes_prefilter("Some startup unveils new gadget", None, BRANDS, KEYWORDS)
    assert passes is False
    assert brand is None


def test_fails_without_positive_term():
    passes, brand = passes_prefilter("Volkswagen reports quarterly deliveries", None, BRANDS, KEYWORDS)
    assert passes is False


def test_fails_on_negative_strong_term_even_with_positive_term():
    passes, _ = passes_prefilter(
        "VW unveils recall for 50000 vehicles", None, BRANDS, KEYWORDS
    )
    assert passes is False


def test_checks_summary_as_well_as_title():
    passes, _ = passes_prefilter("VW news", "the brand unveils a new Golf today", BRANDS, KEYWORDS)
    assert passes is True


# Mirrors the real config/brands.yaml + config/keywords.yaml entries that the
# Fase 1 final review found colliding with naive substring matching.
REAL_WORLD_BRANDS = BrandsConfig.model_validate(
    {
        "brands": [
            {"name": "General Motors", "aliases": ["GM", "Chevrolet", "Chevy"]},
            {"name": "Stellantis", "aliases": ["Jeep", "Ram", "Dodge"]},
            {"name": "Volkswagen", "aliases": ["VW"]},
        ]
    }
)
REAL_WORLD_KEYWORDS = KeywordsConfig.model_validate(
    {
        "positive": {"en": ["unveils", "world premiere", "goes on sale"]},
        "negative_strong": ["stock price", "stock plunges", "shares fall", "recall"],
    }
)


def test_gm_alias_does_not_match_inside_segment():
    """IMPORTANT 6: `"gm" in "segment"` used to make every article about a
    market segment look like a General Motors article."""
    passes, brand = passes_prefilter(
        "Analysts say the compact SUV segment unveils strong growth",
        None,
        REAL_WORLD_BRANDS,
        REAL_WORLD_KEYWORDS,
    )
    assert brand is None
    assert passes is False


def test_ram_alias_does_not_match_inside_program_or_framework():
    passes, brand = passes_prefilter(
        "New safety program and regulatory framework unveils in Europe",
        None,
        REAL_WORLD_BRANDS,
        REAL_WORLD_KEYWORDS,
    )
    assert brand is None
    assert passes is False


def test_real_gm_and_ram_mentions_still_match_on_a_word_boundary():
    _passes, brand = passes_prefilter("GM unveils new Chevy Bolt", None, REAL_WORLD_BRANDS, REAL_WORLD_KEYWORDS)
    assert brand == "General Motors"
    _passes, brand = passes_prefilter("Ram unveils new 1500 pickup", None, REAL_WORLD_BRANDS, REAL_WORLD_KEYWORDS)
    assert brand == "Stellantis"


def test_ram_alias_does_not_match_inside_accented_spanish_portuguese_name():
    """Accented Latin letters (é, ó, ã, ñ, ç — common in this project's pt/es
    sources) must still count as word characters, the way plain `\\b` treated
    them, so "Ram" must not match inside the name "Ramón"."""
    passes, brand = passes_prefilter(
        "Ramón García unveils new safety report", None, REAL_WORLD_BRANDS, REAL_WORLD_KEYWORDS
    )
    assert brand is None
    assert passes is False


def test_in_stock_does_not_trigger_the_financial_negative_terms():
    """IMPORTANT 6: the bare `stock` negative term vetoed legitimate on-sale
    announcements ("now in stock nationwide")."""
    passes, brand = passes_prefilter(
        "VW Golf goes on sale, now in stock nationwide",
        None,
        REAL_WORLD_BRANDS,
        REAL_WORLD_KEYWORDS,
    )
    assert brand == "Volkswagen"
    assert passes is True


def test_financial_market_news_is_still_vetoed():
    for title in (
        "VW unveils plan as stock plunges after profit warning",
        "VW unveils plan as shares fall 8%",
        "VW unveils plan; stock price hits a 5-year low",
    ):
        passes, _ = passes_prefilter(title, None, REAL_WORLD_BRANDS, REAL_WORLD_KEYWORDS)
        assert passes is False, title


def test_positive_term_is_word_bounded_too():
    """`unveils` must not match inside an unrelated longer token."""
    passes, brand = passes_prefilter(
        "Volkswagen reunveilsomething odd", None, REAL_WORLD_BRANDS, REAL_WORLD_KEYWORDS
    )
    assert brand == "Volkswagen"
    assert passes is False


def test_latin_brand_glued_to_cjk_text_still_matches():
    """Python's `\\b` is defined in terms of `\\w`, and CJK ideographs count
    as word characters too — so a naive `\\bBYD\\b` finds no boundary between
    "D" and an immediately adjacent "海" and fails to match "BYD海豹06首发".
    A Latin brand name/alias glued directly to CJK text (no space) must
    still be found."""
    brands = BrandsConfig.model_validate({"brands": [{"name": "BYD", "aliases": []}]})
    passes, brand = passes_prefilter("BYD海豹06首发", None, brands, KEYWORDS)
    assert brand == "BYD"
    assert passes is True


def test_cjk_terms_keep_substring_matching():
    """Python's \\b assumes whitespace-delimited words, which CJK text has
    none of — 比亚迪/首发 must keep plain containment."""
    passes, brand = passes_prefilter("比亚迪海豹06首发", None, BRANDS, KEYWORDS)
    assert passes is True
    assert brand == "BYD"


def test_hyphenated_and_multiword_terms_still_match():
    keywords = KeywordsConfig.model_validate(
        {"positive": {"en": ["all-new", "world premiere"]}, "negative_strong": []}
    )
    assert passes_prefilter("VW shows the all-new Golf", None, REAL_WORLD_BRANDS, keywords)[0] is True
    assert passes_prefilter("VW holds a world premiere", None, REAL_WORLD_BRANDS, keywords)[0] is True


async def test_run_prefilter_updates_rows_and_returns_counts(db_pool):
    async with db_pool.connection() as conn:
        source = await conn.execute(
            "INSERT INTO sources (domain, feed_url, kind, tier, status) "
            "VALUES ('example.com', 'https://example.com/feed', 'rss', 1, 'active') RETURNING id"
        )
        source_id = (await source.fetchone())[0]
        await conn.execute(
            "INSERT INTO raw_items (source_id, url, url_hash, title, summary, status) VALUES "
            "(%s, 'https://example.com/a', 'hash-a', 'VW unveils new Golf', NULL, 'new'), "
            "(%s, 'https://example.com/b', 'hash-b', 'Random unrelated news', NULL, 'new')",
            (source_id, source_id),
        )

    stats = await run_prefilter(db_pool, BRANDS, KEYWORDS, logger=None)

    assert stats == {"in": 2, "out": 1, "pass_rate": 50.0}
    async with db_pool.connection() as conn:
        result = await conn.execute(
            "SELECT title, prefilter_ok, status FROM raw_items ORDER BY id"
        )
        rows = await result.fetchall()
    assert rows[0][1] is True and rows[0][2] == "new"
    assert rows[1][1] is False and rows[1][2] == "filtered"
