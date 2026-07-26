#!/usr/bin/env python3
"""
Weekly Cost-Benefit Analysis Agent
Searches for published AI-assisted software development setups/environments,
and evaluates the cost-benefit of each: local hardware vs paid licenses
(Anthropic, OpenAI Codex, Google Antigravity, Cursor, Copilot, etc.).
Mirrors the pipeline of agents/weekly-sdlc-research, with a different output.
"""

import json
import logging
import math
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
    logger = logging.getLogger("cost_benefit_agent")
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
# Ledger reader
# ---------------------------------------------------------------------------
def read_ledger(ledger_path: Path, logger: logging.Logger) -> str:
    """Return the full ledger text, or empty string if not found."""
    if not ledger_path.exists():
        logger.info("Ledger not found at %s — will create it", ledger_path)
        return ""
    try:
        return ledger_path.read_text(encoding="utf-8")
    except Exception as exc:
        logger.warning("Could not read ledger: %s", exc)
        return ""


def _is_noise_capture(name: str) -> bool:
    """True for captures that are markdown structure, not setup names
    (field labels like 'Tipo:', table separators like '---')."""
    if not name:
        return True
    if name.endswith(":"):
        return True
    if re.fullmatch(r"[-\s]+", name):
        return True
    return False


def extract_known_items(ledger_text: str, known_evaluated: list[str]) -> set[str]:
    """Extract setup names already in the ledger (lowercased)."""
    known: set[str] = set()
    for name in known_evaluated:
        known.add(name.lower())
    # Capture markdown headings and bold text as known names
    patterns = [
        r"###\s+(.+)",
        r"\*\*(.+?)\*\*",
        r"^\|\s*([^|]+?)\s*\|",  # table cells (first column)
    ]
    for pat in patterns:
        for match in re.finditer(pat, ledger_text, re.MULTILINE):
            name = match.group(1).strip()
            if _is_noise_capture(name):
                continue
            known.add(name.lower())
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
        "think": False,
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
# Pricing reference formatting
# ---------------------------------------------------------------------------
def format_pricing_reference(pricing: dict) -> str:
    """Render the pricing_reference config block as text for the prompt."""
    if not pricing:
        return "(no pricing reference available)"
    lines = [f"Reference date: {pricing.get('reference_date', '?')}"]
    lines.append(
        f"Energy cost: R$ {pricing.get('energy_cost_kwh_brl', '?')}/kWh"
        f" | USD/BRL: {pricing.get('usd_brl', '?')}"
    )
    lines.append("LOCAL HARDWARE options (buy once + monthly energy):")
    for hw in pricing.get("local_hardware", []):
        lines.append(
            f"- {hw['name']}: CAPEX US$ {hw['capex_usd']},"
            f" OPEX US$ {hw['opex_month_usd']}/month"
        )
    lines.append("PAID LICENSES (monthly subscription, no hardware needed):")
    for lic in pricing.get("paid_licenses", []):
        lines.append(f"- {lic['name']}: US$ {lic['opex_month_usd']}/month")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# LLM analysis
# ---------------------------------------------------------------------------
ANALYSIS_PROMPT = """\
You are a cost-benefit analyst for a home AI lab running {hardware}.

Given the following web search results about AI-assisted software development
setups and environments (vibe coding stacks, agentic coding assistants, local
LLM rigs, paid subscription tools), identify published SETUPS or ENVIRONMENTS
and evaluate the COST-BENEFIT of each one.

For every setup, compare TWO scenarios:
- LOCAL: buying/using local hardware and open models (Ollama etc.)
- PAID: paying for licenses/subscriptions (Anthropic Claude, OpenAI Codex,
  Google Antigravity/Gemini, Cursor, GitHub Copilot, etc.)

PRICING REFERENCE (use these numbers as the baseline for estimates):
{pricing_reference}

ALREADY EVALUATED setups (skip these — do not include them):
{known_items}

SEARCH RESULTS:
{search_results}

For each NEW and relevant setup you find, output a JSON array. Each element must have:
{{
  "name": "Setup or environment name",
  "setup_type": "local | paid | hybrid",
  "capex_usd": <integer, upfront cost in USD (hardware, 0 if pure subscription)>,
  "opex_month_usd": <integer, monthly cost in USD (licenses, API, energy)>,
  "velocity_score": <integer 1-5, speed of software output>,
  "quality_score": <integer 1-5, quality of software output>,
  "verdict": "local | paid | hybrid",
  "rationale": "One or two sentences: why this verdict, cost vs benefit.",
  "source_url": "URL from the search results if available, else empty string"
}}

Do NOT compute breakeven_months yourself — it is derived deterministically
from capex_usd/opex_month_usd after your response, so omit it.

velocity_score: 5 = ships features very fast, 1 = slow/manual.
quality_score: 5 = production-grade output, 1 = prototype-only.
verdict: which scenario wins for this setup given the pricing reference.

Output ONLY the JSON array — no prose, no markdown fences, no explanation.
If there are no new relevant setups, output an empty array: []
"""


