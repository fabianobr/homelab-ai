"""src/carwatch/llm/classify.py"""
import json
import re

from pydantic import ValidationError

from carwatch.llm.client import call_classify
from carwatch.models import ClassifyItem

SYSTEM_PROMPT = """\
Você classifica notícias automotivas. Para cada item, decida se anuncia
um LANÇAMENTO DE VEÍCULO (modelo novo, nova geração, facelift, versão
nova, estreia mundial, início de vendas ou anúncio de preço).

NÃO é lançamento: resultados financeiros, recall, nomeações executivas,
números de venda, fábricas, parcerias, patrocínio, testes de longa duração,
comparativos, opinião, listas.

Estágios possíveis:
  spy            - flagra de protótipo camuflado
  teaser         - imagem/vídeo parcial oficial pré-estreia
  concept        - conceito, não previsto para produção
  world_premiere - primeira apresentação pública oficial do veículo
  specs_release  - divulgação de ficha técnica completa
  pricing        - anúncio oficial de preço
  on_sale        - abertura de pedidos/pré-venda
  market_launch  - chegada a um mercado onde já existia em outro

Responda APENAS com um array JSON, um objeto por item de entrada,
na mesma ordem. Sem markdown, sem preâmbulo.

[{"i":0,"is_launch":true,"stage":"world_premiere","brand":"BYD",
  "model":"Seal 06 DM-i","confidence":0.92}, ...]

is_launch=false → os demais campos podem ser null.
confidence é sua certeza de 0 a 1.
Se o título estiver em outro idioma, traduza mentalmente. brand e model
sempre em alfabeto latino.
"""

BATCH_SIZE = 20
APPROVAL_CONFIDENCE_THRESHOLD = 0.6


def build_classify_prompt() -> str:
    return SYSTEM_PROMPT


def _format_batch_for_prompt(rows: list[tuple]) -> str:
    lines = []
    for i, (_id, title, summary) in enumerate(rows):
        lines.append(f'{{"i":{i},"title":{json.dumps(title)},"summary":{json.dumps(summary or "")}}}')
    return "[\n" + ",\n".join(lines) + "\n]"


def parse_classify_response(raw_text: str, batch_size: int) -> list[ClassifyItem] | None:
    cleaned = re.sub(r"```(?:json)?", "", raw_text).replace("```", "").strip()
    match = re.search(r"\[.*\]", cleaned, re.DOTALL)
    if not match:
        return None
    try:
        raw_items = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    if not isinstance(raw_items, list) or len(raw_items) != batch_size:
        return None

    try:
        items = [ClassifyItem.model_validate(item) for item in raw_items]
    except ValidationError:
        return None

    if [item.i for item in items] != list(range(batch_size)):
        return None
    return items


async def run_classify(pool, logger, limit: int = 100) -> dict:
    async with pool.connection() as conn:
        result = await conn.execute(
            "SELECT id, title, summary FROM raw_items "
            "WHERE status = 'new' AND prefilter_ok = TRUE LIMIT %s",
            (limit,),
        )
        rows = await result.fetchall()

    approved = rejected = parse_errors = 0
    system_prompt = build_classify_prompt()

    for batch_start in range(0, len(rows), BATCH_SIZE):
        batch = rows[batch_start : batch_start + BATCH_SIZE]
        user_content = _format_batch_for_prompt(batch)
        raw_response = await call_classify(system_prompt, user_content)
        items = parse_classify_response(raw_response, batch_size=len(batch))

        if items is None:
            parse_errors += len(batch)
            if logger is not None:
                logger.warning("llm.call", op="classify", status="parse_error", batch_size=len(batch))
            continue

        async with pool.connection() as conn:
            for (row_id, _title, _summary), item in zip(batch, items):
                is_approved = item.is_launch and item.confidence >= APPROVAL_CONFIDENCE_THRESHOLD
                new_status = "new" if is_approved else "rejected"
                await conn.execute(
                    "UPDATE raw_items SET classified = %s, status = %s WHERE id = %s",
                    (item.model_dump_json(), new_status, row_id),
                )
                if is_approved:
                    approved += 1
                else:
                    rejected += 1

    return {
        "in": len(rows),
        "approved": approved,
        "rejected": rejected,
        "parse_errors": parse_errors,
    }
