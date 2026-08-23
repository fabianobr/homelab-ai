#!/usr/bin/env python3
"""
Weekly SDLC Research Agent
Searches for new agentic LLM tools for local software development,
compares against the backlog and appends new discoveries.
"""

import json
import logging
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import requests
import yaml
from ddgs import DDGS


ITEM_TYPES = {
    "coding_agent",
    "orchestrator",
    "model",
    "infrastructure",
    "technique",
}

ANALYSIS_ITEM_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "name",
        "type",
        "sdlc_relevance",
        "hw_viability",
        "description",
        "source_url",
    ],
    "properties": {
        "name": {"type": "string", "minLength": 1},
        "type": {"type": "string", "enum": sorted(ITEM_TYPES)},
        "sdlc_relevance": {"type": "integer", "minimum": 1, "maximum": 5},
        "hw_viability": {"type": "integer", "minimum": 1, "maximum": 5},
        "description": {"type": "string", "minLength": 1},
        "source_url": {"type": "string"},
    },
}

ANALYSIS_SCHEMA = {
    "type": "array",
    "items": ANALYSIS_ITEM_SCHEMA,
}


class AnalysisValidationError(ValueError):
    """Raised when Ollama returns JSON that does not satisfy ANALYSIS_SCHEMA."""


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
SCRIPT_DIR = Path(__file__).parent.resolve()
CONFIG_PATH = SCRIPT_DIR / "config.yaml"

sys.path.insert(0, str(SCRIPT_DIR.parent / "lib"))
from telegram_notify import send_telegram_document, send_telegram_message  # noqa: E402


# ---------------------------------------------------------------------------
# Config loader
# ---------------------------------------------------------------------------
def load_config() -> dict:
    with open(CONFIG_PATH, "r") as f:
        return yaml.safe_load(f)


# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------
def setup_logging(log_file: str) -> logging.Logger:
    log_path = SCRIPT_DIR / log_file
    logger = logging.getLogger("research_agent")
    logger.setLevel(logging.DEBUG)

    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")

    fh = logging.FileHandler(log_path, encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)

    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.INFO)
    ch.setFormatter(fmt)

    logger.addHandler(fh)
    logger.addHandler(ch)
    return logger


