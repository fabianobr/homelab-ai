import importlib.util
import logging
from datetime import datetime
from pathlib import Path

import yaml


MODULE_PATH = Path(__file__).parents[1] / "cost_benefit_agent.py"
SPEC = importlib.util.spec_from_file_location("cost_benefit_agent_under_test", MODULE_PATH)
agent = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(agent)


def logger():
    value = logging.getLogger("weekly-cost-benefit-tests")
    value.handlers.clear()
    value.addHandler(logging.NullHandler())
    return value


def configured():
    return yaml.safe_load((MODULE_PATH.parent / "config.yaml").read_text(encoding="utf-8"))


def test_current_config_is_valid():
    cfg = configured()
    agent.validate_config(cfg)
    pricing_ids = [
        item["id"]
        for section in ("local_hardware", "paid_licenses")
        for item in cfg["pricing_reference"][section]
    ]
    assert len(pricing_ids) == 12
    assert len(pricing_ids) == len(set(pricing_ids))


def test_model_selection_is_exact_and_never_uses_arbitrary_installed_model(monkeypatch):
    cfg = configured()
    monkeypatch.setattr(
        agent,
        "check_ollama",
        lambda *_: ["qwen3:32b", "nomic-embed-text:latest", "qwen3:8b"],
    )

    assert agent.pick_models(cfg, logger()) == ["qwen3:8b"]


def test_ollama_request_has_resource_limits_thinking_disabled_and_schema(monkeypatch):
    captured = {}

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"message": {"content": "[]"}}

    def fake_post(url, json, timeout):
        captured.update(url=url, payload=json, timeout=timeout)
        return Response()

    monkeypatch.setattr(agent.requests, "post", fake_post)
    inference = configured()["inference"]

    assert agent.ollama_chat("qwen3:14b", "prompt", "http://ollama", logger(), inference) == "[]"
    assert captured["payload"]["think"] is False
    assert captured["payload"]["format"] == agent.ANALYSIS_SCHEMA
    assert "capex_usd" not in captured["payload"]["format"]["items"]["properties"]
    assert "opex_month_usd" not in captured["payload"]["format"]["items"]["properties"]
    assert captured["payload"]["options"]["num_ctx"] == 8192
    assert captured["payload"]["options"]["num_predict"] == 1400
    assert captured["timeout"] == 180


def test_known_urls_and_titles_are_removed_before_llm():
    ledger = """
### Known Setup
- **Fonte:** https://Example.COM/article?id=42&utm_source=old
"""
    results = [
        {
            "title": "Something else",
            "url": "https://example.com/article?id=42&utm_campaign=new",
            "snippet": "x",
        },
        {"title": "Known Setup", "url": "https://fresh.example/known", "snippet": "x"},
        {"title": "New measured setup", "url": "https://fresh.example/new", "snippet": "x"},
    ]

    candidates = agent.filter_search_candidates(
        results,
        agent.extract_known_urls(ledger),
        agent.extract_known_items(ledger, []),
        logger(),
    )

    assert candidates == [results[2]]


def test_normalize_url_preserves_functional_query_and_removes_only_tracking():
    first = agent.normalize_url(
        "https://EXAMPLE.com/search/?id=42&ref=manual&view=full&utm_source=newsletter#section"
    )
    second = agent.normalize_url(
        "https://example.com/search?id=43&view=full&utm_campaign=weekly"
    )

    assert first == "https://example.com/search?id=42&ref=manual&view=full"
    assert second == "https://example.com/search?id=43&view=full"
    assert first != second


def test_normalize_url_canonicalizes_functional_query_order_and_encoding():
    first = agent.normalize_url("https://example.com/search?view=full&q=local%20llm&id=42")
    second = agent.normalize_url("https://example.com/search?id=42&q=local+llm&view=full")

    assert first == second
    assert first == "https://example.com/search?id=42&q=local+llm&view=full"


def test_verbose_variant_of_known_setup_is_removed_after_llm():
    known = {"Mac Studio M4 Max 64GB"}
    items = [
        {
            **valid_item(),
            "name": "Local AI Development Setup with Mac Studio M4 Max 64GB",
        }
    ]

    assert agent.filter_new_items(items, known, logger()) == []


def test_queries_render_current_period_and_rotate_by_week():
    cfg = configured()
    week_one = agent.select_search_queries(cfg, datetime(2026, 8, 3))
    week_two = agent.select_search_queries(cfg, datetime(2026, 8, 10))

    assert len(week_one) == 4
    assert all("{" not in query for query in week_one)
    assert any("2026-08" in query for query in week_one)
    assert week_one[:2] == week_two[:2]
    assert week_one[2:] != week_two[2:]


def valid_item():
    return {
        "name": "Fresh Setup",
        "setup_type": "hybrid",
        "pricing_ids": ["rtx-5060-ti-16gb", "cursor-pro"],
        "velocity_score": 4,
        "quality_score": 4,
        "verdict": "hybrid",
        "rationale": "Uses each resource where it is most effective.",
        "source_url": "https://example.com/new",
    }


