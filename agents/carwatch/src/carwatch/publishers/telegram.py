"""src/carwatch/publishers/telegram.py"""
import json

import httpx

TELEGRAM_API_BASE = "https://api.telegram.org"

# Telegram rejects messages over ~4096 characters. Chunk well under that
# limit rather than against it, to leave headroom for header/formatting
# variance across languages and future tweaks to per-item line length.
MESSAGE_BUDGET = 3500


async def send_telegram_message(bot_token: str, chat_id: str, text: str) -> bool:
    url = f"{TELEGRAM_API_BASE}/bot{bot_token}/sendMessage"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(url, json={"chat_id": chat_id, "text": text})
            response.raise_for_status()
            return True
    except httpx.HTTPError:
        return False


def _format_item_line(i: int, item: dict) -> str:
    brand = item.get("brand") or "?"
    model = item.get("model") or "?"
    stage = item.get("stage") or "?"
    confidence = item.get("confidence", 0.0)
    return f"{i}. {brand} {model} ({stage}) — confiança {confidence:.2f}\n   {item['url']}"


def format_smoke_summary(items: list[dict]) -> str:
    if not items:
        return "CarWatch — execução semanal\n\nNenhum lançamento novo detectado nesta execução."

    lines = [f"CarWatch — execução semanal", "", f"{len(items)} item(ns) classificado(s) como lançamento:", ""]
    for i, item in enumerate(items, 1):
        lines.append(_format_item_line(i, item))
    return "\n".join(lines)


def _format_chunk_summary(chunk: list[dict], part: int, total_parts: int, total_items: int) -> str:
    """Multi-message variant of format_smoke_summary, used only when the full
    approved-and-unnotified backlog doesn't fit a single Telegram message.
    Only ever called when total_parts > 1, so the common single-message case
    keeps using format_smoke_summary() unchanged."""
    lines = [
        f"CarWatch — execução semanal (parte {part}/{total_parts})",
        "",
        f"{total_items} item(ns) classificado(s) como lançamento nesta execução:",
        "",
    ]
    for i, item in enumerate(chunk, 1):
        lines.append(_format_item_line(i, item))
    return "\n".join(lines)


def _chunk_items_for_telegram(items: list[dict], budget: int = MESSAGE_BUDGET) -> list[list[dict]]:
    """Split approved-and-unnotified items into groups whose formatted text
    stays under `budget` characters.

    When the single-message rendering already fits, returns one chunk
    containing every item -- the caller must render that case with
    format_smoke_summary() so the common small-backlog path is unchanged
    from before this fix. Never splits a single item's line across chunks;
    a single item whose own line exceeds the budget still ends up alone in
    its own (oversized) chunk rather than being dropped.
    """
    if not items:
        return [[]]
    if len(format_smoke_summary(items)) <= budget:
        return [items]

    chunks: list[list[dict]] = []
    current: list[dict] = []
    for item in items:
        candidate = current + [item]
        # The exact header used to measure doesn't matter, only that growth
        # is measured consistently against the same budget the real
        # multi-part header will use.
        if current and len(_format_chunk_summary(candidate, 1, 1, len(items))) > budget:
            chunks.append(current)
            current = [item]
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks


async def get_approved_items_for_notification(pool) -> list[dict]:
    async with pool.connection() as conn:
        result = await conn.execute(
            "SELECT id, title, url, classified FROM raw_items "
            "WHERE status = 'new' AND classified IS NOT NULL "
            "AND classified->>'is_launch' = 'true'"
        )
        rows = await result.fetchall()

    items = []
    for item_id, title, url, classified in rows:
        data = classified if isinstance(classified, dict) else json.loads(classified)
        items.append(
            {
                "id": item_id,
                "title": title,
                "url": url,
                "brand": data.get("brand"),
                "model": data.get("model"),
                "stage": data.get("stage"),
                "confidence": data.get("confidence", 0.0),
            }
        )
    return items


async def mark_notified(pool, item_ids: list[int]) -> None:
    # 'notified' is a Fase 1-only status value, not listed among SPEC.md
    # §5.3's raw_items.status comment ('new'|'filtered'|'rejected'|
    # 'extracted'|'error'). This smoke publisher is a deliberate, temporary
    # stand-in (see DESIGN.md) that has no launch_events.published flag to
    # rely on yet — that proper mechanism arrives in Fase 2. Without marking
    # rows 'notified' here, every weekly-run would re-select and re-send the
    # same already-approved items forever, since nothing else advances their
    # status once classified.
    if not item_ids:
        return
    async with pool.connection() as conn:
        await conn.execute(
            "UPDATE raw_items SET status = 'notified' WHERE id = ANY(%s)",
            (item_ids,),
        )


async def run_publish_smoke(pool, bot_token: str, chat_id: str, logger) -> dict:
    """Send the weekly Telegram summary, chunking it across multiple
    messages when the backlog doesn't fit Telegram's ~4096-char limit.

    Contract: {"sent": <int, items actually marked notified>, "item_count":
    <int, total eligible items considered>}. A failed chunk's items are left
    at status='new' (retried next week) without blocking a different,
    successfully-sent chunk's items from being marked notified -- a single
    giant message used to make the whole send atomic-fail, silently
    stranding every approved item at 'new' forever.
    """
    items = await get_approved_items_for_notification(pool)

    if not items:
        text = format_smoke_summary(items)
        heartbeat_ok = await send_telegram_message(bot_token, chat_id, text)
        if logger is not None:
            logger.info(
                "publish.sent",
                channel="telegram",
                item_count=0,
                sent=0,
                heartbeat_ok=heartbeat_ok,
            )
        return {"sent": 0, "item_count": 0}

    chunks = _chunk_items_for_telegram(items)
    notified = 0
    for idx, chunk in enumerate(chunks, 1):
        text = (
            format_smoke_summary(chunk)
            if len(chunks) == 1
            else _format_chunk_summary(chunk, idx, len(chunks), len(items))
        )
        ok = await send_telegram_message(bot_token, chat_id, text)
        if ok:
            await mark_notified(pool, [item["id"] for item in chunk])
            notified += len(chunk)
        elif logger is not None:
            logger.warning(
                "publish.chunk_failed",
                channel="telegram",
                chunk=idx,
                total_chunks=len(chunks),
                chunk_size=len(chunk),
            )

    if logger is not None:
        logger.info(
            "publish.sent",
            channel="telegram",
            item_count=len(items),
            sent=notified,
            chunks=len(chunks),
        )

    return {"sent": notified, "item_count": len(items)}
