import importlib.util
import json
import logging
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import requests


AGENT_PATH = Path(__file__).resolve().parents[1] / "research_agent.py"
SPEC = importlib.util.spec_from_file_location("weekly_sdlc_research_agent", AGENT_PATH)
agent = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(agent)


def valid_item(name="Tool X"):
    return {
        "name": name,
        "type": "coding_agent",
        "sdlc_relevance": 4,
        "hw_viability": 5,
        "description": "Ferramenta local útil para revisão de código.",
        "source_url": "https://example.test/tool-x",
    }


class ModelSelectionTests(unittest.TestCase):
    def setUp(self):
        self.logger = Mock(spec=logging.Logger)
        self.cfg = {
            "ollama_url": "http://ollama.test",
            "ollama_model": "qwen3:14b",
            "ollama_fallback_models": ["qwen3:8b", "llama3.2:latest"],
            "ollama_max_attempts": 2,
        }

    @patch.object(agent, "check_ollama")
    def test_selects_only_exact_configured_models_in_order(self, check_ollama):
        check_ollama.return_value = [
            "qwen2.5-coder:32b",
            "llama3.2:latest",
            "qwen3:8b",
            "qwen3:14b",
        ]

        selected = agent.pick_models(self.cfg, self.logger)

        self.assertEqual(selected, ["qwen3:14b", "qwen3:8b"])

    @patch.object(agent, "check_ollama")
    def test_does_not_substitute_prefix_or_first_installed_model(self, check_ollama):
        check_ollama.return_value = ["qwen3:32b", "embeddinggemma:latest"]

        selected = agent.pick_models(self.cfg, self.logger)

        self.assertEqual(selected, [])


class OllamaRequestTests(unittest.TestCase):
    @patch.object(agent.requests, "post")
    def test_request_is_bounded_non_thinking_and_schema_constrained(self, post):
        response = Mock()
        response.json.return_value = {"message": {"content": "[]"}}
        post.return_value = response
        options = {"temperature": 0.2, "num_ctx": 8192, "num_predict": 1536}

        result = agent.ollama_chat(
            "qwen3:14b",
            "prompt",
            "http://ollama.test",
            Mock(spec=logging.Logger),
            options=options,
            timeout_seconds=240,
        )

        self.assertEqual(result, "[]")
        payload = post.call_args.kwargs["json"]
        self.assertIs(payload["think"], False)
        self.assertEqual(payload["format"], agent.ANALYSIS_SCHEMA)
        self.assertEqual(payload["options"], options)
        self.assertEqual(post.call_args.kwargs["timeout"], 240)

    @patch.object(agent.requests, "post")
    def test_invalid_ollama_envelope_is_classified_as_invalid_response(self, post):
        response = Mock()
        response.json.return_value = {"done": True}
        post.return_value = response

        with self.assertRaises(agent.AnalysisValidationError):
            agent.ollama_chat(
                "qwen3:14b",
                "prompt",
                "http://ollama.test",
                Mock(spec=logging.Logger),
                options={"num_ctx": 8192, "num_predict": 1536},
                timeout_seconds=240,
            )


