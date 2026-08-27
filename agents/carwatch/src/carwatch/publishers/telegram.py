"""src/carwatch/publishers/telegram.py"""
import asyncio
import html

import httpx

TELEGRAM_API_BASE = "https://api.telegram.org"
# frankfurter.app 301-redirects here now; httpx doesn't follow redirects by
# default and raise_for_status() rejects 3xx too, so pointing this at the old
# host makes fetch_usd_rates() silently return {} on every real call. Point
# straight at the live host, and still pass follow_redirects=True below as a
# defense-in-depth against the next such move.
FRANKFURTER_API = "https://api.frankfurter.dev/v1/latest"

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

# extract.py's prompt constrains `markets` to ISO-3166-1 alpha-2 codes, so
# lookups here are keyed on that. Covers UN member states plus a few
# territories relevant to automotive markets (TW, HK, MO, PR); an unlisted
# code still renders correctly via _format_market's fallback to the raw code.
COUNTRY_NAME_PT = {
    "AD": "Andorra", "AE": "Emirados Árabes Unidos", "AF": "Afeganistão",
    "AG": "Antígua e Barbuda", "AI": "Anguilla", "AL": "Albânia", "AM": "Armênia",
    "AO": "Angola", "AR": "Argentina", "AS": "Samoa Americana", "AT": "Áustria",
    "AU": "Austrália", "AW": "Aruba", "AZ": "Azerbaijão", "BA": "Bósnia e Herzegovina",
    "BB": "Barbados", "BD": "Bangladesh", "BE": "Bélgica", "BF": "Burkina Faso",
    "BG": "Bulgária", "BH": "Bahrein", "BI": "Burundi", "BJ": "Benin",
    "BM": "Bermudas", "BN": "Brunei", "BO": "Bolívia", "BR": "Brasil",
    "BS": "Bahamas", "BT": "Butão", "BW": "Botsuana", "BY": "Belarus",
    "BZ": "Belize", "CA": "Canadá", "CD": "República Democrática do Congo",
    "CF": "República Centro-Africana", "CG": "Congo", "CH": "Suíça",
    "CI": "Costa do Marfim", "CK": "Ilhas Cook", "CL": "Chile", "CM": "Camarões",
    "CN": "China", "CO": "Colômbia", "CR": "Costa Rica", "CU": "Cuba",
    "CV": "Cabo Verde", "CY": "Chipre", "CZ": "República Tcheca", "DE": "Alemanha",
    "DJ": "Djibuti", "DK": "Dinamarca", "DM": "Dominica", "DO": "República Dominicana",
    "DZ": "Argélia", "EC": "Equador", "EE": "Estônia", "EG": "Egito",
    "ER": "Eritreia", "ES": "Espanha", "ET": "Etiópia", "FI": "Finlândia",
    "FJ": "Fiji", "FM": "Micronésia", "FR": "França", "GA": "Gabão",
    "GB": "Reino Unido", "GD": "Granada", "GE": "Geórgia", "GH": "Gana",
    "GI": "Gibraltar", "GL": "Groenlândia", "GM": "Gâmbia", "GN": "Guiné",
    "GQ": "Guiné Equatorial", "GR": "Grécia", "GT": "Guatemala", "GU": "Guam",
    "GW": "Guiné-Bissau", "GY": "Guiana", "HK": "Hong Kong", "HN": "Honduras",
    "HR": "Croácia", "HT": "Haiti", "HU": "Hungria", "ID": "Indonésia",
    "IE": "Irlanda", "IL": "Israel", "IN": "Índia", "IQ": "Iraque", "IR": "Irã",
    "IS": "Islândia", "IT": "Itália", "JM": "Jamaica", "JO": "Jordânia",
    "JP": "Japão", "KE": "Quênia", "KG": "Quirguistão", "KH": "Camboja",
    "KI": "Kiribati", "KM": "Comores", "KN": "São Cristóvão e Névis",
    "KP": "Coreia do Norte", "KR": "Coreia do Sul", "KW": "Kuwait",
    "KY": "Ilhas Cayman", "KZ": "Cazaquistão", "LA": "Laos", "LB": "Líbano",
    "LC": "Santa Lúcia", "LI": "Liechtenstein", "LK": "Sri Lanka", "LR": "Libéria",
    "LS": "Lesoto", "LT": "Lituânia", "LU": "Luxemburgo", "LV": "Letônia",
    "LY": "Líbia", "MA": "Marrocos", "MC": "Mônaco", "MD": "Moldávia",
    "ME": "Montenegro", "MG": "Madagascar", "MH": "Ilhas Marshall",
    "MK": "Macedônia do Norte", "ML": "Mali", "MM": "Mianmar", "MN": "Mongólia",
    "MO": "Macau", "MR": "Mauritânia", "MT": "Malta", "MU": "Maurício",
    "MV": "Maldivas", "MW": "Malaui", "MX": "México", "MY": "Malásia",
    "MZ": "Moçambique", "NA": "Namíbia", "NE": "Níger", "NG": "Nigéria",
    "NI": "Nicarágua", "NL": "Países Baixos", "NO": "Noruega", "NP": "Nepal",
    "NR": "Nauru", "NZ": "Nova Zelândia", "OM": "Omã", "PA": "Panamá",
    "PE": "Peru", "PG": "Papua-Nova Guiné", "PH": "Filipinas", "PK": "Paquistão",
    "PL": "Polônia", "PR": "Porto Rico", "PS": "Palestina", "PT": "Portugal",
    "PW": "Palau", "PY": "Paraguai", "QA": "Catar", "RO": "Romênia",
    "RS": "Sérvia", "RU": "Rússia", "RW": "Ruanda", "SA": "Arábia Saudita",
    "SB": "Ilhas Salomão", "SC": "Seicheles", "SD": "Sudão", "SE": "Suécia",
    "SG": "Singapura", "SI": "Eslovênia", "SK": "Eslováquia", "SL": "Serra Leoa",
    "SM": "San Marino", "SN": "Senegal", "SO": "Somália", "SR": "Suriname",
    "SS": "Sudão do Sul", "ST": "São Tomé e Príncipe", "SV": "El Salvador",
    "SY": "Síria", "SZ": "Essuatíni", "TD": "Chade", "TG": "Togo",
    "TH": "Tailândia", "TJ": "Tajiquistão", "TL": "Timor-Leste",
    "TM": "Turcomenistão", "TN": "Tunísia", "TO": "Tonga", "TR": "Turquia",
    "TT": "Trinidad e Tobago", "TV": "Tuvalu", "TW": "Taiwan", "TZ": "Tanzânia",
    "UA": "Ucrânia", "UG": "Uganda", "US": "Estados Unidos", "UY": "Uruguai",
    "UZ": "Uzbequistão", "VA": "Vaticano", "VC": "São Vicente e Granadinas",
    "VE": "Venezuela", "VN": "Vietnã", "VU": "Vanuatu", "WS": "Samoa",
    "YE": "Iêmen", "ZA": "África do Sul", "ZM": "Zâmbia", "ZW": "Zimbábue",
}


