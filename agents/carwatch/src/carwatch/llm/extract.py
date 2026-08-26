"""src/carwatch/llm/extract.py"""
import json
import re

import structlog
from pydantic import ValidationError
from selectolax.parser import HTMLParser

from carwatch import dedupe, fetcher
from carwatch.cost import (
    MONTHLY_COST_CAP_USD,
    compute_cost_usd,
    is_extraction_cost_capped,
    load_llm_pricing,
    record_llm_usage,
)
from carwatch.llm.client import MODEL
from carwatch.llm.client import call_extract as _call_extract_raw
from carwatch.models import ExtractedEvent
from carwatch.publishers.telegram import send_telegram_message
from carwatch.settings import CONFIG_DIR

MAX_CHARS = 6000 * 4  # approximate 4 chars/token (SPEC.md §11.3 caps at 6000 tokens)
MIN_TEXT_LEN_FOR_FULL_EXTRACT = 400
DEGRADED_CONFIDENCE_CAP = 0.5

logger = structlog.get_logger()

SYSTEM_PROMPT = """\
Extraia dados estruturados de lançamento de veículo do artigo fornecido.

REGRAS:
- Use null para qualquer campo não afirmado explicitamente no texto.
- NUNCA infira, estime ou complete com conhecimento externo.
- Converta unidades para o padrão do schema (hp, Nm, kWh, km).
- Se o artigo citar múltiplas versões, registre a de entrada e liste as
  demais em highlights.
- is_new_generation: true APENAS se o texto indicar plataforma nova ou
  geração nova. Facelift, restyling, "atualizado", "renovado" => false.
  Na dúvida => false.
- markets: códigos ISO-3166-1 alpha-2. Global/mundial => listar os
  mercados citados; se nenhum, usar [].
- event_date: data do anúncio (formato ISO). Não confundir com data de venda.
- Artigo em qualquer idioma; saída sempre em inglês, exceto highlights
  que devem sair em português do Brasil.
- highlights: 3 a 5 itens, ≤120 caracteres cada, factuais.
- confidence: 0-1, refletindo quão completo e inequívoco é o artigo.

Responda APENAS com um objeto JSON com os campos: brand, model, generation,
body_type, stage, is_new_generation, markets, global_debut, event_date,
sales_start, powertrain, price, highlights, confidence. Sem markdown.
"""


async def call_extract(article_text: str) -> tuple[str, dict]:
    """Thin wrapper over the client's `(text, usage)` contract.

    Passes `usage` on to the caller (extract_one_item) instead of swallowing
    it -- Fase 3's cost cap (SPEC.md §18) needs each call's token counts to
    record into `llm_usage` and compute the running monthly total. The
    cost-observability `llm.call` log event is emitted by
    _record_extract_usage below, once cost (usd) has actually been computed,
    rather than here.
    """
    return await _call_extract_raw(SYSTEM_PROMPT, article_text)


async def _record_extract_usage(pool, usage: dict) -> None:
    input_price, output_price = load_llm_pricing(CONFIG_DIR / "settings.yaml", MODEL)
    cost = compute_cost_usd(
        usage["tokens_in"], usage["tokens_out"],
        input_usd_per_million=input_price, output_usd_per_million=output_price,
    )
    logger.info(
        "llm.call",
        op="extract",
        model=MODEL,
        tokens_in=usage.get("tokens_in"),
        tokens_out=usage.get("tokens_out"),
        stop_reason=usage.get("stop_reason"),
        usd=cost,
    )
    await record_llm_usage(pool, "extract", MODEL, usage["tokens_in"], usage["tokens_out"], cost)


def extract_article_text(html: str) -> str:
    tree = HTMLParser(html)

    ld_json_node = tree.css_first('script[type="application/ld+json"]')
    if ld_json_node is not None:
        try:
            data = json.loads(ld_json_node.text())
        except (json.JSONDecodeError, TypeError):
            data = None
        candidates = data if isinstance(data, list) else [data] if data else []
        for candidate in candidates:
            if isinstance(candidate, dict) and candidate.get("@type") == "NewsArticle":
                body = candidate.get("articleBody")
                if body:
                    return body

    for selector in ("article", "main"):
        node = tree.css_first(selector)
        if node is not None:
            text = node.text(separator=" ", strip=True)
            if len(text) > MIN_TEXT_LEN_FOR_FULL_EXTRACT:
                return text

    paragraphs = tree.css("p")
    return " ".join(p.text(strip=True) for p in paragraphs)


def truncate_for_llm(text: str) -> str:
    return text[:MAX_CHARS]


