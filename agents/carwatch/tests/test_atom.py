"""tests/test_atom.py"""
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

from carwatch.publishers.atom import render_atom_feed

ATOM_NS = "{http://www.w3.org/2005/Atom}"


def test_render_atom_feed_produces_well_formed_xml_with_required_elements():
    events = [
        {
            "id": 1, "brand": "BYD", "model": "Seal 06", "stage": "world_premiere",
            "highlights": ["Estreia mundial em Shenzhen"],
            "updated_at": datetime(2026, 1, 15, 10, 0, tzinfo=timezone.utc),
            "primary_url": "https://x.com/a",
        }
    ]
    xml_text = render_atom_feed(events, feed_self_url="https://example.com/feed.atom")

    root = ET.fromstring(xml_text)
    assert root.tag == f"{ATOM_NS}feed"
    assert root.find(f"{ATOM_NS}id") is not None
    assert root.find(f"{ATOM_NS}title") is not None
    assert root.find(f"{ATOM_NS}updated") is not None
    entries = root.findall(f"{ATOM_NS}entry")
    assert len(entries) == 1
    entry = entries[0]
    assert entry.find(f"{ATOM_NS}id").text == "urn:carwatch:event:1"
    assert "BYD Seal 06" in entry.find(f"{ATOM_NS}title").text
    assert entry.find(f"{ATOM_NS}updated").text == "2026-01-15T10:00:00Z"
    assert entry.find(f"{ATOM_NS}link").get("href") == "https://x.com/a"


def test_render_atom_feed_escapes_special_characters_in_titles():
    events = [
        {
            "id": 2, "brand": "M&M Motors", "model": "X<Y>", "stage": "teaser",
            "highlights": [], "updated_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
            "primary_url": "https://x.com/b",
        }
    ]
    xml_text = render_atom_feed(events, feed_self_url="https://example.com/feed.atom")
    root = ET.fromstring(xml_text)  # raises if not well-formed
    assert "M&M Motors" in root.find(f"{ATOM_NS}entry/{ATOM_NS}title").text


def test_render_atom_feed_escapes_double_quote_in_href_attributes():
    """A URL containing a literal `"` (crafted or malformed, sourced from an
    external feed's <link> with zero validation) must not break out of the
    double-quoted href="..." attribute. xml.sax.saxutils.escape()'s default
    entity set does not cover `"`, so this used to inject a bogus extra
    attribute and corrupt the XML. Round-trip through ElementTree (not
    string-matching) to prove the quote survives escape+parse intact."""
    malicious_url = 'https://x.com/a" foo="bar'
    events = [
        {
            "id": 3, "brand": "BYD", "model": "Seal 06", "stage": "teaser",
            "highlights": [], "updated_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
            "primary_url": malicious_url,
        }
    ]
    xml_text = render_atom_feed(events, feed_self_url="https://example.com/feed.atom")

    root = ET.fromstring(xml_text)  # raises if the injected attribute broke well-formedness
    entry = root.findall(f"{ATOM_NS}entry")[0]
    assert entry.find(f"{ATOM_NS}link").get("href") == malicious_url
    assert entry.find(f"{ATOM_NS}link").get("foo") is None


def test_render_atom_feed_escapes_double_quote_in_feed_self_url():
    malicious_self_url = 'https://example.com/feed.atom" foo="bar'
    xml_text = render_atom_feed([], feed_self_url=malicious_self_url)

    root = ET.fromstring(xml_text)  # raises if the injected attribute broke well-formedness
    self_link = root.find(f"{ATOM_NS}link")
    assert self_link.get("href") == malicious_self_url
    assert self_link.get("foo") is None


def test_render_atom_feed_handles_zero_events():
    xml_text = render_atom_feed([], feed_self_url="https://example.com/feed.atom")
    root = ET.fromstring(xml_text)
    assert root.findall(f"{ATOM_NS}entry") == []


async def test_write_atom_feed_writes_file_and_returns_count(db_pool, tmp_path):
    async with db_pool.connection() as conn:
        await conn.execute(
            "INSERT INTO launch_events (dedupe_key, brand, model, model_slug, stage, "
            "highlights, confidence, published) VALUES "
            "('k1', 'BYD', 'Seal 06', 'seal-06', 'world_premiere', ARRAY['h'], 0.9, TRUE)"
        )
        await conn.execute(
            "INSERT INTO launch_events (dedupe_key, brand, model, model_slug, stage, "
            "highlights, confidence, published) VALUES "
            "('k2', 'BYD', 'Seal 07', 'seal-07', 'teaser', ARRAY['h'], 0.9, FALSE)"  # unpublished, excluded
        )

    from carwatch.publishers.atom import write_atom_feed

    out_path = tmp_path / "feed.atom"
    count = await write_atom_feed(db_pool, out_path, "https://example.com/feed.atom")

    assert count == 1
    assert out_path.exists()
    assert "Seal 06" in out_path.read_text()
    assert "Seal 07" not in out_path.read_text()