class AnalysisTests(unittest.TestCase):
    def setUp(self):
        self.logger = Mock(spec=logging.Logger)
        self.results = [
            {
                "title": "Tool X",
                "url": "https://example.test/tool-x",
                "snippet": "A local coding agent.",
            }
        ]
        self.models = ["qwen3:14b", "qwen3:8b"]
        self.options = {"temperature": 0.2, "num_ctx": 8192, "num_predict": 1536}

    def analyze(self):
        return agent.analyze_results(
            self.results,
            set(),
            "16 GB VRAM",
            self.models,
            "http://ollama.test",
            self.logger,
            options=self.options,
            timeout_seconds=240,
        )

    @patch.object(agent, "ollama_chat")
    def test_timeout_retries_with_fallback(self, ollama_chat):
        ollama_chat.side_effect = [
            requests.Timeout("deadline"),
            json.dumps([valid_item()]),
        ]

        items, error, model = self.analyze()

        self.assertEqual(items, [valid_item()])
        self.assertEqual(error, "")
        self.assertEqual(model, "qwen3:8b")
        self.assertEqual(
            [call.args[0] for call in ollama_chat.call_args_list],
            self.models,
        )

    @patch.object(agent, "ollama_chat")
    def test_invalid_schema_retries_with_fallback(self, ollama_chat):
        invalid = valid_item()
        invalid["sdlc_relevance"] = 8
        ollama_chat.side_effect = [json.dumps([invalid]), json.dumps([valid_item()])]

        items, error, model = self.analyze()

        self.assertEqual(items, [valid_item()])
        self.assertEqual(error, "")
        self.assertEqual(model, "qwen3:8b")
        self.assertEqual(ollama_chat.call_count, 2)

    @patch.object(agent, "ollama_chat")
    def test_exhausted_invalid_responses_return_error(self, ollama_chat):
        ollama_chat.side_effect = ["not json", "{}"]

        items, error, model = self.analyze()

        self.assertEqual(items, [])
        self.assertIn("Tentativas LLM esgotadas", error)
        self.assertEqual(model, "qwen3:14b, qwen3:8b")
        self.assertEqual(ollama_chat.call_count, 2)

    def test_schema_validation_rejects_missing_extra_and_wrong_types(self):
        missing = valid_item()
        del missing["source_url"]
        extra = {**valid_item(), "confidence": 0.9}
        wrong_type = {**valid_item(), "hw_viability": True}

        for value in ([missing], [extra], [wrong_type]):
            with self.subTest(value=value):
                with self.assertRaises(agent.AnalysisValidationError):
                    agent.validate_analysis_items(value)

    def test_validation_rejects_source_not_present_in_search_results(self):
        with self.assertRaises(agent.AnalysisValidationError):
            agent.parse_analysis_response(
                json.dumps([valid_item()]),
                [{"url": "https://example.test/a-different-source"}],
            )

    def test_url_normalization_removes_only_known_tracking_parameters(self):
        tracked = (
            "https://Example.Test/watch?v=video-123&utm_source=newsletter"
            "&fbclid=tracking&page=2"
        )

        self.assertEqual(
            agent.normalize_url(tracked),
            "https://example.test/watch?page=2&v=video-123",
        )

    def test_url_normalization_preserves_functional_resource_identity(self):
        first = agent.normalize_url("https://youtube.com/watch?v=AAA&utm_medium=social")
        second = agent.normalize_url("https://youtube.com/watch?v=BBB&utm_medium=social")

        self.assertNotEqual(first, second)
        with self.assertRaises(agent.AnalysisValidationError):
            agent.parse_analysis_response(
                json.dumps(
                    [
                        {
                            **valid_item(),
                            "source_url": "https://youtube.com/watch?v=BBB",
                        }
                    ]
                ),
                [{"url": "https://youtube.com/watch?v=AAA&utm_source=search"}],
            )


