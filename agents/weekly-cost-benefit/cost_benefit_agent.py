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
from urllib.parse import urlsplit, urlunsplit

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
        cfg = yaml.safe_load(f)
    validate_config(cfg)
    return cfg


def validate_config(cfg: dict) -> None:
    """Fail early when an input could make the scheduled run misleading."""
    if not isinstance(cfg, dict):
        raise ValueError("config.yaml must contain a mapping")

    required_paths = (
        "ollama_url",
        "ollama_model",
        "ollama_fallback_model",
        "ledger_path",
        "reports_dir",
    )
    for key in required_paths:
        if not isinstance(cfg.get(key), str) or not cfg[key].strip():
            raise ValueError(f"missing or invalid config value: {key}")
    if cfg["ollama_model"] == cfg["ollama_fallback_model"]:
        raise ValueError("ollama_model and ollama_fallback_model must be different exact tags")

    inference = cfg.get("inference", {})
    for key, minimum, maximum in (
        ("num_ctx", 2048, 32768),
        ("num_predict", 128, 4096),
        ("timeout_seconds", 30, 600),
    ):
        value = inference.get(key)
        if not isinstance(value, int) or not minimum <= value <= maximum:
            raise ValueError(f"inference.{key} must be an integer from {minimum} to {maximum}")
    temperature = inference.get("temperature")
    if (
        isinstance(temperature, bool)
        or not isinstance(temperature, (int, float))
        or not 0 <= temperature <= 1
    ):
        raise ValueError("inference.temperature must be a number from 0 to 1")

    for url_key in ("ollama_url", "searxng_url"):
        url = cfg.get(url_key, "")
        if url and urlsplit(url).scheme not in {"http", "https"}:
            raise ValueError(f"{url_key} must be an http(s) URL")

    pricing = cfg.get("pricing_reference")
    valid_reference_date = isinstance(pricing, dict) and re.fullmatch(
        r"\d{4}-\d{2}", str(pricing.get("reference_date", ""))
    )
    if not valid_reference_date:
        raise ValueError("pricing_reference.reference_date must use YYYY-MM")
    try:
        datetime.strptime(pricing["reference_date"], "%Y-%m")
    except ValueError as exc:
        raise ValueError("pricing_reference.reference_date is not a valid month") from exc
    for section in ("local_hardware", "paid_licenses"):
        if not isinstance(pricing.get(section), list) or not pricing[section]:
            raise ValueError(f"pricing_reference.{section} must be a non-empty list")
        for item in pricing[section]:
            if not isinstance(item, dict) or not isinstance(item.get("name"), str):
                raise ValueError(f"pricing_reference.{section} contains an invalid item")
            capex_keys = ("capex_usd",) if section == "local_hardware" else ()
            for cost_key in ("opex_month_usd",) + capex_keys:
                value = item.get(cost_key)
                invalid_cost = (
                    isinstance(value, bool)
                    or not isinstance(value, (int, float))
                    or value < 0
                )
                if invalid_cost:
                    raise ValueError(
                        f"pricing_reference.{section}.{cost_key} must be non-negative"
                    )

    search = cfg.get("search", {})
    if search.get("time_range") not in {"day", "week", "month", "year"}:
        raise ValueError("search.time_range must be day, week, month, or year")
    max_results = search.get("max_results_per_query")
    if not isinstance(max_results, int) or not 1 <= max_results <= 20:
        raise ValueError("search.max_results_per_query must be an integer from 1 to 20")
    delay = search.get("delay_seconds")
    if isinstance(delay, bool) or not isinstance(delay, (int, float)) or not 0 <= delay <= 10:
        raise ValueError("search.delay_seconds must be a number from 0 to 10")
    if not cfg.get("search_queries") and not cfg.get("search_query_groups"):
        raise ValueError("at least one search query must be configured")
    if not isinstance(cfg.get("search_queries", []), list) or not all(
        isinstance(query, str) for query in cfg.get("search_queries", [])
    ):
        raise ValueError("search_queries must be a list of strings")
    groups = cfg.get("search_query_groups", [])
    if not isinstance(groups, list) or not all(
        isinstance(group, list) and group and all(isinstance(query, str) for query in group)
        for group in groups
    ):
        raise ValueError("search_query_groups must be a list of non-empty string lists")


# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------
def setup_logging(log_file: str) -> logging.Logger:
    log_path = SCRIPT_DIR / log_file
    logger = logging.getLogger("cost_benefit_agent")
    logger.setLevel(logging.DEBUG)
    logger.handlers.clear()

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
def search_searxng(
    query: str,
    base_url: str,
    logger: logging.Logger,
    *,
    time_range: str = "month",
    max_results: int = 6,
) -> list[dict]:
    """Search via local SearXNG instance."""
    params = {"q": query, "format": "json", "language": "en", "time_range": time_range}
    url = f"{base_url.rstrip('/')}/search"
    try:
        resp = requests.get(url, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        results = []
        for item in data.get("results", [])[:max_results]:
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


def search_duckduckgo(
    query: str,
    logger: logging.Logger,
    *,
    time_range: str = "month",
    max_results: int = 6,
) -> list[dict]:
    """Search via duckduckgo-search library."""
    try:
        with DDGS() as ddgs:
            timelimit = {"day": "d", "week": "w", "month": "m", "year": "y"}.get(
                time_range, "m"
            )
            hits = list(ddgs.text(query, max_results=max_results, timelimit=timelimit))
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
    search_cfg = cfg.get("search", {})
    time_range = search_cfg.get("time_range", "month")
    max_results = search_cfg.get("max_results_per_query", 6)
    delay = search_cfg.get("delay_seconds", 0.5)

    for query in queries:
        logger.info("Searching: %s", query)
        results: list[dict] = []

        # Try SearXNG first
        if searxng_url:
            results = search_searxng(
                query, searxng_url, logger, time_range=time_range, max_results=max_results
            )
            if results:
                logger.debug("SearXNG returned %d results for '%s'", len(results), query)

        # Fall back to DuckDuckGo
        if not results:
            results = search_duckduckgo(
                query, logger, time_range=time_range, max_results=max_results
            )

        for r in results:
            url = r.get("url", "")
            if url and url not in seen_urls:
                seen_urls.add(url)
                r["query"] = query
                all_results.append(r)
            elif not url:
                all_results.append(r)

        time.sleep(delay)  # rate limiting

    logger.info("Total unique search results: %d", len(all_results))
    return all_results


def select_search_queries(cfg: dict, now: datetime) -> list[str]:
    """Build date-aware queries and rotate one focused group each ISO week."""
    queries = list(cfg.get("search_queries", []))
    groups = cfg.get("search_query_groups", [])
    if groups:
        group = groups[(now.isocalendar().week - 1) % len(groups)]
        queries.extend(group)

    variables = {
        "year": now.strftime("%Y"),
        "month": now.strftime("%Y-%m"),
        "month_name": now.strftime("%B"),
    }
    rendered = []
    for query in queries:
        try:
            value = query.format(**variables).strip()
        except KeyError as exc:
            raise ValueError(f"unsupported placeholder in search query: {exc}") from exc
        if value and value not in rendered:
            rendered.append(value)
    return rendered


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


def normalize_url(url: str) -> str:
    """Normalize a source URL for stable deduplication across tracking variants."""
    try:
        parts = urlsplit(url.strip())
    except ValueError:
        return ""
    if parts.scheme not in {"http", "https"} or not parts.netloc:
        return ""
    path = re.sub(r"/{2,}", "/", parts.path).rstrip("/") or "/"
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, "", ""))


def extract_known_urls(ledger_text: str) -> set[str]:
    """Extract normalized source URLs persisted in prior evaluations."""
    urls = set()
    for raw_url in re.findall(r"https?://[^\s)>]+", ledger_text):
        normalized = normalize_url(raw_url.rstrip(".,;"))
        if normalized:
            urls.add(normalized)
    return urls