# ---------------------------------------------------------------------------
# Search backends
# ---------------------------------------------------------------------------
def search_searxng(query: str, base_url: str, logger: logging.Logger) -> list[dict]:
    """Search via local SearXNG instance."""
    params = {"q": query, "format": "json", "language": "en", "time_range": "year"}
    url = f"{base_url.rstrip('/')}/search"
    try:
        resp = requests.get(url, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        results = []
        for item in data.get("results", [])[:8]:
            results.append(
                {
                    "title": item.get("title", ""),
                    "url": item.get("url", ""),
                    "snippet": item.get("content", ""),
                }
            )
        return results
    except Exception as exc:
        logger.warning("SearXNG search failed for '%s': %s", query, exc)
        return []


def search_duckduckgo(query: str, logger: logging.Logger) -> list[dict]:
    """Search via duckduckgo-search library."""
    try:
        with DDGS() as ddgs:
            hits = list(ddgs.text(query, max_results=8, timelimit="y"))
        results = [
            {"title": h.get("title", ""), "url": h.get("href", ""), "snippet": h.get("body", "")}
            for h in hits
        ]
        logger.debug("DDGS returned %d results for '%s'", len(results), query)
        return results
    except Exception as exc:
        logger.warning("DuckDuckGo search failed for '%s': %s", query, exc)
        return []


def run_searches(
    queries: list[str], cfg: dict, logger: logging.Logger
) -> list[dict]:
    """Run all queries and deduplicate results by URL."""
    all_results: list[dict] = []
    seen_urls: set[str] = set()
    searxng_url = cfg.get("searxng_url", "")

    for query in queries:
        logger.info("Searching: %s", query)
        results: list[dict] = []

        # Try SearXNG first
        if searxng_url:
            results = search_searxng(query, searxng_url, logger)
            if results:
                logger.debug("SearXNG returned %d results for '%s'", len(results), query)

        # Fall back to DuckDuckGo
        if not results:
            results = search_duckduckgo(query, logger)

        for r in results:
            url = r.get("url", "")
            if url and url not in seen_urls:
                seen_urls.add(url)
                r["query"] = query
                all_results.append(r)
            elif not url:
                all_results.append(r)

        time.sleep(1)  # rate limiting

    logger.info("Total unique search results: %d", len(all_results))
    return all_results


# ---------------------------------------------------------------------------
# Backlog reader
# ---------------------------------------------------------------------------
def read_backlog(backlog_path: Path, logger: logging.Logger) -> str:
    """Return the full backlog text, or empty string if not found."""
    if not backlog_path.exists():
        logger.info("Backlog not found at %s — will create it", backlog_path)
        return ""
    try:
        return backlog_path.read_text(encoding="utf-8")
    except Exception as exc:
        logger.warning("Could not read backlog: %s", exc)
        return ""


def extract_known_items(backlog_text: str, known_discarded: list[str]) -> set[str]:
    """Extract tool/project names already in the backlog (lowercased)."""
    known: set[str] = set()
    for name in known_discarded:
        known.add(name.lower())
    # Capture markdown headings and bold text as known names
    patterns = [
        r"###\s+(.+)",
        r"\*\*(.+?)\*\*",
        r"^\|\s*[^|]+\|\s*([^|]+?)\s*\|",  # item name in the second table column
        r"`([^`]+)`",  # exact model/tool tags mentioned in prose
    ]
    for pat in patterns:
        for match in re.finditer(pat, backlog_text, re.MULTILINE):
            known.add(match.group(1).strip().lower())
    return known


def normalize_url(url: str) -> str:
    """Normalize a source URL for deterministic provenance checks."""
    try:
        parts = urlsplit(url.strip())
    except ValueError:
        return ""
    if parts.scheme not in {"http", "https"} or not parts.netloc:
        return ""
    path = re.sub(r"/{2,}", "/", parts.path).rstrip("/") or "/"
    tracking_params = {
        "dclid",
        "fbclid",
        "gclid",
        "igshid",
        "mc_cid",
        "mc_eid",
        "msclkid",
    }
    query = [
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if not key.casefold().startswith("utm_")
        and key.casefold() not in tracking_params
    ]
    # Query order is not part of the resource identity for the sources consumed
    # here. Sorting makes equivalent links stable while preserving functional
    # parameters such as YouTube's `v`, pagination and document IDs.
    normalized_query = urlencode(sorted(query))
    return urlunsplit(
        (parts.scheme.lower(), parts.netloc.lower(), path, normalized_query, "")
    )


def normalize_item_name(name: str) -> str:
    """Normalize headings, model tags and display qualifiers for deduplication."""
    value = re.sub(r"^\s*\d+(?:\s*[-–]\s*\d+)?[.)]?\s*", "", name.casefold())
    value = re.sub(r"\([^)]*\)", " ", value)
    return re.sub(r"[^a-z0-9]+", " ", value).strip()


def is_known_item_name(name: str, known_items: set[str]) -> bool:
    """Match exact normalized names and qualified variants such as 'Devstral Small'."""
    candidate = normalize_item_name(name)
    if not candidate:
        return True
    for known in known_items:
        normalized_known = normalize_item_name(known)
        if candidate == normalized_known:
            return True
        shorter, longer = sorted((candidate, normalized_known), key=len)
        if len(shorter) >= 7 and f" {shorter} " in f" {longer} ":
            return True
    return False


# ---------------------------------------------------------------------------
# Ollama interface
# ---------------------------------------------------------------------------
def check_ollama(ollama_url: str, logger: logging.Logger) -> list[str] | None:
    """Return the list of available model names, or None if Ollama is unreachable."""
    try:
        resp = requests.get(f"{ollama_url}/api/tags", timeout=8)
        resp.raise_for_status()
        models = [m["name"] for m in resp.json().get("models", [])]
        logger.info("Ollama available models: %s", models)
        return models
    except Exception as exc:
        logger.warning("Ollama not reachable: %s", exc)
        return None


def configured_models(cfg: dict) -> list[str]:
    """Return the configured primary/fallback models in stable order."""
    candidates = [cfg.get("ollama_model", "")]
    fallbacks = cfg.get("ollama_fallback_models")
    if fallbacks is None:
        # Backwards-compatible config parsing without restoring loose matching.
        fallbacks = [cfg.get("ollama_fallback_model", "")]
    elif isinstance(fallbacks, str):
        fallbacks = [fallbacks]
    candidates.extend(fallbacks)

    ordered = []
    for candidate in candidates:
        if candidate and candidate not in ordered:
            ordered.append(candidate)
    return ordered


def pick_models(cfg: dict, logger: logging.Logger) -> list[str]:
    """Select only exact installed models, preserving configured priority."""
    ollama_url = cfg["ollama_url"]
    models = check_ollama(ollama_url, logger)
    if not models:
        return []

    candidates = configured_models(cfg)
    selected = [candidate for candidate in candidates if candidate in models]
    missing = [candidate for candidate in candidates if candidate not in models]
    if missing:
        logger.warning(
            "Configured models not installed (no prefix substitution will be used): %s",
            missing,
        )
    if not selected:
        logger.error(
            "None of the configured models is installed. Configured=%s; installed=%s",
            candidates,
            models,
        )
        return []

    max_attempts = max(1, int(cfg.get("ollama_max_attempts", 2)))
    selected = selected[:max_attempts]
    logger.info("Models selected in attempt order: %s", selected)
    return selected


def ollama_chat(
    model: str,
    prompt: str,
    ollama_url: str,
    logger: logging.Logger,
    *,
    options: dict,
    timeout_seconds: int,
) -> str:
    """Send a bounded, non-thinking, schema-constrained request to Ollama."""
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        "think": False,
        "format": ANALYSIS_SCHEMA,
        "options": options,
    }
    try:
        resp = requests.post(
            f"{ollama_url}/api/chat", json=payload, timeout=timeout_seconds
        )
        resp.raise_for_status()
        try:
            content = resp.json()["message"]["content"]
            if not isinstance(content, str):
                raise TypeError("message.content is not a string")
            return content.strip()
        except (KeyError, TypeError, ValueError) as exc:
            raise AnalysisValidationError(
                f"envelope de resposta inválido: {exc}"
            ) from exc
    except Exception as exc:
        logger.error("Ollama request failed: %s", exc)
        raise