def test_structured_output_validation_enforces_source_provenance():
    cfg = configured()
    results = [{"url": "https://example.com/new?utm_source=test"}]
    items, error = agent.validate_analysis_items(
        [valid_item()], results, cfg["pricing_reference"]
    )
    assert items and error == ""
    assert items[0]["capex_usd"] == 430
    assert items[0]["opex_month_usd"] == 35

    invalid = valid_item()
    invalid["source_url"] = "https://invented.example/not-in-search"
    items, error = agent.validate_analysis_items(
        [invalid], results, cfg["pricing_reference"]
    )
    assert items == []
    assert "não estava nos resultados" in error


def test_llm_costs_are_rejected_and_unknown_pricing_ids_cannot_be_persisted():
    cfg = configured()
    results = [{"url": "https://example.com/new"}]

    arbitrary_cost = {**valid_item(), "capex_usd": 1, "opex_month_usd": 999999}
    items, error = agent.validate_analysis_items(
        [arbitrary_cost], results, cfg["pricing_reference"]
    )
    assert items == []
    assert "campos ausentes ou extras" in error

    unknown_price = {**valid_item(), "pricing_ids": ["invented-price-id"]}
    items, error = agent.validate_analysis_items(
        [unknown_price], results, cfg["pricing_reference"]
    )
    assert items == []
    assert "desconhecido" in error


def test_persistence_boundary_overwrites_injected_costs_from_upstream():
    cfg = configured()
    injected = {
        **valid_item(),
        "capex_usd": 1,
        "opex_month_usd": 999999,
        "breakeven_months": 1,
        "unexpected": "discard me",
    }

    items, error = agent.anchor_items_to_pricing([injected], cfg["pricing_reference"])

    assert error == ""
    assert items[0]["capex_usd"] == 430
    assert items[0]["opex_month_usd"] == 35
    assert "breakeven_months" not in items[0]
    assert "unexpected" not in items[0]


def test_pricing_ids_must_match_setup_type():
    cfg = configured()
    results = [{"url": "https://example.com/new"}]
    paid_with_hardware = {
        **valid_item(),
        "setup_type": "paid",
        "pricing_ids": ["rtx-5060-ti-16gb"],
    }

    items, error = agent.validate_analysis_items(
        [paid_with_hardware], results, cfg["pricing_reference"]
    )
    assert items == []
    assert "incompatíveis" in error


def test_semantic_dedup_keeps_legitimate_composite_of_known_setups():
    known = {"Cursor Pro", "GitHub Copilot Pro"}
    composite = {**valid_item(), "name": "Cursor Pro + GitHub Copilot Pro"}

    assert agent.filter_new_items([composite], known, logger()) == [composite]


def test_semantic_dedup_does_not_merge_pro_and_pro_plus_tiers():
    pro_plus = {**valid_item(), "name": "GitHub Copilot Pro+"}

    assert agent.filter_new_items([pro_plus], {"GitHub Copilot Pro"}, logger()) == [pro_plus]


def test_semantic_dedup_removes_aliases_inside_same_batch():
    first = {**valid_item(), "name": "Cursor Pro + GitHub Copilot Pro"}
    reordered = {**valid_item(), "name": "GitHub Copilot Pro and Cursor Pro"}
    verbose = {**valid_item(), "name": "Local AI Development Setup with Fresh Setup"}

    assert agent.filter_new_items([first, reordered, valid_item(), verbose], set(), logger()) == [
        first,
        valid_item(),
    ]

    assert agent.filter_new_items([valid_item(), valid_item()], set(), logger()) == [valid_item()]


def test_fallback_is_attempted_once_only_after_primary_failure(monkeypatch):
    calls = []

    def fake_analyze(*args):
        model = args[4]
        calls.append(model)
        if model == "qwen3:14b":
            return [], "timeout"
        return [], ""

    monkeypatch.setattr(agent, "analyze_results", fake_analyze)
    cfg = configured()
    items, error, model = agent.analyze_with_fallback(
        [{"url": "https://example.com"}], set(), "hardware", "prices",
        ["qwen3:14b", "qwen3:8b"], cfg, logger(),
    )

    assert items == []
    assert error == ""
    assert model == "qwen3:8b"
    assert calls == ["qwen3:14b", "qwen3:8b"]


