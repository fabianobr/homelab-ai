"""tests/test_no_direct_http.py"""
import ast
from pathlib import Path

SRC_ROOT = Path(__file__).resolve().parents[1] / "src" / "carwatch"
# fetcher.py is the sole egress point for anonymous web crawling (SPEC.md §3/§6).
# publishers/telegram.py is a deliberate, documented exception (see Task 15) for two
# calls, neither of which is anonymous content crawling that fetcher's robots.txt
# checks, conditional-GET, and silent-block heuristics (short body < 500 chars, which
# a small JSON ack would trip) are meant to police:
#   - send_telegram_message() POSTs to the authenticated Telegram Bot API.
#   - fetch_usd_rates() GETs a single well-known JSON currency-rate API (not a
#     monitored content source), needed once per publish batch with its own
#     short timeout and best-effort failure handling (see its docstring).
ALLOWED_FILES = {"fetcher.py", "telegram.py"}
FORBIDDEN_ATTRS = {"get", "post", "put", "delete", "patch", "request", "stream"}
FORBIDDEN_MODULES = {"httpx", "requests", "urllib.request"}


def _iter_python_files():
    for path in SRC_ROOT.rglob("*.py"):
        if path.name not in ALLOWED_FILES:
            yield path


def _imports_forbidden_module(tree: ast.AST) -> set[str]:
    aliases = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name in FORBIDDEN_MODULES:
                    aliases.add(alias.asname or alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module in FORBIDDEN_MODULES:
            for alias in node.names:
                aliases.add(alias.asname or alias.name)
    return aliases


def test_no_module_outside_fetcher_imports_http_libraries():
    offenders = []
    for path in _iter_python_files():
        tree = ast.parse(path.read_text(), filename=str(path))
        aliases = _imports_forbidden_module(tree)
        if aliases:
            offenders.append((str(path.relative_to(SRC_ROOT)), sorted(aliases)))

    assert offenders == [], f"HTTP libraries imported outside the allowed files {ALLOWED_FILES}: {offenders}"


def test_no_module_outside_fetcher_calls_http_methods_on_a_client_named_client():
    offenders = []
    for path in _iter_python_files():
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in FORBIDDEN_ATTRS
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id in {"httpx", "client", "session", "requests"}
            ):
                offenders.append(f"{path.relative_to(SRC_ROOT)}:{node.lineno}")

    assert offenders == [], f"Direct HTTP calls found outside the allowed files: {offenders}"
