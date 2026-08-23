"""src/carwatch/publishers/atom.py"""
from datetime import timezone
from pathlib import Path
from xml.sax.saxutils import escape

ATOM_NS = "http://www.w3.org/2005/Atom"


async def get_recent_events_for_feed(pool, limit: int = 100) -> list[dict]:
    async with pool.connection() as conn:
        result = await conn.execute(
            "SELECT le.id, le.brand, le.model, le.stage, le.highlights, le.updated_at, "
            "(SELECT ri.url FROM event_sources es JOIN raw_items ri ON ri.id = es.item_id "
            " WHERE es.event_id = le.id ORDER BY es.is_primary DESC, es.seen_at ASC LIMIT 1) AS primary_url "
            "FROM launch_events le WHERE le.published = TRUE "
            "ORDER BY le.updated_at DESC LIMIT %s",
            (limit,),
        )
        rows = await result.fetchall()
    return [
        {"id": r[0], "brand": r[1], "model": r[2], "stage": r[3], "highlights": r[4],
         "updated_at": r[5], "primary_url": r[6]}
        for r in rows
    ]


def _rfc3339(dt) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def render_atom_feed(events: list[dict], feed_self_url: str) -> str:
    from datetime import datetime

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    entries = []
    for event in events:
        summary = " ".join(event.get("highlights") or [])
        link = event.get("primary_url") or feed_self_url
        title = f"{event['brand']} {event['model']} — {event['stage']}"
        entries.append(
            "  <entry>\n"
            f"    <id>urn:carwatch:event:{event['id']}</id>\n"
            f"    <title>{escape(title)}</title>\n"
            f"    <updated>{_rfc3339(event['updated_at'])}</updated>\n"
            f"    <link href=\"{escape(link)}\"/>\n"
            f"    <summary>{escape(summary)}</summary>\n"
            "  </entry>\n"
        )

    return (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        f'<feed xmlns="{ATOM_NS}">\n'
        "  <title>CarWatch — Lançamentos Automotivos</title>\n"
        "  <id>urn:carwatch:feed</id>\n"
        f"  <updated>{now}</updated>\n"
        f'  <link rel="self" href="{escape(feed_self_url)}"/>\n'
        + "".join(entries)
        + "</feed>\n"
    )


async def write_atom_feed(pool, output_path: Path, feed_self_url: str, limit: int = 100) -> int:
    events = await get_recent_events_for_feed(pool, limit)
    content = render_atom_feed(events, feed_self_url)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(content, encoding="utf-8")
    return len(events)