def validate_analysis_items(
    value: object,
    allowed_source_urls: set[str] | None = None,
) -> list[dict]:
    """Validate the LLM result deterministically before it reaches the backlog."""
    if not isinstance(value, list):
        raise AnalysisValidationError("a raiz deve ser um array")

    required = set(ANALYSIS_ITEM_SCHEMA["required"])
    validated = []
    for index, item in enumerate(value):
        location = f"item {index + 1}"
        if not isinstance(item, dict):
            raise AnalysisValidationError(f"{location} deve ser um objeto")

        keys = set(item)
        missing = required - keys
        extra = keys - required
        if missing:
            raise AnalysisValidationError(
                f"{location} sem campos obrigatórios: {sorted(missing)}"
            )
        if extra:
            raise AnalysisValidationError(
                f"{location} contém campos não permitidos: {sorted(extra)}"
            )

        for field in ("name", "description", "source_url"):
            if not isinstance(item[field], str):
                raise AnalysisValidationError(f"{location}.{field} deve ser string")
        if not item["name"].strip():
            raise AnalysisValidationError(f"{location}.name não pode ser vazio")
        if not item["description"].strip():
            raise AnalysisValidationError(f"{location}.description não pode ser vazia")
        source_url = normalize_url(item["source_url"])
        if allowed_source_urls:
            if not source_url:
                raise AnalysisValidationError(
                    f"{location}.source_url deve citar uma fonte coletada"
                )
            if source_url not in allowed_source_urls:
                raise AnalysisValidationError(
                    f"{location}.source_url não estava nos resultados de busca"
                )
        if not isinstance(item["type"], str):
            raise AnalysisValidationError(f"{location}.type deve ser string")
        if item["type"] not in ITEM_TYPES:
            raise AnalysisValidationError(
                f"{location}.type deve ser um de {sorted(ITEM_TYPES)}"
            )
        for field in ("sdlc_relevance", "hw_viability"):
            score = item[field]
            if isinstance(score, bool) or not isinstance(score, int) or not 1 <= score <= 5:
                raise AnalysisValidationError(
                    f"{location}.{field} deve ser inteiro entre 1 e 5"
                )
        validated.append(item)
    return validated


