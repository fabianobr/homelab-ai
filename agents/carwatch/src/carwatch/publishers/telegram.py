"""src/carwatch/publishers/telegram.py"""
import asyncio
import html

import httpx

TELEGRAM_API_BASE = "https://api.telegram.org"

STAGE_EMOJI = {
    "spy": "🕵️", "teaser": "🎬", "concept": "💭", "world_premiere": "🌍",
    "specs_release": "📋", "pricing": "💵", "on_sale": "🛒", "market_launch": "🚀",
}
STAGE_LABEL_PT = {
    "spy": "Flagra", "teaser": "Teaser", "concept": "Conceito",
    "world_premiere": "Estreia mundial", "specs_release": "Ficha técnica divulgada",
    "pricing": "Preço anunciado", "on_sale": "Pré-venda aberta",
    "market_launch": "Chegada ao mercado",
}
POWERTRAIN_TYPE_LABEL = {
    "bev": "Elétrico", "phev": "Híbrido plug-in", "hev": "Híbrido",
    "ice": "Combustão", "fcev": "Célula de combustível",
}
PRICE_STATUS_LABEL = {"official": "oficial", "estimated": "estimado", "starting_from": "a partir de"}


async def send_telegram_message(bot_token: str, chat_id: str, text: str) -> bool:
    url = f"{TELEGRAM_API_BASE}/bot{bot_token}/sendMessage"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(url, json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"})
            response.raise_for_status()
            return True
    except httpx.HTTPError:
        return False


def _format_powertrain(powertrain: dict | None) -> str:
    if not powertrain:
        return "não informado"
    ptype = powertrain.get("type")
    parts = [POWERTRAIN_TYPE_LABEL.get(ptype, html.escape(ptype) if ptype else "?")]
    if powertrain.get("power_hp"):
        parts.append(f"{powertrain['power_hp']} cv")
    if powertrain.get("range_km"):
        cycle = powertrain.get("range_cycle")
        parts.append(f"{powertrain['range_km']} km ({html.escape(cycle) if cycle else '?'})")
    return " · ".join(parts)


def _format_price(price: dict | None) -> str:
    if not price or price.get("amount") is None:
        return "não divulgado"
    status = PRICE_STATUS_LABEL.get(price.get("status"), "")
    currency = html.escape(price.get("currency") or "")
    return f"{currency} {price['amount']:,.0f} ({status})".strip()


def format_event_message(event: dict, source_count: int, primary_url: str) -> str:
    # brand/model/markets/highlights/sales_start are free-text fields sourced
    # from the LLM extraction pipeline (ExtractedEvent), not from a fixed
    # vocabulary, and this message is sent with parse_mode="HTML" -- any
    # unescaped '<', '>', or '&' in that text would corrupt Telegram's HTML
    # parsing and fail the send (leaving the event stuck unpublished and
    # retried every future run). Only the tags we build ourselves (<b>,
    # <a href=...>) are literal HTML; everything interpolated into them, plus
    # the primary_url placed inside the href attribute, is escaped.
    stage = event["stage"]
    emoji = STAGE_EMOJI.get(stage, "🚗")
    label = STAGE_LABEL_PT.get(stage, html.escape(stage))
    markets = ", ".join(html.escape(m) for m in (event.get("markets") or [])) or "Global"

    brand = html.escape(event["brand"])
    model = html.escape(event["model"])

    lines = [f"🚗 <b>{brand} {model}</b>", f"{emoji} {label} · {markets}", ""]
    highlights = event.get("highlights") or []
    if highlights:
        lines.append("\n".join(f"• {html.escape(h)}" for h in highlights))
        lines.append("")
    lines.append(f"⚡ {_format_powertrain(event.get('powertrain'))}")
    lines.append(f"💰 {_format_price(event.get('price'))}")
    if event.get("sales_start"):
        lines.append(f"📅 Vendas: {html.escape(event['sales_start'])}")
    lines.append("")
    lines.append(f'<a href="{html.escape(primary_url)}">Fonte</a> · {source_count} fonte(s)')
    return "\n".join(lines)


async def get_pending_events(pool) -> list[dict]:
    async with pool.connection() as conn:
        result = await conn.execute(
            "SELECT le.id, le.brand, le.model, le.stage, le.markets, le.highlights, "
            "le.powertrain, le.price, le.sales_start, "
            "(SELECT ri.url FROM event_sources es JOIN raw_items ri ON ri.id = es.item_id "
            " WHERE es.event_id = le.id ORDER BY es.is_primary DESC, es.seen_at ASC LIMIT 1) AS primary_url, "
            "(SELECT count(*) FROM event_sources es WHERE es.event_id = le.id) AS source_count "
            "FROM launch_events le WHERE le.published = FALSE AND le.confidence >= 0.7 "
            "ORDER BY le.first_seen_at ASC"
        )
        rows = await result.fetchall()

    return [
        {
            "id": r[0], "brand": r[1], "model": r[2], "stage": r[3], "markets": r[4],
            "highlights": r[5], "powertrain": r[6], "price": r[7], "sales_start": r[8],
            "primary_url": r[9], "source_count": r[10],
        }
        for r in rows
    ]


async def mark_published(pool, event_id: int) -> None:
    async with pool.connection() as conn:
        await conn.execute("UPDATE launch_events SET published = TRUE WHERE id = %s", (event_id,))


async def publish_pending_events(pool, bot_token: str, chat_id: str, logger) -> dict:
    events = await get_pending_events(pool)
    sent = 0
    for i, event in enumerate(events):
        text = format_event_message(event, event["source_count"], event["primary_url"] or "")
        ok = await send_telegram_message(bot_token, chat_id, text)
        if ok:
            await mark_published(pool, event["id"])
            sent += 1
        if logger is not None:
            logger.info("publish.sent", event_id=event["id"], channel="telegram", ok=ok)
        if i < len(events) - 1:
            await asyncio.sleep(1.1)
    return {"pending": len(events), "sent": sent}