def analyze_results(
    search_results: list[dict],
    known_items: set[str],
    hardware_context: str,
    pricing_reference: str,
    model: str,
    ollama_url: str,
    logger: logging.Logger,
) -> tuple[list[dict], str]:
    """Use LLM to evaluate cost-benefit of found setups. Returns (items, error_message)."""
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
        pricing_reference=pricing_reference,
        known_items=known_list,
        search_results=search_block,
    )

    logger.info("Sending %d results to LLM for cost-benefit analysis...", len(search_results))
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
        logger.info("LLM evaluated %d new setups.", len(items))
        return items, ""
    except json.JSONDecodeError as exc:
        logger.error("JSON parse error: %s\nRaw snippet: %s", exc, match.group(0)[:500])
        return [], f"Erro ao parsear JSON do LLM: {exc}"


# ---------------------------------------------------------------------------
# Deterministic breakeven calculation
# ---------------------------------------------------------------------------
def compute_breakeven_months(item: dict, pricing: dict) -> int:
    """Months until capex_usd pays off vs the cheapest paid license, given the
    monthly savings (cheapest_paid - opex_month_usd). Returns -1 when the local
    option never pays off (no monthly savings, or no capex to recoup against a
    pricier opex).

    Computed in Python rather than trusted from the LLM, since arithmetic like
    this is a common failure mode for smaller local models.
    """
    capex = item.get("capex_usd") or 0
    opex_local = item.get("opex_month_usd") or 0
    licenses = pricing.get("paid_licenses", [])
    if not licenses:
        return -1
    cheapest_paid = min(lic["opex_month_usd"] for lic in licenses)

    if capex <= 0:
        return 0 if opex_local <= cheapest_paid else -1

    monthly_savings = cheapest_paid - opex_local
    if monthly_savings <= 0:
        return -1
    return math.ceil(capex / monthly_savings)


def _format_breakeven(value) -> str:
    """'nunca' for -1 (never pays off), '<N>m' otherwise."""
    try:
        v = int(value)
    except (TypeError, ValueError):
        return "-"
    return "nunca" if v < 0 else f"{v}m"


def _escape_md_cell(value) -> str:
    """Escape pipe characters so free-text values can't break a Markdown table row."""
    return str(value).replace("|", "\\|")


# ---------------------------------------------------------------------------
# Deduplication against ledger
# ---------------------------------------------------------------------------
def filter_new_items(
    items: list[dict], known_items: set[str], logger: logging.Logger
) -> list[dict]:
    """Remove items whose name already appears in the ledger."""
    new_items = []
    for item in items:
        name = item.get("name", "").strip()
        if name.lower() in known_items:
            logger.debug("Skipping already-evaluated setup: %s", name)
        else:
            new_items.append(item)
    logger.info("%d items after dedup: %d new", len(items), len(new_items))
    return new_items


# ---------------------------------------------------------------------------
# Report generation
# ---------------------------------------------------------------------------
def format_item_markdown(item: dict) -> str:
    name = item.get("name", "Unknown")
    stype = item.get("setup_type", "-")
    capex = item.get("capex_usd", "-")
    opex = item.get("opex_month_usd", "-")
    velocity = item.get("velocity_score", "-")
    quality = item.get("quality_score", "-")
    breakeven = _format_breakeven(item.get("breakeven_months", "-"))
    verdict = item.get("verdict", "-")
    rationale = item.get("rationale", "")
    url = item.get("source_url", "")

    lines = [
        f"### {name}",
        f"- **Tipo:** {stype}",
        f"- **CAPEX:** US$ {capex}",
        f"- **OPEX:** US$ {opex}/mes",
        f"- **Velocidade:** {velocity}/5 | **Qualidade:** {quality}/5",
        f"- **Breakeven local vs pago:** {breakeven}",
        f"- **Veredito:** {verdict}",
        f"- **Justificativa:** {rationale}",
    ]
    if url:
        lines.append(f"- **Fonte:** {url}")
    return "\n".join(lines)