def parse_analysis_response(raw: str, search_results: list[dict] | None = None) -> list[dict]:
    """Parse an Ollama response and enforce the full analysis schema."""
    if not raw:
        raise AnalysisValidationError("resposta vazia")

    cleaned = re.sub(r"```(?:json)?\s*", "", raw)
    cleaned = re.sub(r"```", "", cleaned).strip()
    try:
        value = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise AnalysisValidationError(f"JSON inválido: {exc}") from exc
    allowed_source_urls = {
        normalize_url(result.get("url", ""))
        for result in (search_results or [])
        if normalize_url(result.get("url", ""))
    }
    return validate_analysis_items(value, allowed_source_urls)


# ---------------------------------------------------------------------------
# LLM analysis
# ---------------------------------------------------------------------------
ANALYSIS_PROMPT = """\
You are a technical analyst for a home AI lab running {hardware}.

Given the following web search results about local LLM tools for software development,
identify NEW tools, projects, models or techniques that are relevant to:
- Agentic coding assistants (code generation, review, debugging)
- Local SDLC automation (planning, testing, CI/CD with local LLMs)
- Orchestration frameworks compatible with Ollama
- Open-source self-hosted alternatives to GitHub Copilot / Cursor

ALREADY KNOWN items (skip these — do not include them):
{known_items}

SEARCH RESULTS:
{search_results}

For each NEW and relevant item you find, output a JSON array. Each element must have:
{{
  "name": "Tool or project name",
  "type": "coding_agent | orchestrator | model | infrastructure | technique",
  "sdlc_relevance": <integer 1-5>,
  "hw_viability": <integer 1-5>,
  "description": "One or two sentences about what it does and why it matters.",
  "source_url": "URL from the search results if available, else empty string"
}}

sdlc_relevance: 5 = covers multiple SDLC phases, 1 = narrow/tangential.
hw_viability: 5 = runs great on 16GB VRAM / 32GB RAM, 1 = requires much more.

Output ONLY the JSON array — no prose, no markdown fences, no explanation.
If there are no new relevant items, output an empty array: []
"""


def analyze_results(
    search_results: list[dict],
    known_items: set[str],
    hardware_context: str,
    models: list[str],
    ollama_url: str,
    logger: logging.Logger,
    *,
    options: dict,
    timeout_seconds: int,
) -> tuple[list[dict], str, str]:
    """Analyze results, retrying timeout/invalid output on the next model only."""
    if not search_results:
        logger.info("No search results to analyze.")
        return [], "", models[0]

    # Format results for prompt
    formatted = []
    for i, r in enumerate(search_results[:40], 1):  # cap at 40 to fit context
        formatted.append(
            f"{i}. TITLE: {r.get('title', '')}\n"
            f"   URL: {r.get('url', '')}\n"
            f"   SNIPPET: {r.get('snippet', '')[:300]}"
        )

    known_list = ", ".join(sorted(known_items)[:60]) if known_items else "(none)"
    search_block = "\n\n".join(formatted)

    prompt = ANALYSIS_PROMPT.format(
        hardware=hardware_context,
        known_items=known_list,
        search_results=search_block,
    )

    failures = []
    for attempt, model in enumerate(models, 1):
        logger.info(
            "Sending %d results to LLM for analysis (attempt %d/%d, model=%s)...",
            len(search_results),
            attempt,
            len(models),
            model,
        )
        try:
            raw = ollama_chat(
                model,
                prompt,
                ollama_url,
                logger,
                options=options,
                timeout_seconds=timeout_seconds,
            )
            items = parse_analysis_response(raw, search_results)
            logger.info("LLM identified %d new items with model %s.", len(items), model)
            return items, "", model
        except (requests.Timeout, AnalysisValidationError) as exc:
            reason = f"{model}: {exc}"
            failures.append(reason)
            logger.warning("Retryable LLM failure (%s)", reason)
            if attempt < len(models):
                logger.info("Retrying with the next configured fallback model.")
        except Exception as exc:
            # Other HTTP/connectivity/programming failures are not made more expensive by retrying.
            logger.error("Non-retryable LLM failure with %s: %s", model, exc)
            return [], f"LLM ({model}) falhou: {exc}", model

    attempted = ", ".join(models)
    details = "; ".join(failures)
    return [], f"Tentativas LLM esgotadas ({attempted}): {details}", attempted