def _normalize_name(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", name.casefold()).strip()


def is_known_setup_name(name: str, known_items: set[str]) -> bool:
    """Match exact names and verbose/qualified variants without another LLM call."""
    candidate = _normalize_name(name)
    if not candidate:
        return True
    for known in known_items:
        normalized_known = _normalize_name(known)
        if candidate == normalized_known:
            return True
        shorter, longer = sorted((candidate, normalized_known), key=len)
        if len(shorter) >= 8 and f" {shorter} " in f" {longer} ":
            return True
    return False


def filter_search_candidates(
    results: list[dict],
    known_urls: set[str],
    known_items: set[str],
    logger: logging.Logger,
) -> list[dict]:
    """Remove already-consumed URLs and exact known setup titles before inference."""
    candidates: list[dict] = []
    seen_urls: set[str] = set()
    skipped_known_url = 0
    skipped_known_name = 0

    for result in results:
        normalized_url = normalize_url(result.get("url", ""))
        normalized_title = _normalize_name(result.get("title", ""))
        if normalized_url and normalized_url in known_urls:
            skipped_known_url += 1
            continue
        if normalized_title and is_known_setup_name(result.get("title", ""), known_items):
            skipped_known_name += 1
            continue
        if normalized_url and normalized_url in seen_urls:
            continue
        if normalized_url:
            seen_urls.add(normalized_url)
        candidates.append(result)

    logger.info(
        "Pre-LLM dedup: %d raw -> %d candidates (%d known URLs, %d known titles skipped)",
        len(results),
        len(candidates),
        skipped_known_url,
        skipped_known_name,
    )
    return candidates


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


def pick_models(cfg: dict, logger: logging.Logger) -> list[str]:
    """Return installed primary/fallback exact tags, in configured order."""
    ollama_url = cfg["ollama_url"]
    models = check_ollama(ollama_url, logger)
    if not models:
        return []

    selected = []
    for role, candidate in (
        ("primary", cfg["ollama_model"]),
        ("fallback", cfg["ollama_fallback_model"]),
    ):
        if candidate in models:
            selected.append(candidate)
            logger.info("Configured %s model is installed: %s", role, candidate)
        else:
            logger.warning(
                "Configured %s model is not installed: %s (no implicit substitution)",
                role,
                candidate,
            )
    return selected


ANALYSIS_SCHEMA = {
    "type": "array",
    "items": {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "name",
            "setup_type",
            "capex_usd",
            "opex_month_usd",
            "velocity_score",
            "quality_score",
            "verdict",
            "rationale",
            "source_url",
        ],
        "properties": {
            "name": {"type": "string", "minLength": 1},
            "setup_type": {"type": "string", "enum": ["local", "paid", "hybrid"]},
            "capex_usd": {"type": "integer", "minimum": 0},
            "opex_month_usd": {"type": "integer", "minimum": 0},
            "velocity_score": {"type": "integer", "minimum": 1, "maximum": 5},
            "quality_score": {"type": "integer", "minimum": 1, "maximum": 5},
            "verdict": {"type": "string", "enum": ["local", "paid", "hybrid"]},
            "rationale": {"type": "string", "minLength": 1},
            "source_url": {"type": "string"},
        },
    },
}