def format_summary_table(items: list[dict]) -> list[str]:
    """Comparative table of all evaluated setups."""
    lines = [
        "| Setup | Tipo | CAPEX (US$) | OPEX (US$/mes) | Vel. | Qual. | Breakeven | Veredito |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for item in items:
        lines.append(
            f"| {_escape_md_cell(item.get('name', '?'))} "
            f"| {_escape_md_cell(item.get('setup_type', '-'))} "
            f"| {item.get('capex_usd', '-')} "
            f"| {item.get('opex_month_usd', '-')} "
            f"| {item.get('velocity_score', '-')}/5 "
            f"| {item.get('quality_score', '-')}/5 "
            f"| {_format_breakeven(item.get('breakeven_months', '-'))} "
            f"| {_escape_md_cell(item.get('verdict', '-'))} |"
        )
    return lines


def write_report(
    new_items: list[dict],
    all_results: list[dict],
    queries: list[str],
    pricing_reference: str,
    reports_dir: Path,
    today: str,
    logger: logging.Logger,
    llm_error: str = "",
    llm_model: str = "",
) -> Path:
    """Write the weekly cost-benefit report markdown file."""
    reports_dir.mkdir(parents=True, exist_ok=True)
    report_path = reports_dir / f"{today}-cost-benefit.md"

    if llm_error:
        llm_status = f"ERRO — {llm_error}"
    elif llm_model:
        llm_status = f"OK — `{llm_model}` analisou {len(all_results)} resultados e avaliou {len(new_items)} setup(s) novo(s)"
    else:
        llm_status = "não executada (Ollama indisponível)"

    lines = [
        f"# Weekly Cost-Benefit Report — {today}",
        "",
        f"**Analise executada em:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"**Queries executadas:** {len(queries)}",
        f"**Resultados brutos coletados:** {len(all_results)}",
        f"**Análise LLM:** {llm_status}",
        f"**Setups avaliados:** {len(new_items)}",
        "",
        "## Base de Precos Utilizada",
        "",
        "```",
        pricing_reference,
        "```",
        "",
        "## Comparativo",
        "",
    ]

    if llm_error:
        lines.append(f"> **Erro na análise LLM:** {llm_error}")
        lines.append(">")
        lines.append("> Os resultados de busca foram coletados mas não puderam ser analisados.")
        lines.append("> Verifique os logs e re-execute manualmente se necessário.")
        lines.append("")
    if not new_items and not llm_error:
        lines.append("_Nenhum setup novo avaliado nesta semana._")
    elif not new_items:
        lines.append("_Nenhum setup extraído — ver erro acima._")
    else:
        lines += format_summary_table(new_items)
        lines += ["", "## Avaliacoes Detalhadas", ""]
        for item in new_items:
            lines.append(format_item_markdown(item))
            lines.append("")

    lines += [
        "## Queries Executadas",
        "",
    ]
    for q in queries:
        lines.append(f"- `{q}`")

    lines += [
        "",
        "## Fontes Consultadas",
        "",
    ]
    seen_urls: set[str] = set()
    for r in all_results[:20]:
        url = r.get("url", "")
        if url and url not in seen_urls:
            seen_urls.add(url)
            title = r.get("title", url)[:80]
            lines.append(f"- [{title}]({url})")

    content = "\n".join(lines) + "\n"
    report_path.write_text(content, encoding="utf-8")
    logger.info("Report written: %s", report_path)
    return report_path


# ---------------------------------------------------------------------------
# Ledger updater
# ---------------------------------------------------------------------------
LEDGER_SECTION = "## Setups avaliados"

INITIAL_LEDGER = """\
# Custo-Beneficio — Ambientes de Desenvolvimento com LLMs

Avaliacoes de custo-beneficio de setups publicados: hardware local vs licencas
pagas (Anthropic, OpenAI Codex, Google Antigravity, Cursor, Copilot).
Hardware de referencia: RTX 5060 Ti 16GB VRAM, 32GB RAM.

Gerado pelo agente semanal em `agents/weekly-cost-benefit/`.

---

## Setups avaliados

_Setups avaliados pela analise semanal automatica._

---

## Descartados

_Setups julgados irrelevantes ou duplicados._
"""


def update_ledger(
    ledger_path: Path,
    new_items: list[dict],
    today: str,
    logger: logging.Logger,
) -> None:
    """Append new evaluations to the ledger under the evaluated section."""
    if not new_items:
        logger.info("No new items to add to ledger.")
        return

    # Ensure ledger exists
    if not ledger_path.exists():
        ledger_path.parent.mkdir(parents=True, exist_ok=True)
        ledger_path.write_text(INITIAL_LEDGER, encoding="utf-8")
        logger.info("Created initial ledger at %s", ledger_path)

    current = ledger_path.read_text(encoding="utf-8")

    # Idempotency: do not re-add if today's block already present
    marker = f"### Analise de {today}"
    if marker in current:
        logger.info("Ledger already contains entries for %s — skipping.", today)
        return

    # Build block to insert
    block_lines = [f"\n### Analise de {today}\n"]
    block_lines += format_summary_table(new_items)
    block_lines.append("")
    for item in new_items:
        block_lines.append(format_item_markdown(item))
        block_lines.append("")
    block = "\n".join(block_lines)

    # Insert after the section header
    if LEDGER_SECTION in current:
        insert_after = LEDGER_SECTION
        idx = current.index(insert_after) + len(insert_after)
        updated = current[:idx] + "\n" + block + current[idx:]
    else:
        # Append new section at end
        updated = current.rstrip() + f"\n\n{LEDGER_SECTION}\n{block}\n"

    ledger_path.write_text(updated, encoding="utf-8")
    logger.info("Ledger updated with %d new evaluations.", len(new_items))


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
        f"deduplicado contra {known_count} setup(s) já no ledger\n"
        f"Queries ({len(queries)}):\n" + "\n".join(f"  • {q}" for q in queries) + "\n"
        f"Resultados brutos coletados: {raw_result_count}\n"
        f"Modelo de análise: {model or '(nenhum — Ollama indisponível)'}"
    )

    if llm_error:
        text = (
            f"⚠️ Weekly Cost-Benefit — {today}\n\n"
            f"FALHA na análise LLM: {llm_error}\n"
            f"{params_block}"
        )
    elif not new_items:
        text = (
            f"Weekly Cost-Benefit — {today}\n\n"
            "Nenhum setup novo avaliado esta semana.\n"
            f"{params_block}"
        )
    else:
        lines = [f"Weekly Cost-Benefit — {today}", f"\n{len(new_items)} setup(s) avaliado(s):\n"]
        for i, item in enumerate(new_items, 1):
            name = item.get("name", "?")
            stype = item.get("setup_type", "-")
            capex = item.get("capex_usd", "-")
            opex = item.get("opex_month_usd", "-")
            verdict = item.get("verdict", "-")
            breakeven = _format_breakeven(item.get("breakeven_months", "-"))
            lines.append(f"{i}. {name} ({stype})")
            lines.append(f"   CAPEX US$ {capex} | OPEX US$ {opex}/mes")
            lines.append(f"   Breakeven {breakeven} | Veredito: {verdict}")
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
        logging.getLogger("cost_benefit_agent").exception("Agent crashed unexpectedly.")
        send_telegram_message(
            f"🔥 Weekly Cost-Benefit — CRASH\n\nO agente quebrou antes de terminar: {exc}",
            logger=None,
        )
        raise


