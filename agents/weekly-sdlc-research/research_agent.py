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

import requests
import yaml
from ddgs import DDGS

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
        r"^\|\s*([^|]+?)\s*\|",  # table cells (first column)
    ]
    for pat in patterns:
        for match in re.finditer(pat, backlog_text, re.MULTILINE):
            known.add(match.group(1).strip().lower())
    return known


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


def pick_model(cfg: dict, logger: logging.Logger) -> str | None:
    """Pick preferred model, fallback, or whatever is installed."""
    ollama_url = cfg["ollama_url"]
    models = check_ollama(ollama_url, logger)
    if not models:
        return None

    preferred = cfg.get("ollama_model", "")
    fallback = cfg.get("ollama_fallback_model", "")

    for candidate in [preferred, fallback]:
        if not candidate:
            continue
        # Exact match first
        if candidate in models:
            logger.info("Using model: %s", candidate)
            return candidate
        # Prefix match as fallback (e.g. "qwen2.5-coder:14b" prefix "qwen2.5-coder")
        prefix = candidate.split(":")[0]
        tag = candidate.split(":")[-1] if ":" in candidate else ""
        for installed in models:
            installed_prefix = installed.split(":")[0]
            installed_tag = installed.split(":")[-1] if ":" in installed else ""
            if installed_prefix == prefix and installed_tag == tag:
                logger.info("Using model: %s", installed)
                return installed
        # Looser prefix match only if no tag-matching candidate found
        for installed in models:
            if installed.startswith(prefix + ":"):
                logger.warning(
                    "Exact model '%s' not found; using '%s' (prefix match).",
                    candidate, installed,
                )
                return installed

    if models:
        logger.warning(
            "Preferred model '%s' (or fallback '%s') not found; using first available "
            "as last resort: %s — may be unsuitable for this task (e.g. embedding/vision model).",
            preferred, fallback, models[0],
        )
        return models[0]
    return None


def ollama_chat(
    model: str, prompt: str, ollama_url: str, logger: logging.Logger
) -> str:
    """Send a prompt to Ollama and return the response text."""
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        "options": {"temperature": 0.2, "num_predict": 4096},
    }
    try:
        resp = requests.post(
            f"{ollama_url}/api/chat", json=payload, timeout=300
        )
        resp.raise_for_status()
        return resp.json()["message"]["content"].strip()
    except Exception as exc:
        logger.error("Ollama request failed: %s", exc)
        raise


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
    model: str,
    ollama_url: str,
    logger: logging.Logger,
) -> tuple[list[dict], str]:
    """Use LLM to filter and evaluate search results. Returns (items, error_message)."""
    if not search_results:
        logger.info("No search results to analyze.")
        return [], ""

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

    logger.info("Sending %d results to LLM for analysis...", len(search_results))
    try:
        raw = ollama_chat(model, prompt, ollama_url, logger)
    except Exception as exc:
        return [], f"LLM ({model}) falhou: {exc}"

    if not raw:
        logger.warning("LLM returned empty response.")
        return [], f"LLM ({model}) retornou resposta vazia — verifique se o modelo está disponível."

    # Extract JSON array robustly
    # Strip markdown fences if present
    cleaned = re.sub(r"```(?:json)?\s*", "", raw)
    cleaned = re.sub(r"```", "", cleaned).strip()

    # Find first [ ... ] block
    match = re.search(r"\[.*\]", cleaned, re.DOTALL)
    if not match:
        logger.warning("Could not find JSON array in LLM response. Raw: %s", raw[:500])
        return [], "LLM não retornou JSON válido — resposta inesperada."

    try:
        items = json.loads(match.group(0))
        if not isinstance(items, list):
            logger.warning("LLM JSON was not a list.")
            return [], "LLM retornou JSON mas não como array."
        logger.info("LLM identified %d new items.", len(items))
        return items, ""
    except json.JSONDecodeError as exc:
        logger.error("JSON parse error: %s\nRaw snippet: %s", exc, match.group(0)[:500])
        return [], f"Erro ao parsear JSON do LLM: {exc}"


# ---------------------------------------------------------------------------
# Deduplication against backlog
# ---------------------------------------------------------------------------
def filter_new_items(
    items: list[dict], known_items: set[str], logger: logging.Logger
) -> list[dict]:
    """Remove items whose name already appears in the backlog."""
    new_items = []
    for item in items:
        name = item.get("name", "").strip()
        if name.lower() in known_items:
            logger.debug("Skipping already-known item: %s", name)
        else:
            new_items.append(item)
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
def main() -> None:
    """Run the agent, guaranteeing a Telegram alert even on an unhandled crash."""
    try:
        _run()
    except Exception as exc:
        logging.getLogger("research_agent").exception("Agent crashed unexpectedly.")
        send_telegram_message(
            f"🔥 Weekly LLM Research — CRASH\n\nO agente quebrou antes de terminar: {exc}",
            logger=None,
        )
        raise


def _run() -> None:
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

    # 3. Check Ollama
    model = pick_model(cfg, logger)
    if model is None:
        no_model_error = "Ollama indisponível ou sem modelos instalados."
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
        return

    # 4. LLM analysis
    raw_items, llm_error = analyze_results(
        all_results,
        known_items,
        cfg.get("hardware_context", ""),
        model,
        cfg["ollama_url"],
        logger,
    )

    # 5. Filter duplicates
    new_items = filter_new_items(raw_items, known_items, logger)

    # 6. Write report
    report_path = write_report(
        new_items, all_results, queries, reports_dir, today, logger,
        llm_error=llm_error,
        llm_model=model,
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
        model=model,
        report_path=report_path,
        llm_error=llm_error,
    )

    logger.info("=== Agent finished. Report: %s ===", report_path)


if __name__ == "__main__":
    main()
