"""src/carwatch/publishers/telegram.py"""
import json

import httpx

TELEGRAM_API_BASE = "https://api.telegram.org"


async def send_telegram_message(bot_token: str, chat_id: str, text: str) -> bool:
    url = f"{TELEGRAM_API_BASE}/bot{bot_token}/sendMessage"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(url, json={"chat_id": chat_id, "text": text})
            response.raise_for_status()
            return True
    except httpx.HTTPError:
        return False


def format_smoke_summary(items: list[dict]) -> str:
    if not items:
        return "CarWatch — execução semanal\n\nNenhum lançamento novo detectado nesta execução."

    lines = [f"CarWatch — execução semanal", "", f"{len(items)} item(ns) classificado(s) como lançamento:", ""]
    for i, item in enumerate(items, 1):
        brand = item.get("brand") or "?"
        model = item.get("model") or "?"
        stage = item.get("stage") or "?"
        confidence = item.get("confidence", 0.0)
        lines.append(f"{i}. {brand} {model} ({stage}) — confiança {confidence:.2f}")
        lines.append(f"   {item['url']}")
    return "\n".join(lines)


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
    items = await get_approved_items_for_notification(pool)
    text = format_smoke_summary(items)
    sent = await send_telegram_message(bot_token, chat_id, text)
    if sent:
        await mark_notified(pool, [item["id"] for item in items])
    if logger is not None:
        logger.info("publish.sent", channel="telegram", item_count=len(items), sent=sent)
    return {"sent": sent, "item_count": len(items)}