def ollama_chat(
    model: str,
    prompt: str,
    ollama_url: str,
    logger: logging.Logger,
    inference: dict,
) -> str:
    """Send a prompt to Ollama and return the response text."""
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        "think": False,
        "format": ANALYSIS_SCHEMA,
        "options": {
            "temperature": inference.get("temperature", 0.1),
            "num_ctx": inference["num_ctx"],
            "num_predict": inference["num_predict"],
        },
    }
    try:
        resp = requests.post(
            f"{ollama_url}/api/chat", json=payload, timeout=inference["timeout_seconds"]
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
    lines = [
        f"Reference date: {pricing.get('reference_date', '?')}",
        "Policy: historical, manually configured baseline. Prices are not refreshed by the LLM.",
        "Only values checked against an official vendor/source should be updated in config.yaml.",
    ]
    lines.append(
        f"Energy cost: R$ {pricing.get('energy_cost_kwh_brl', '?')}/kWh"
        f" | USD/BRL: {pricing.get('usd_brl', '?')}"
    )
    lines.append("LOCAL HARDWARE options (buy once + monthly energy):")
    for hw in pricing.get("local_hardware", []):
        source = hw.get("source_url") or "UNVERIFIED/MANUAL"
        lines.append(
            f"- {hw['name']}: CAPEX US$ {hw['capex_usd']},"
            f" OPEX US$ {hw['opex_month_usd']}/month | source: {source}"
        )
    lines.append("PAID LICENSES (monthly subscription, no hardware needed):")
    for lic in pricing.get("paid_licenses", []):
        source = lic.get("source_url") or "UNVERIFIED/MANUAL"
        lines.append(
            f"- {lic['name']}: US$ {lic['opex_month_usd']}/month | source: {source}"
        )
    return "\n".join(lines)


def pricing_reference_warning(pricing: dict, now: datetime) -> str:
    """Return a dynamic warning when the manually verified reference is old."""
    reference = datetime.strptime(pricing["reference_date"], "%Y-%m")
    age_months = (now.year - reference.year) * 12 + now.month - reference.month
    max_age = int(pricing.get("max_age_months", 2))
    unverified = sum(
        1
        for item in pricing.get("local_hardware", []) + pricing.get("paid_licenses", [])
        if not item.get("source_url")
    )
    messages = []
    if age_months > max_age:
        messages.append(
            f"referência de preços tem {age_months} meses (limite configurado: {max_age})"
        )
    if unverified:
        messages.append(f"{unverified} preço(s) sem URL de fonte oficial")
    return "; ".join(messages)


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

The pricing block is a historical, manually maintained input. Do not replace,
refresh, or invent prices from snippets. A price may only be changed by a human
after checking an official vendor/source. Use the configured numbers as-is.

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


def validate_analysis_items(items: object, search_results: list[dict]) -> tuple[list[dict], str]:
    """Validate structured output and source provenance without trusting the model."""
    if not isinstance(items, list):
        return [], "LLM retornou JSON mas não como array."
    if len(items) > 20:
        return [], "LLM retornou mais de 20 itens; resposta rejeitada."

    required_strings = ("name", "rationale", "source_url")
    required_ints = ("capex_usd", "opex_month_usd", "velocity_score", "quality_score")
    allowed_types = {"local", "paid", "hybrid"}
    allowed_urls = {
        normalize_url(result.get("url", "")) for result in search_results if result.get("url")
    }
    seen_names = set()

    for index, item in enumerate(items, 1):
        if not isinstance(item, dict):
            return [], f"item {index} não é um objeto."
        if set(item) != set(ANALYSIS_SCHEMA["items"]["required"]):
            return [], f"item {index} possui campos ausentes ou extras."
        if any(not isinstance(item[key], str) for key in required_strings):
            return [], f"item {index} possui campo textual inválido."
        if not item["name"].strip() or not item["rationale"].strip():
            return [], f"item {index} possui nome/justificativa vazios."
        invalid_integer = any(
            isinstance(item[key], bool) or not isinstance(item[key], int)
            for key in required_ints
        )
        if invalid_integer:
            return [], f"item {index} possui custo ou nota não inteiro."
        if item["capex_usd"] < 0 or item["opex_month_usd"] < 0:
            return [], f"item {index} possui custo negativo."
        if not 1 <= item["velocity_score"] <= 5 or not 1 <= item["quality_score"] <= 5:
            return [], f"item {index} possui nota fora do intervalo 1-5."
        if (
            not isinstance(item["setup_type"], str)
            or not isinstance(item["verdict"], str)
            or item["setup_type"] not in allowed_types
            or item["verdict"] not in allowed_types
        ):
            return [], f"item {index} possui categoria inválida."
        source_url = normalize_url(item["source_url"])
        if allowed_urls and not source_url:
            return [], f"item {index} não cita a fonte disponível nos resultados de busca."
        if item["source_url"] and source_url not in allowed_urls:
            return [], f"item {index} cita URL que não estava nos resultados de busca."
        normalized_name = _normalize_name(item["name"])
        if normalized_name in seen_names:
            return [], f"item {index} duplica outro setup na mesma resposta."
        seen_names.add(normalized_name)
    return items, ""


def analyze_results(
    search_results: list[dict],
    known_items: set[str],
    hardware_context: str,
    pricing_reference: str,
    model: str,
    ollama_url: str,
    logger: logging.Logger,
    inference: dict,
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
        raw = ollama_chat(model, prompt, ollama_url, logger, inference)
    except Exception as exc:
        return [], f"LLM ({model}) falhou: {exc}"

    if not raw:
        logger.warning("LLM returned empty response.")
        return [], (
            f"LLM ({model}) retornou resposta vazia — "
            "verifique se o modelo está disponível."
        )

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
        items, validation_error = validate_analysis_items(items, search_results)
        if validation_error:
            logger.warning("LLM structured output rejected: %s", validation_error)
            return [], validation_error
        logger.info("LLM evaluated %d new setups.", len(items))
        return items, ""
    except json.JSONDecodeError as exc:
        logger.error("JSON parse error: %s\nRaw snippet: %s", exc, match.group(0)[:500])
        return [], f"Erro ao parsear JSON do LLM: {exc}"


def analyze_with_fallback(
    search_results: list[dict],
    known_items: set[str],
    hardware_context: str,
    pricing_reference: str,
    models: list[str],
    cfg: dict,
    logger: logging.Logger,
) -> tuple[list[dict], str, str]:
    """Try primary once and, only after failure, the configured smaller fallback once."""
    errors = []
    for attempt, model in enumerate(models, 1):
        if attempt > 1:
            logger.warning("Retrying analysis once with configured fallback model: %s", model)
        items, error = analyze_results(
            search_results,
            known_items,
            hardware_context,
            pricing_reference,
            model,
            cfg["ollama_url"],
            logger,
            cfg["inference"],
        )
        if not error:
            return items, "", model
        errors.append(error)
    return [], " | ".join(errors), models[-1] if models else ""


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
        if is_known_setup_name(name, known_items):
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
    candidate_count: int | None = None,
    analysis_skipped_reason: str = "",
    pricing_warning: str = "",
) -> Path:
    """Write the weekly cost-benefit report markdown file."""
    reports_dir.mkdir(parents=True, exist_ok=True)
    report_path = reports_dir / f"{today}-cost-benefit.md"

    if llm_error:
        llm_status = f"ERRO — {llm_error}"
    elif analysis_skipped_reason:
        llm_status = f"NÃO NECESSÁRIA — {analysis_skipped_reason}"
    elif llm_model:
        analyzed_count = candidate_count if candidate_count is not None else len(all_results)
        llm_status = (
            f"OK — `{llm_model}` analisou {analyzed_count} candidato(s) e "
            f"avaliou {len(new_items)} setup(s) novo(s)"
        )
    else:
        llm_status = "não executada (Ollama indisponível)"

    lines = [
        f"# Weekly Cost-Benefit Report — {today}",
        "",
        f"**Analise executada em:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"**Queries executadas:** {len(queries)}",
        f"**Resultados brutos coletados:** {len(all_results)}",
        "**Fontes candidatas após deduplicação:** "
        f"{candidate_count if candidate_count is not None else len(all_results)}",
        f"**Análise LLM:** {llm_status}",
        f"**Setups avaliados:** {len(new_items)}",
        "",
        "## Base de Precos Utilizada",
        "",
        "> Valores históricos configurados manualmente; não são atualizados pelo modelo.",
        "> Alterações de preço exigem conferência em fonte oficial.",
        *([f"> **Atenção:** {pricing_warning}."] if pricing_warning else []),
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
    if analysis_skipped_reason:
        lines.append(
            "_Nenhuma fonte candidata nova após deduplicar URLs e títulos já conhecidos._"
        )
    elif not new_items and not llm_error:
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
    candidate_count: int | None = None,
    search_time_range: str = "month",
    analysis_skipped_reason: str = "",
) -> None:
    """Send a Telegram message via the Hermes bot, with run metadata and the report attached."""
    params_block = (
        "\n--- Parâmetros desta execução ---\n"
        f"Período de busca: {search_time_range}, "
        f"deduplicado contra {known_count} setup(s) já no ledger\n"
        f"Queries ({len(queries)}):\n" + "\n".join(f"  • {q}" for q in queries) + "\n"
        f"Resultados brutos coletados: {raw_result_count}\n"
        "Fontes candidatas novas: "
        f"{candidate_count if candidate_count is not None else raw_result_count}\n"
        "Modelo de análise: "
        f"{model or ('(não acionado)' if analysis_skipped_reason else '(nenhum disponível)')}"
    )

    if llm_error:
        text = (
            f"⚠️ Weekly Cost-Benefit — {today}\n\n"
            f"FALHA na análise LLM: {llm_error}\n"
            f"{params_block}"
        )
    elif analysis_skipped_reason:
        text = (
            f"Weekly Cost-Benefit — {today}\n\n"
            "Nenhuma fonte candidata nova após deduplicação; inferência não foi necessária.\n"
            f"{params_block}"
        )
    elif not new_items:
        text = (
            f"Weekly Cost-Benefit — {today}\n\n"
            "Nenhum setup novo avaliado esta semana.\n"
            f"{params_block}"
        )
    else:
        lines = [
            f"Weekly Cost-Benefit — {today}",
            f"\n{len(new_items)} setup(s) avaliado(s):\n",
        ]
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
            "Falha ao enviar a notificação Telegram — "
            "ninguém será avisado do resultado desta execução."
        )
    if report_path is not None:
        caption = (
            f"⚠️ Relatório com erro — {today}"
            if llm_error
            else f"Relatório completo — {today}"
        )
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
        logging.getLogger("cost_benefit_agent").exception("Agent crashed unexpectedly.")
        send_telegram_message(
            f"🔥 Weekly Cost-Benefit — CRASH\n\nO agente quebrou antes de terminar: {exc}",
            logger=None,
        )
        raise


