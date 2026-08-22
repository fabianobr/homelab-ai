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