# ---------------------------------------------------------------------------
# Deduplication against backlog
# ---------------------------------------------------------------------------
def filter_new_items(
    items: list[dict], known_items: set[str], logger: logging.Logger
) -> list[dict]:
    """Remove backlog matches and semantic duplicates in the current batch."""
    new_items = []
    seen_items = set(known_items)
    for item in items:
        name = item.get("name", "").strip()
        if is_known_item_name(name, seen_items):
            logger.debug("Skipping already-known item: %s", name)
        else:
            new_items.append(item)
            # Make the decision progressive: later exact or qualified variants
            # are compared against items already accepted from this response.
            seen_items.add(name)
    logger.info("%d items after dedup: %d new", len(items), len(new_items))
    return new_items


# ---------------------------------------------------------------------------
# Report generation
# ---------------------------------------------------------------------------
def format_item_markdown(item: dict) -> str:
    name = item.get("name", "Unknown")
    itype = item.get("type", "-")
    sdlc = item.get("sdlc_relevance", "-")
    hw = item.get("hw_viability", "-")
    desc = item.get("description", "")
    url = item.get("source_url", "")

    lines = [
        f"### {name}",
        f"- **Tipo:** {itype}",
        f"- **Relevancia SDLC:** {sdlc}/5",
        f"- **Viabilidade HW:** {hw}/5",
        f"- **Descricao:** {desc}",
    ]
    if url:
        lines.append(f"- **Fonte:** {url}")
    return "\n".join(lines)


def write_report(
    new_items: list[dict],
    all_results: list[dict],
    queries: list[str],
    reports_dir: Path,
    today: str,
    logger: logging.Logger,
    llm_error: str = "",
    llm_model: str = "",
) -> Path:
    """Write the weekly report markdown file."""
    reports_dir.mkdir(parents=True, exist_ok=True)
    report_path = reports_dir / f"{today}-weekly-research.md"

    if llm_error:
        llm_status = f"ERRO — {llm_error}"
    elif llm_model:
        llm_status = f"OK — `{llm_model}` analisou {len(all_results)} resultados e identificou {len(new_items)} item(ns) novo(s)"
    else:
        llm_status = "não executada (Ollama indisponível)"

    lines = [
        f"# Weekly LLM Research Report — {today}",
        "",
        f"**Pesquisa executada em:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"**Queries executadas:** {len(queries)}",
        f"**Resultados brutos coletados:** {len(all_results)}",
        f"**Análise LLM:** {llm_status}",
        f"**Novos itens identificados:** {len(new_items)}",
        "",
        "## Queries Executadas",
        "",
    ]
    for q in queries:
        lines.append(f"- `{q}`")

    lines += ["", "## Novos Itens Encontrados", ""]

    if llm_error:
        lines.append(f"> **Erro na análise LLM:** {llm_error}")
        lines.append(">")
        lines.append("> Os resultados de busca foram coletados mas não puderam ser analisados.")
        lines.append("> Verifique os logs e re-execute manualmente se necessário.")
        lines.append("")
    if not new_items and not llm_error:
        lines.append("_Nenhum item novo identificado nesta semana._")
    elif not new_items:
        lines.append("_Nenhum item extraído — ver erro acima._")
    else:
        for item in new_items:
            lines.append(format_item_markdown(item))
            lines.append("")

    analyzed = all_results[:40]
    lines += [
        f"## Resultados Analisados pelo LLM ({len(analyzed)} de {len(all_results)})",
        "",
        "_Exatamente o que foi enviado ao modelo para análise:_",
        "",
    ]
    for i, r in enumerate(analyzed, 1):
        title = r.get("title", "(sem título)")
        url = r.get("url", "")
        snippet = r.get("snippet", "").strip()[:300]
        query = r.get("query", "")
        lines.append(f"**{i}. {title}**")
        if url:
            lines.append(f"<{url}>")
        if query:
            lines.append(f"_Query: `{query}`_")
        if snippet:
            lines.append(f"> {snippet}")
        lines.append("")

    content = "\n".join(lines) + "\n"
    report_path.write_text(content, encoding="utf-8")
    logger.info("Report written: %s", report_path)
    return report_path