def _run() -> None:
    cfg = load_config()
    logger = setup_logging(cfg.get("log_file", "cost-benefit.log"))
    today = datetime.now().strftime("%Y-%m-%d")

    logger.info("=== Weekly Cost-Benefit Agent starting — %s ===", today)

    # Resolve paths relative to script directory
    ledger_path = (SCRIPT_DIR / cfg["ledger_path"]).resolve()
    reports_dir = (SCRIPT_DIR / cfg["reports_dir"]).resolve()

    # 1. Read ledger
    ledger_text = read_ledger(ledger_path, logger)
    known_items = extract_known_items(ledger_text, cfg.get("known_evaluated", []))
    logger.info("Known setups in ledger: %d", len(known_items))

    # 2. Format pricing reference
    pricing_reference = format_pricing_reference(cfg.get("pricing_reference", {}))

    # 3. Run searches
    queries = cfg.get("search_queries", [])
    all_results = run_searches(queries, cfg, logger)

    # 4. Check Ollama
    model = pick_model(cfg, logger)
    if model is None:
        no_model_error = "Ollama indisponível ou sem modelos instalados."
        logger.error(
            "Ollama not available or no models installed. "
            "Writing raw results to report without LLM analysis."
        )
        report_path = write_report(
            [], all_results, queries, pricing_reference, reports_dir, today, logger,
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

    # 5. LLM cost-benefit analysis
    raw_items, llm_error = analyze_results(
        all_results,
        known_items,
        cfg.get("hardware_context", ""),
        pricing_reference,
        model,
        cfg["ollama_url"],
        logger,
    )

    # 6. Filter duplicates
    new_items = filter_new_items(raw_items, known_items, logger)

    # 6b. Recompute breakeven deterministically (do not trust LLM arithmetic)
    pricing_cfg = cfg.get("pricing_reference", {})
    for item in new_items:
        item["breakeven_months"] = compute_breakeven_months(item, pricing_cfg)

    # 7. Write report
    report_path = write_report(
        new_items, all_results, queries, pricing_reference, reports_dir, today, logger,
        llm_error=llm_error,
        llm_model=model,
    )

    # 8. Update ledger
    update_ledger(ledger_path, new_items, today, logger)

    # 9. Notify via Telegram
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
