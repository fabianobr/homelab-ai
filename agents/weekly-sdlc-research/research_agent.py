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

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
SCRIPT_DIR = Path(__file__).parent.resolve()
CONFIG_PATH = SCRIPT_DIR / "config.yaml"


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
    """Search via DuckDuckGo Instant Answer API (no key required)."""
    url = "https://api.duckduckgo.com/"
    params = {"q": query, "format": "json", "no_html": "1", "skip_disambig": "1"}
    headers = {"User-Agent": "homelab-research-agent/1.0"}
    try:
        resp = requests.get(url, params=params, headers=headers, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        results = []

        # Abstract result
        if data.get("AbstractText") and data.get("AbstractURL"):
            results.append(
                {
                    "title": data.get("Heading", query),
                    "url": data.get("AbstractURL", ""),
                    "snippet": data.get("AbstractText", ""),
                }
            )

        # Related topics
        for topic in data.get("RelatedTopics", [])[:6]:
            if isinstance(topic, dict) and topic.get("Text"):
                results.append(
                    {
                        "title": topic.get("Text", "")[:80],
                        "url": topic.get("FirstURL", ""),
                        "snippet": topic.get("Text", ""),
                    }
                )
        return results
    except Exception as exc:
        logger.warning("DuckDuckGo search failed for '%s': %s", query, exc)
        return []


def search_duckduckgo_html(query: str, logger: logging.Logger) -> list[dict]:
    """Fallback: scrape DuckDuckGo HTML lite endpoint."""
    url = "https://html.duckduckgo.com/html/"
    params = {"q": query}
    headers = {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    try:
        resp = requests.post(url, data=params, headers=headers, timeout=20)
        resp.raise_for_status()
        html = resp.text

        # Simple regex extraction of result snippets (no external libs)
        results = []
        # Match result blocks: title in <a class="result__a"> and snippet in .result__snippet
        titles = re.findall(r'class="result__a"[^>]*>(.*?)</a>', html)
        urls_raw = re.findall(r'class="result__url"[^>]*>(.*?)</span>', html)
        snippets = re.findall(r'class="result__snippet"[^>]*>(.*?)</a>', html, re.DOTALL)

        for i in range(min(len(titles), len(snippets), 8)):
            title = re.sub(r"<[^>]+>", "", titles[i]).strip()
            snippet = re.sub(r"<[^>]+>", "", snippets[i]).strip()
            url_hint = urls_raw[i].strip() if i < len(urls_raw) else ""
            if title and snippet:
                results.append({"title": title, "url": url_hint, "snippet": snippet})
        return results
    except Exception as exc:
        logger.warning("DuckDuckGo HTML search failed for '%s': %s", query, exc)
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

        # Fall back to DuckDuckGo Instant Answer
        if not results:
            results = search_duckduckgo(query, logger)
            if results:
                logger.debug("DDG IA returned %d results for '%s'", len(results), query)

        # Fall back to DDG HTML scrape
        if not results:
            time.sleep(2)  # be polite
            results = search_duckduckgo_html(query, logger)
            logger.debug("DDG HTML returned %d results for '%s'", len(results), query)

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
def check_ollama(ollama_url: str, logger: logging.Logger) -> str | None:
    """Return the first available model name or None."""
    try:
        resp = requests.get(f"{ollama_url}/api/tags", timeout=8)
        resp.raise_for_status()
        models = [m["name"] for m in resp.json().get("models", [])]
        logger.info("Ollama available models: %s", models)
        return models[0] if models else None
    except Exception as exc:
        logger.warning("Ollama not reachable: %s", exc)
        return None


def pick_model(cfg: dict, logger: logging.Logger) -> str | None:
    """Pick preferred model, fallback, or whatever is installed."""
    ollama_url = cfg["ollama_url"]
    available = check_ollama(ollama_url, logger)
    if available is None:
        return None

    try:
        resp = requests.get(f"{ollama_url}/api/tags", timeout=8)
        models = [m["name"] for m in resp.json().get("models", [])]
    except Exception:
        models = []

    preferred = cfg.get("ollama_model", "")
    fallback = cfg.get("ollama_fallback_model", "")

    for candidate in [preferred, fallback]:
        for installed in models:
            if installed.startswith(candidate.split(":")[0]):
                logger.info("Using model: %s", installed)
                return installed

    if models:
        logger.info("Preferred models not found; using first available: %s", models[0])
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
        "options": {"temperature": 0.2, "num_predict": 1024},
    }
    try:
        resp = requests.post(
            f"{ollama_url}/api/chat", json=payload, timeout=120
        )
        resp.raise_for_status()
        return resp.json()["message"]["content"].strip()
    except Exception as exc:
        logger.error("Ollama request failed: %s", exc)
        return ""


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
) -> list[dict]:
    """Use LLM to filter and evaluate search results."""
    if not search_results:
        logger.info("No search results to analyze.")
        return []

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
    raw = ollama_chat(model, prompt, ollama_url, logger)

    if not raw:
        logger.warning("LLM returned empty response.")
        return []

    # Extract JSON array robustly
    # Strip markdown fences if present
    cleaned = re.sub(r"```(?:json)?\s*", "", raw)
    cleaned = re.sub(r"```", "", cleaned).strip()

    # Find first [ ... ] block
    match = re.search(r"\[.*\]", cleaned, re.DOTALL)
    if not match:
        logger.warning("Could not find JSON array in LLM response. Raw: %s", raw[:500])
        return []

    try:
        items = json.loads(match.group(0))
        if not isinstance(items, list):
            logger.warning("LLM JSON was not a list.")
            return []
        logger.info("LLM identified %d new items.", len(items))
        return items
    except json.JSONDecodeError as exc:
        logger.error("JSON parse error: %s\nRaw snippet: %s", exc, match.group(0)[:500])
        return []


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
) -> Path:
    """Write the weekly report markdown file."""
    reports_dir.mkdir(parents=True, exist_ok=True)
    report_path = reports_dir / f"{today}-weekly-research.md"

    lines = [
        f"# Weekly LLM Research Report — {today}",
        "",
        f"**Pesquisa executada em:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"**Queries executadas:** {len(queries)}",
        f"**Resultados brutos coletados:** {len(all_results)}",
        f"**Novos itens identificados:** {len(new_items)}",
        "",
        "## Queries Executadas",
        "",
    ]
    for q in queries:
        lines.append(f"- `{q}`")

    lines += ["", "## Novos Itens Encontrados", ""]

    if not new_items:
        lines.append("_Nenhum item novo identificado nesta semana._")
    else:
        for item in new_items:
            lines.append(format_item_markdown(item))
            lines.append("")

    lines += [
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
# Main
# ---------------------------------------------------------------------------
def main() -> None:
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
        logger.error(
            "Ollama not available or no models installed. "
            "Writing raw results to report without LLM analysis."
        )
        # Write a minimal report and exit gracefully
        write_report([], all_results, queries, reports_dir, today, logger)
        logger.info("Done (no LLM analysis).")
        return

    # 4. LLM analysis
    raw_items = analyze_results(
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
        new_items, all_results, queries, reports_dir, today, logger
    )

    # 7. Update backlog
    update_backlog(backlog_path, new_items, today, logger)

    logger.info("=== Agent finished. Report: %s ===", report_path)


if __name__ == "__main__":
    main()