# ---------------------------------------------------------------------------
# Backlog updater
# ---------------------------------------------------------------------------
BACKLOG_SECTION = "## Novos itens pendentes de avaliacao"

INITIAL_BACKLOG = """\
# Backlog — SDLC Agentico Local

Ferramentas, modelos e abordagens para ciclo de desenvolvimento de software
com LLMs locais. Hardware de referencia: RTX 5060 Ti 16GB VRAM, 32GB RAM.

---

## Itens em avaliacao

_Adicione aqui itens que estao sendo testados ativamente._

---

## Novos itens pendentes de avaliacao

_Itens descobertos pela pesquisa semanal automatica._

---

## Descartados

- **Cline** — requer VS Code + cloud LLM por padrao, nao alinha com setup local
- **Continue.dev** — extensao de IDE focada em cloud, integracao local limitada
"""


def update_backlog(
    backlog_path: Path,
    new_items: list[dict],
    today: str,
    logger: logging.Logger,
) -> None:
    """Append new items to the backlog under the pending section."""
    if not new_items:
        logger.info("No new items to add to backlog.")
        return

    # Ensure backlog exists
    if not backlog_path.exists():
        backlog_path.parent.mkdir(parents=True, exist_ok=True)
        backlog_path.write_text(INITIAL_BACKLOG, encoding="utf-8")
        logger.info("Created initial backlog at %s", backlog_path)

    current = backlog_path.read_text(encoding="utf-8")

    # Build block to insert
    block_lines = [f"\n### Pesquisa de {today}\n"]
    for item in new_items:
        block_lines.append(format_item_markdown(item))
        block_lines.append("")
    block = "\n".join(block_lines)

    # Insert after the section header
    if BACKLOG_SECTION in current:
        insert_after = BACKLOG_SECTION
        idx = current.index(insert_after) + len(insert_after)
        updated = current[:idx] + "\n" + block + current[idx:]
    else:
        # Append new section at end
        updated = current.rstrip() + f"\n\n{BACKLOG_SECTION}\n{block}\n"

    # Idempotency: do not re-add if today's block already present
    marker = f"### Pesquisa de {today}"
    if marker in current:
        logger.info("Backlog already contains entries for %s — skipping.", today)
        return

    backlog_path.write_text(updated, encoding="utf-8")
    logger.info("Backlog updated with %d new items.", len(new_items))


# ---------------------------------------------------------------------------
# Telegram notification
# ---------------------------------------------------------------------------
def send_telegram(
    new_items: list[dict],
    today: str,
    logger: logging.Logger,
    *,
    queries: list[str],
    known_count: int,
    raw_result_count: int,
    model: str,
    report_path=None,
    llm_error: str = "",
) -> None:
    """Send a Telegram message via the Hermes bot, with run metadata and the report attached."""
    params_block = (
        "\n--- Parâmetros desta execução ---\n"
        "Período de busca: último ano (SearXNG time_range=year), "
        f"deduplicado contra {known_count} item(ns) já no backlog\n"
        f"Queries ({len(queries)}):\n" + "\n".join(f"  • {q}" for q in queries) + "\n"
        f"Resultados brutos coletados: {raw_result_count}\n"
        f"Modelo de análise: {model or '(nenhum — Ollama indisponível)'}"
    )

    if llm_error:
        text = (
            f"⚠️ Weekly LLM Research — {today}\n\n"
            f"FALHA na análise LLM: {llm_error}\n"
            f"{params_block}"
        )
    elif not new_items:
        text = (
            f"Weekly LLM Research — {today}\n\n"
            "Nenhum item novo encontrado esta semana.\n"
            f"{params_block}"
        )
    else:
        lines = [f"Weekly LLM Research — {today}", f"\n{len(new_items)} novo(s) item(ns) encontrado(s):\n"]
        for i, item in enumerate(new_items, 1):
            name = item.get("name", "?")
            itype = item.get("type", "-")
            sdlc = item.get("sdlc_relevance", "-")
            hw = item.get("hw_viability", "-")
            desc = item.get("description", "")[:120]
            lines.append(f"{i}. {name} ({itype})")
            lines.append(f"   SDLC {sdlc}/5 | HW {hw}/5")
            lines.append(f"   {desc}")
        lines.append(params_block)
        text = "\n".join(lines)

    if not send_telegram_message(text, logger):
        logger.error(
            "Falha ao enviar a notificação Telegram — ninguém será avisado do resultado desta execução."
        )
    if report_path is not None:
        caption = f"⚠️ Relatório com erro — {today}" if llm_error else f"Relatório completo — {today}"
        if not send_telegram_document(report_path, caption=caption, logger=logger):
            logger.error("Falha ao anexar o relatório no Telegram.")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> int:
    """Run the agent, guaranteeing a Telegram alert even on an unhandled crash."""
    try:
        return _run()
    except Exception as exc:
        logging.getLogger("research_agent").exception("Agent crashed unexpectedly.")
        send_telegram_message(
            f"🔥 Weekly LLM Research — CRASH\n\nO agente quebrou antes de terminar: {exc}",
            logger=None,
        )
        raise