def test_analysis_failure_returns_nonzero_after_mocked_report_and_notification(monkeypatch):
    cfg = configured()
    cfg["ledger_path"] = "never-read.md"
    cfg["reports_dir"] = "never-written"
    calls = []

    monkeypatch.setattr(agent, "load_config", lambda: cfg)
    monkeypatch.setattr(agent, "setup_logging", lambda *_: logger())
    monkeypatch.setattr(agent, "read_ledger", lambda *_: "")
    monkeypatch.setattr(
        agent,
        "run_searches",
        lambda *_: [{"title": "New", "url": "https://example.com/new", "snippet": "x"}],
    )
    monkeypatch.setattr(agent, "pick_models", lambda *_: ["qwen3:14b", "qwen3:8b"])
    monkeypatch.setattr(
        agent,
        "analyze_with_fallback",
        lambda *_: ([], "primary timeout | fallback timeout", "qwen3:8b"),
    )
    monkeypatch.setattr(
        agent,
        "write_report",
        lambda *args, **kwargs: calls.append("report") or Path("mock.md"),
    )
    monkeypatch.setattr(agent, "update_ledger", lambda *args, **kwargs: calls.append("ledger"))
    monkeypatch.setattr(agent, "send_telegram", lambda *args, **kwargs: calls.append("notify"))

    assert agent._run() == 1
    assert calls == ["report", "ledger", "notify"]


def test_run_reanchors_costs_before_report_and_ledger(monkeypatch):
    cfg = configured()
    cfg["ledger_path"] = "never-read.md"
    cfg["reports_dir"] = "never-written"
    captured = {}
    injected = {**valid_item(), "capex_usd": 1, "opex_month_usd": 999999}

    monkeypatch.setattr(agent, "load_config", lambda: cfg)
    monkeypatch.setattr(agent, "setup_logging", lambda *_: logger())
    monkeypatch.setattr(agent, "read_ledger", lambda *_: "")
    monkeypatch.setattr(
        agent,
        "run_searches",
        lambda *_: [{"title": "New", "url": "https://example.com/new", "snippet": "x"}],
    )
    monkeypatch.setattr(agent, "pick_models", lambda *_: ["qwen3:14b"])
    monkeypatch.setattr(
        agent,
        "analyze_with_fallback",
        lambda *_: ([injected], "", "qwen3:14b"),
    )
    monkeypatch.setattr(
        agent,
        "write_report",
        lambda items, *args, **kwargs: captured.setdefault("report", items) or Path("mock.md"),
    )
    monkeypatch.setattr(
        agent,
        "update_ledger",
        lambda path, items, *args, **kwargs: captured.setdefault("ledger", items),
    )
    monkeypatch.setattr(agent, "send_telegram", lambda *args, **kwargs: None)

    assert agent._run() == 0
    assert captured["report"][0]["capex_usd"] == 430
    assert captured["report"][0]["opex_month_usd"] == 35
    assert captured["ledger"] == captured["report"]


def test_no_new_candidates_is_success_and_skips_ollama(monkeypatch):
    cfg = configured()
    cfg["ledger_path"] = "never-read.md"
    cfg["reports_dir"] = "never-written"
    known_url = "https://example.com/already-evaluated"
    calls = []

    monkeypatch.setattr(agent, "load_config", lambda: cfg)
    monkeypatch.setattr(agent, "setup_logging", lambda *_: logger())
    monkeypatch.setattr(
        agent,
        "read_ledger",
        lambda *_: f"### Known Setup\n- **Fonte:** {known_url}\n",
    )
    monkeypatch.setattr(
        agent,
        "run_searches",
        lambda *_: [{"title": "Old", "url": f"{known_url}?utm_source=search", "snippet": "x"}],
    )
    monkeypatch.setattr(
        agent,
        "pick_models",
        lambda *_: (_ for _ in ()).throw(AssertionError("Ollama must not be checked")),
    )
    monkeypatch.setattr(
        agent,
        "write_report",
        lambda *args, **kwargs: calls.append("report") or Path("mock.md"),
    )
    monkeypatch.setattr(agent, "send_telegram", lambda *args, **kwargs: calls.append("notify"))

    assert agent._run() == 0
    assert calls == ["report", "notify"]


def test_empty_search_results_are_failure_and_skip_ollama(monkeypatch):
    cfg = configured()
    cfg["ledger_path"] = "never-read.md"
    cfg["reports_dir"] = "never-written"
    calls = []

    monkeypatch.setattr(agent, "load_config", lambda: cfg)
    monkeypatch.setattr(agent, "setup_logging", lambda *_: logger())
    monkeypatch.setattr(agent, "read_ledger", lambda *_: "")
    monkeypatch.setattr(agent, "run_searches", lambda *_: [])
    monkeypatch.setattr(
        agent,
        "pick_models",
        lambda *_: (_ for _ in ()).throw(AssertionError("Ollama must not be checked")),
    )
    monkeypatch.setattr(
        agent,
        "write_report",
        lambda *args, **kwargs: calls.append(("report", kwargs["llm_error"])) or Path("mock.md"),
    )
    monkeypatch.setattr(
        agent,
        "send_telegram",
        lambda *args, **kwargs: calls.append(("notify", kwargs["llm_error"])),
    )

    assert agent._run() == 1
    assert calls[0][0] == "report" and "Nenhum resultado" in calls[0][1]
    assert calls[1][0] == "notify" and "Nenhum resultado" in calls[1][1]