def parse_extract_response(raw_text: str) -> ExtractedEvent | None:
    # A greedy `\{.*\}` regex would match from the FIRST `{` to the LAST `}`
    # in the whole cleaned text -- if the LLM appends any trailing chatter
    # after the JSON object that itself contains a stray `{`/`}`, the regex
    # swallows that too and json.loads() fails on an otherwise well-formed
    # object. JSONDecoder.raw_decode() instead parses the first complete,
    # valid JSON value starting at `start` and reports exactly where it
    # ends, correctly handling this schema's nested objects
    # (powertrain/price) and simply ignoring whatever text follows.
    cleaned = re.sub(r"```(?:json)?", "", raw_text).replace("```", "").strip()
    start = cleaned.find("{")
    if start == -1:
        return None
    try:
        data, _end = json.JSONDecoder().raw_decode(cleaned, start)
    except json.JSONDecodeError:
        return None
    try:
        return ExtractedEvent.model_validate(data)
    except ValidationError:
        return None


async def extract_one_item(pool, row: tuple, logger) -> str:
    item_id, url, title, summary, source_id, source_tier = row

    result = await fetcher.fetch(url, kind="page")
    degraded = result.status != 200 or result.blocked or not result.body

    if degraded:
        article_text = f"{title}\n\n{summary or ''}"
    else:
        article_text = extract_article_text(result.body)
        if len(article_text) < MIN_TEXT_LEN_FOR_FULL_EXTRACT:
            degraded = True
            article_text = f"{title}\n\n{summary or ''}"

    truncated = truncate_for_llm(article_text)
    raw_response, usage = await call_extract(truncated)
    await _record_extract_usage(pool, usage)
    extracted = parse_extract_response(raw_response)

    if extracted is None:
        retry_text = truncated + (
            "\n\n[A resposta anterior não pôde ser validada como o JSON esperado. "
            "Responda novamente, apenas com o objeto JSON, sem markdown.]"
        )
        raw_response, usage = await call_extract(retry_text)
        await _record_extract_usage(pool, usage)
        extracted = parse_extract_response(raw_response)

    if extracted is None:
        async with pool.connection() as conn:
            await conn.execute("UPDATE raw_items SET status = 'error' WHERE id = %s", (item_id,))
        if logger is not None:
            logger.warning("llm.call", op="extract", status="parse_error", item_id=item_id)
        return "error"

    if degraded:
        extracted.confidence = min(extracted.confidence, DEGRADED_CONFIDENCE_CAP)

    await dedupe.process_extracted_event(
        pool, extracted, source_id=source_id, raw_item_id=item_id, source_tier=source_tier
    )
    async with pool.connection() as conn:
        await conn.execute(
            "UPDATE raw_items SET status = 'extracted', body = %s WHERE id = %s",
            (None if degraded else result.body, item_id),
        )
    return "extracted"


async def run_extract(pool, logger, bot_token: str, chat_id: str, limit: int = 50) -> dict:
    """Extract structured launch data from approved raw_items.

    bot_token/chat_id mirror curate.py's run_curate convention (explicit
    params, not settings read internally) -- SPEC.md §18/§19 require the
    monthly cost cap to "notifica e pausa": a log line alone only reaches the
    local systemd journal on this `Type=oneshot` unit, never the operator, so
    the cap must also send a Telegram message, not just log a warning.
    """
    if await is_extraction_cost_capped(pool):
        if logger is not None:
            logger.warning("extract.cost_capped", cap_usd=MONTHLY_COST_CAP_USD)
        await send_telegram_message(
            bot_token, chat_id,
            f"⚠️ CarWatch: extração pausada — custo mensal de LLM ultrapassou US${MONTHLY_COST_CAP_USD:.0f}",
        )
        return {"in": 0, "extracted": 0, "error": 0, "cost_capped": True}

    async with pool.connection() as conn:
        result = await conn.execute(
            "SELECT ri.id, ri.url, ri.title, ri.summary, ri.source_id, s.tier "
            "FROM raw_items ri JOIN sources s ON s.id = ri.source_id "
            "WHERE ri.status = 'new' AND ri.classified IS NOT NULL "
            "AND ri.classified->>'is_launch' = 'true' LIMIT %s",
            (limit,),
        )
        rows = await result.fetchall()

    extracted_count = error_count = 0
    for row in rows:
        outcome = await extract_one_item(pool, row, logger)
        if outcome == "extracted":
            extracted_count += 1
        else:
            error_count += 1

    stats = {"in": len(rows), "extracted": extracted_count, "error": error_count}
    if logger is not None:
        logger.info("extract.batch", **stats)
    return stats