async def send_telegram_message(bot_token: str, chat_id: str, text: str) -> bool:
    url = f"{TELEGRAM_API_BASE}/bot{bot_token}/sendMessage"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(url, json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"})
            response.raise_for_status()
            return True
    except httpx.HTTPError:
        return False


def _flag_emoji(iso_code: str) -> str:
    letters = iso_code.strip().upper()
    if len(letters) != 2 or not letters.isalpha():
        return ""
    # Regional indicator symbols are Unicode code points offset from 'A' at
    # U+1F1E6; a two-letter ISO code maps directly to the flag emoji pair.
    return "".join(chr(0x1F1E6 + ord(ch) - ord("A")) for ch in letters)


def _format_market(code: str) -> str:
    flag = _flag_emoji(code)
    name = COUNTRY_NAME_PT.get(code.strip().upper())
    label = html.escape(name) if name else html.escape(code)
    return f"{flag} {label}".strip()


async def fetch_usd_rates(currencies: set[str], logger=None) -> dict[str, float]:
    """Return units-of-currency-per-1-USD for each code, via frankfurter.dev.

    Best-effort only: on any failure (network error, timeout, malformed JSON
    body) this returns {} so callers just omit the USD conversion instead of
    failing message publishing over an unrelated FX API outage. An
    unsupported currency code doesn't trigger this path -- frankfurter still
    replies 200 and simply omits that code from `rates`, which
    _convert_to_usd already treats as "no rate available" for that currency.
    """
    to_fetch = {c.strip().upper() for c in currencies if c and c.strip().upper() != "USD"}
    if not to_fetch:
        return {}
    try:
        async with httpx.AsyncClient(timeout=5.0, follow_redirects=True) as client:
            response = await client.get(FRANKFURTER_API, params={"from": "USD", "to": ",".join(sorted(to_fetch))})
            response.raise_for_status()
            return response.json().get("rates", {})
    except (httpx.HTTPError, ValueError) as exc:
        if logger is not None:
            logger.warning(
                "publish.usd_rates_failed", currencies=sorted(to_fetch), error=f"{type(exc).__name__}: {exc}"
            )
        return {}


def _convert_to_usd(amount: float, currency: str | None, usd_rates: dict[str, float] | None) -> float | None:
    if not usd_rates or not currency:
        return None
    currency = currency.strip().upper()
    if currency == "USD":
        return None
    rate = usd_rates.get(currency)
    if not rate:
        return None
    return amount / rate


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


def _format_price(price: dict | None, usd_rates: dict[str, float] | None = None) -> str:
    if not price or price.get("amount") is None:
        return "não divulgado"
    amount = price["amount"]
    currency = price.get("currency") or ""
    amount_str = f"{html.escape(currency)} {amount:,.0f}".strip()
    usd = _convert_to_usd(amount, currency, usd_rates)
    if usd is not None:
        amount_str += f" (≈ US$ {usd:,.0f})"
    status = PRICE_STATUS_LABEL.get(price.get("status"), "")
    return f"{amount_str} · {status}" if status else amount_str


def format_event_message(
    event: dict, source_count: int, primary_url: str, usd_rates: dict[str, float] | None = None
) -> str:
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
    markets = ", ".join(_format_market(m) for m in (event.get("markets") or [])) or "Global"

    brand = html.escape(event["brand"])
    model = html.escape(event["model"])

    lines = [f"🚗 <b>{brand} {model}</b>", f"{emoji} {label} · {markets}", ""]
    highlights = event.get("highlights") or []
    if highlights:
        lines.append("\n".join(f"• {html.escape(h)}" for h in highlights))
        lines.append("")
    lines.append(f"⚡ {_format_powertrain(event.get('powertrain'))}")
    lines.append(f"💰 {_format_price(event.get('price'), usd_rates)}")
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
        await conn.execute(
            "UPDATE launch_events SET published = TRUE, published_at = now() WHERE id = %s", (event_id,)
        )


async def publish_pending_events(pool, bot_token: str, chat_id: str, logger) -> dict:
    events = await get_pending_events(pool)
    currencies = {
        event["price"]["currency"]
        for event in events
        if event.get("price") and event["price"].get("amount") is not None and event["price"].get("currency")
    }
    usd_rates = await fetch_usd_rates(currencies, logger)
    if logger is not None and currencies:
        logger.info("publish.usd_rates", requested=sorted(currencies), resolved=sorted(usd_rates.keys()))
    sent = 0
    for i, event in enumerate(events):
        text = format_event_message(event, event["source_count"], event["primary_url"] or "", usd_rates)
        ok = await send_telegram_message(bot_token, chat_id, text)
        if ok:
            await mark_published(pool, event["id"])
            sent += 1
        if logger is not None:
            logger.info("publish.sent", event_id=event["id"], channel="telegram", ok=ok)
        if i < len(events) - 1:
            await asyncio.sleep(1.1)
    return {"pending": len(events), "sent": sent}
