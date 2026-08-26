"""tests/test_e2e_fase2.py"""
from pathlib import Path

from carwatch.dedupe import process_extracted_event
from carwatch.llm.extract import extract_article_text
from carwatch.models import ExtractedEvent

FIXTURES = Path(__file__).parent / "fixtures" / "articles"


def test_extract_article_text_handles_chinese_japanese_and_portuguese():
    for filename, expected_fragment in (
        ("article_zh.html", "比亚迪"),
        ("article_ja.html", "BYD"),
        ("article_pt.html", "Shenzhen"),
    ):
        html = (FIXTURES / filename).read_text(encoding="utf-8")
        text = extract_article_text(html)
        assert expected_fragment in text


async def _insert_source_and_item(db_pool, url: str):
    async with db_pool.connection() as conn:
        source = await conn.execute(
            "INSERT INTO sources (domain, feed_url, kind, tier, status) "
            "VALUES ('x.com', %s, 'rss', 3, 'active') RETURNING id",
            (f"{url}-feed",),
        )
        source_id = (await source.fetchone())[0]
        item = await conn.execute(
            "INSERT INTO raw_items (source_id, url, url_hash, title) "
            "VALUES (%s, %s, %s, 'title') RETURNING id",
            (source_id, url, url),
        )
        item_id = (await item.fetchone())[0]
    return source_id, item_id


async def test_eight_articles_about_same_launch_collapse_into_one_event(db_pool):
    event_id = None
    for i in range(8):
        source_id, item_id = await _insert_source_and_item(db_pool, f"https://x.com/article-{i}")
        extracted = ExtractedEvent(
            brand="BYD", model="Seal 06", generation=None, body_type="sedan",
            stage="world_premiere", markets=["CN"], event_date=None, sales_start=None,
            powertrain=None, price=None, highlights=[f"Cobertura {i}"], confidence=0.9,
        )
        result_id = await process_extracted_event(
            db_pool, extracted, source_id=source_id, raw_item_id=item_id, source_tier=3
        )
        if event_id is None:
            event_id = result_id
        assert result_id == event_id  # every one of the 8 collapses onto the first

    async with db_pool.connection() as conn:
        result = await conn.execute("SELECT count(*) FROM launch_events")
        assert (await result.fetchone())[0] == 1
        result = await conn.execute(
            "SELECT count(*) FROM event_sources WHERE event_id = %s", (event_id,)
        )
        assert (await result.fetchone())[0] == 8