def _run() -> int:
    cfg = load_config()
    logger = setup_logging(cfg.get("log_file", "research.log"))
    today = datetime.now().strftime("%Y-%m-%d")

    logger.info("=== Weekly SDLC Research Agent starting — %s ===", today)

    # Resolve paths relative to script directory
    backlog_path = (SCRIPT_DIR / cfg["backlog_path"]).resolve()
    reports_dir = (SCRIPT_DIR / cfg["reports_dir"]).resolve()

    # 1. Read backlog
    backlog_text = read_backlog(backlog_path, logger)
    known_items = extract_known_items(backlog_text, cfg.get("known_discarded", []))
    logger.info("Known items in backlog: %d", len(known_items))

    # 2. Run searches
    queries = cfg.get("search_queries", [])
    all_results = run_searches(queries, cfg, logger)

    # Zero resultados em todas as queries é indistinguível de uma indisponibilidade
    # completa dos backends de busca; não registrar isso como execução saudável.
    if not all_results:
        search_error = "Nenhum resultado foi retornado pelos backends de busca."
        logger.error(search_error)
        report_path = write_report(
            [], all_results, queries, reports_dir, today, logger,
            llm_error=search_error,
            llm_model="",
        )
        send_telegram(
            [],
            today,
            logger,
            queries=queries,
            known_count=len(known_items),
            raw_result_count=0,
            model="",
            report_path=report_path,
            llm_error=search_error,
        )
        return 1

    # 3. Check Ollama
    models = pick_models(cfg, logger)
    if not models:
        no_model_error = "Ollama indisponível ou nenhum modelo configurado está instalado."
        logger.error(
            "Ollama not available or no models installed. "
            "Writing raw results to report without LLM analysis."
        )
        report_path = write_report(
            [], all_results, queries, reports_dir, today, logger,
            llm_error=no_model_error,
            llm_model="",
        )
        send_telegram(
            [],
            today,
            logger,
            queries=queries,
            known_count=len(known_items),
            raw_result_count=len(all_results),
            model="",
            report_path=report_path,
            llm_error=no_model_error,
        )
        logger.info("Done (no LLM analysis).")
        return 1

    # 4. LLM analysis
    raw_items, llm_error, used_model = analyze_results(
        all_results,
        known_items,
        cfg.get("hardware_context", ""),
        models,
        cfg["ollama_url"],
        logger,
        options=cfg.get(
            "ollama_options",
            {"temperature": 0.2, "num_ctx": 8192, "num_predict": 1536},
        ),
        timeout_seconds=int(cfg.get("ollama_timeout_seconds", 240)),
    )

    # 5. Filter duplicates
    new_items = filter_new_items(raw_items, known_items, logger)

    # 6. Write report
    report_path = write_report(
        new_items, all_results, queries, reports_dir, today, logger,
        llm_error=llm_error,
        llm_model=used_model,
    )

    # 7. Update backlog
    update_backlog(backlog_path, new_items, today, logger)

    # 8. Notify via Telegram
    send_telegram(
        new_items,
        today,
        logger,
        queries=queries,
        known_count=len(known_items),
        raw_result_count=len(all_results),
        model=used_model,
        report_path=report_path,
        llm_error=llm_error,
    )

    logger.info("=== Agent finished. Report: %s ===", report_path)
    return 1 if llm_error else 0


if __name__ == "__main__":
    sys.exit(main())