class RunOutcomeTests(unittest.TestCase):
    def test_known_item_extraction_and_normalized_dedup_cover_tables_and_tags(self):
        backlog = """
| 3 | OpenHands (ex-OpenDevin) | Agente Autonomo |
### 11. Devstral Small 24B Q4_K_M
- modelo ativo: `qwen3-coder:30b`
"""
        known = agent.extract_known_items(backlog, [])
        values = [valid_item("OpenHands"), valid_item("Devstral"), valid_item("Qwen3-Coder 30B")]

        self.assertEqual(agent.filter_new_items(values, known, Mock(spec=logging.Logger)), [])

    def test_batch_dedup_is_progressive_for_exact_and_qualified_variants(self):
        values = [
            valid_item("Devstral Small"),
            valid_item("Devstral Small (local build)"),
            valid_item("Devstral Small"),
            valid_item("Qwen3 8B"),
            valid_item("Qwen3 14B"),
        ]

        filtered = agent.filter_new_items(values, set(), Mock(spec=logging.Logger))

        self.assertEqual(
            [item["name"] for item in filtered],
            ["Devstral Small", "Qwen3 8B", "Qwen3 14B"],
        )

    @patch.object(agent, "send_telegram")
    @patch.object(agent, "write_report")
    @patch.object(agent, "pick_models")
    @patch.object(agent, "run_searches")
    @patch.object(agent, "read_backlog")
    @patch.object(agent, "setup_logging")
    @patch.object(agent, "load_config")
    def test_empty_search_results_are_reported_as_failure_before_ollama(
        self,
        load_config,
        setup_logging,
        read_backlog,
        run_searches,
        pick_models,
        write_report,
        send_telegram,
    ):
        load_config.return_value = {
            "backlog_path": "backlog.test.md",
            "reports_dir": "reports-test",
            "ollama_url": "http://ollama.test",
            "search_queries": ["query"],
        }
        setup_logging.return_value = Mock(spec=logging.Logger)
        read_backlog.return_value = ""
        run_searches.return_value = []
        write_report.return_value = Path("report.test.md")

        self.assertEqual(agent._run(), 1)
        pick_models.assert_not_called()
        write_report.assert_called_once()
        send_telegram.assert_called_once()
        self.assertIn("Nenhum resultado", send_telegram.call_args.kwargs["llm_error"])

    @patch.object(agent, "send_telegram")
    @patch.object(agent, "update_backlog")
    @patch.object(agent, "write_report")
    @patch.object(agent, "analyze_results")
    @patch.object(agent, "pick_models")
    @patch.object(agent, "run_searches")
    @patch.object(agent, "read_backlog")
    @patch.object(agent, "setup_logging")
    @patch.object(agent, "load_config")
    def test_llm_failure_writes_reports_notifies_once_and_returns_nonzero(
        self,
        load_config,
        setup_logging,
        read_backlog,
        run_searches,
        pick_models,
        analyze_results,
        write_report,
        update_backlog,
        send_telegram,
    ):
        load_config.return_value = {
            "backlog_path": "backlog.test.md",
            "reports_dir": "reports-test",
            "ollama_url": "http://ollama.test",
            "search_queries": ["query"],
        }
        setup_logging.return_value = Mock(spec=logging.Logger)
        read_backlog.return_value = ""
        run_searches.return_value = self_results = [
            {"title": "X", "url": "https://example.test/x", "snippet": "X"}
        ]
        pick_models.return_value = ["qwen3:14b", "qwen3:8b"]
        analyze_results.return_value = (
            [],
            "Tentativas LLM esgotadas",
            "qwen3:14b, qwen3:8b",
        )
        write_report.return_value = Path("report.test.md")

        exit_code = agent._run()

        self.assertEqual(exit_code, 1)
        write_report.assert_called_once()
        send_telegram.assert_called_once()
        self.assertEqual(send_telegram.call_args.kwargs["llm_error"], "Tentativas LLM esgotadas")
        update_backlog.assert_called_once_with(
            (agent.SCRIPT_DIR / "backlog.test.md").resolve(),
            [],
            unittest.mock.ANY,
            setup_logging.return_value,
        )
        self.assertEqual(run_searches.return_value, self_results)

    def test_backlog_update_remains_idempotent_for_same_day(self):
        logger = Mock(spec=logging.Logger)
        with tempfile.TemporaryDirectory() as temp_dir:
            backlog = Path(temp_dir) / "backlog.md"
            backlog.write_text(
                "# Backlog\n\n## Novos itens pendentes de avaliacao\n",
                encoding="utf-8",
            )

            agent.update_backlog(backlog, [valid_item()], "2026-08-22", logger)
            once = backlog.read_text(encoding="utf-8")
            agent.update_backlog(backlog, [valid_item()], "2026-08-22", logger)
            twice = backlog.read_text(encoding="utf-8")

        self.assertEqual(once, twice)
        self.assertEqual(twice.count("### Pesquisa de 2026-08-22"), 1)


if __name__ == "__main__":
    unittest.main()
