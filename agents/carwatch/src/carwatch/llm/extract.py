"""src/carwatch/llm/extract.py"""
import json
import re

import structlog
from pydantic import ValidationError
from selectolax.parser import HTMLParser

from carwatch import dedupe, fetcher
from carwatch.llm.client import MODEL
from carwatch.llm.client import call_extract as _call_extract_raw
from carwatch.models import ExtractedEvent

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


async def call_extract(article_text: str) -> str:
    """Thin wrapper over the client's `(text, usage)` contract.

    extract_one_item (below) and its tests treat this as a plain-string
    call, mirroring the Fase 2 plan's original sketch -- the tuple
    unpacking and cost-observability logging happen here, at the one
    call site, instead of leaking the client's richer return shape into
    every caller.
    """
    text, usage = await _call_extract_raw(SYSTEM_PROMPT, article_text)
    logger.info(
        "llm.call",
        op="extract",
        model=MODEL,
        tokens_in=usage.get("tokens_in"),
        tokens_out=usage.get("tokens_out"),
        stop_reason=usage.get("stop_reason"),
    )
    return text


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
    raw_response = await call_extract(truncated)
    extracted = parse_extract_response(raw_response)

    if extracted is None:
        retry_text = truncated + (
            "\n\n[A resposta anterior não pôde ser validada como o JSON esperado. "
            "Responda novamente, apenas com o objeto JSON, sem markdown.]"
        )
        raw_response = await call_extract(retry_text)
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


async def run_extract(pool, logger, limit: int = 50) -> dict:
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