def _run() -> int:
    cfg = load_config()
    logger = setup_logging(cfg.get("log_file", "cost-benefit.log"))
    now = datetime.now()
    today = now.strftime("%Y-%m-%d")

    logger.info("=== Weekly Cost-Benefit Agent starting — %s ===", today)

    # Resolve paths relative to script directory
    ledger_path = (SCRIPT_DIR / cfg["ledger_path"]).resolve()
    reports_dir = (SCRIPT_DIR / cfg["reports_dir"]).resolve()

    # 1. Read ledger
    ledger_text = read_ledger(ledger_path, logger)
    known_items = extract_known_items(ledger_text, cfg.get("known_evaluated", []))
    known_urls = extract_known_urls(ledger_text)
    logger.info("Known setups in ledger: %d", len(known_items))
    logger.info("Known source URLs in ledger: %d", len(known_urls))

    # 2. Format pricing reference
    pricing_cfg = cfg.get("pricing_reference", {})
    pricing_reference = format_pricing_reference(pricing_cfg)
    pricing_warning = pricing_reference_warning(pricing_cfg, now)
    if pricing_warning:
        logger.warning("Pricing reference needs review: %s", pricing_warning)

    # 3. Run searches
    queries = select_search_queries(cfg, now)
    all_results = run_searches(queries, cfg, logger)

    # Se todas as queries retornaram zero, não há evidência para distinguir
    # “sem novidades” de uma indisponibilidade completa dos backends de busca.
    if not all_results:
        search_error = "Nenhum resultado foi retornado pelos backends de busca."
        logger.error(search_error)
        report_path = write_report(
            [],
            all_results,
            queries,
            pricing_reference,
            reports_dir,
            today,
            logger,
            llm_error=search_error,
            candidate_count=0,
            pricing_warning=pricing_warning,
        )
        send_telegram(
            [],
            today,
            logger,
            queries=queries,
            known_count=len(known_items),
            raw_result_count=0,
            candidate_count=0,
            model="",
            report_path=report_path,
            llm_error=search_error,
            search_time_range=cfg.get("search", {}).get("time_range", "month"),
        )
        return 1

    candidates = filter_search_candidates(all_results, known_urls, known_items, logger)

    # No unseen source/title is a legitimate result, not an inference failure.
    if not candidates:
        skipped_reason = "nenhuma fonte candidata nova após deduplicação pré-LLM"
        report_path = write_report(
            [],
            all_results,
            queries,
            pricing_reference,
            reports_dir,
            today,
            logger,
            candidate_count=0,
            analysis_skipped_reason=skipped_reason,
            pricing_warning=pricing_warning,
        )
        send_telegram(
            [],
            today,
            logger,
            queries=queries,
            known_count=len(known_items),
            raw_result_count=len(all_results),
            candidate_count=0,
            model="",
            report_path=report_path,
            search_time_range=cfg.get("search", {}).get("time_range", "month"),
            analysis_skipped_reason=skipped_reason,
        )
        logger.info("Done: no new candidates; LLM was not called.")
        return 0

    # 4. Check Ollama
    models = pick_models(cfg, logger)
    if not models:
        no_model_error = "Ollama indisponível ou nenhum modelo configurado está instalado."
        logger.error(
            "Ollama not available or no models installed. "
            "Writing raw results to report without LLM analysis."
        )
        report_path = write_report(
            [], all_results, queries, pricing_reference, reports_dir, today, logger,
            llm_error=no_model_error,
            llm_model="",
            candidate_count=len(candidates),
            pricing_warning=pricing_warning,
        )
        send_telegram(
            [],
            today,
            logger,
            queries=queries,
            known_count=len(known_items),
            raw_result_count=len(all_results),
            candidate_count=len(candidates),
            model="",
            report_path=report_path,
            llm_error=no_model_error,
            search_time_range=cfg.get("search", {}).get("time_range", "month"),
        )
        logger.error("Done with failure (no configured LLM available).")
        return 1

    # 5. LLM cost-benefit analysis
    raw_items, llm_error, model = analyze_with_fallback(
        candidates,
        known_items,
        cfg.get("hardware_context", ""),
        pricing_reference,
        models,
        cfg,
        logger,
    )

    # 6. Filter duplicates
    new_items = filter_new_items(raw_items, known_items, logger)

    # 6b. Recompute breakeven deterministically (do not trust LLM arithmetic)
    for item in new_items:
        item["breakeven_months"] = compute_breakeven_months(item, pricing_cfg)

    # 7. Write report
    report_path = write_report(
        new_items, all_results, queries, pricing_reference, reports_dir, today, logger,
        llm_error=llm_error,
        llm_model=model,
        candidate_count=len(candidates),
        pricing_warning=pricing_warning,
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
        candidate_count=len(candidates),
        model=model,
        report_path=report_path,
        llm_error=llm_error,
        search_time_range=cfg.get("search", {}).get("time_range", "month"),
    )

    logger.info("=== Agent finished. Report: %s ===", report_path)
    if llm_error:
        logger.error("Agent completed reporting/notification but analysis failed; exit status=1.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
