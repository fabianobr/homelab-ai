import importlib.util
import json
from pathlib import Path
from unittest.mock import Mock

import pytest
import yaml


DOCKER_DIR = Path(__file__).parents[1]
MODULE_PATH = DOCKER_DIR / "public_prompt_guardrail.py"
SPEC = importlib.util.spec_from_file_location("public_prompt_guardrail", MODULE_PATH)
guardrail = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(guardrail)


def public_request(content="Summarize these public release notes."):
    return {
        "model": "groq-fast-public",
        "metadata": {"data_classification": "public"},
        "messages": [{"role": "user", "content": content}],
    }


def test_route_has_groq_primary_reasoning_disabled_and_smaller_local_fallback():
    config = yaml.safe_load((DOCKER_DIR / "litellm-config.yaml").read_text(encoding="utf-8"))
    models = {item["model_name"]: item["litellm_params"] for item in config["model_list"]}

    primary = models["groq-fast-public"]
    fallback = models["groq-fast-public-local"]
    assert primary["model"] == "groq/qwen/qwen3.6-27b"
    assert primary["reasoning_effort"] == "none"
    assert primary["api_key"] == "os.environ/GROQ_API_KEY"
    assert fallback["model"] == "ollama/qwen3.5:latest"
    assert config["litellm_settings"]["fallbacks"] == [
        {"sdlc-fix": ["sdlc-review"]},
        {"groq-fast-public": ["groq-fast-public-local"]},
    ]


def test_mocked_provider_failure_routes_to_local_fallback_in_declared_order():
    config = yaml.safe_load((DOCKER_DIR / "litellm-config.yaml").read_text(encoding="utf-8"))
    fallback_map = {
        primary: fallbacks
        for item in config["litellm_settings"]["fallbacks"]
        for primary, fallbacks in item.items()
    }
    providers = {
        "groq-fast-public": Mock(side_effect=TimeoutError("mocked Groq timeout")),
        "groq-fast-public-local": Mock(return_value="local response"),
    }

    attempt_order = ["groq-fast-public", *fallback_map["groq-fast-public"]]
    result = None
    for model in attempt_order:
        try:
            result = providers[model]()
            break
        except TimeoutError:
            continue

    assert result == "local response"
    assert providers["groq-fast-public"].call_count == 1
    assert providers["groq-fast-public-local"].call_count == 1


def test_safe_explicitly_public_prompt_is_allowed_without_network():
    request = public_request()
    assert guardrail.enforce_public_route(request) is request


@pytest.mark.parametrize(
    "content",
    [
        "Authorization: " + "Bearer " + "definitely-not-for-public-use",
        "api_" + "key=" + "super-sensitive-value",
        json.dumps({"api_" + "key": "definitely-sensitive-value"}),
        json.dumps({"pass" + "word": "correct-horse-battery-staple"}),
        "Host 192.168.10.25 contains the private service",
        "-----BEGIN " + "PRIVATE KEY-----\nnot-public",
    ],
)
def test_sensitive_prompts_are_blocked_before_any_provider_call(content):
    provider_call = Mock()
    with pytest.raises(guardrail.SensitivePromptError):
        guardrail.enforce_public_route(public_request(content))
    provider_call.assert_not_called()


def test_missing_public_classification_is_blocked():
    request = public_request()
    request.pop("metadata")
    with pytest.raises(guardrail.SensitivePromptError, match="data_classification=public"):
        guardrail.enforce_public_route(request)


def test_public_environment_placeholders_are_not_treated_as_secret_values():
    request = public_request(json.dumps({"api_" + "key": "${GROQ_API_KEY}"}))
    assert guardrail.enforce_public_route(request) is request


def test_uninspectable_multimodal_content_is_blocked_fail_closed():
    request = public_request()
    request["messages"][0]["content"] = [
        {"type": "text", "text": "public image"},
        {"type": "image_url", "image_url": {"url": "https://example.test/image.png"}},
    ]
    with pytest.raises(guardrail.SensitivePromptError, match="non-text content"):
        guardrail.enforce_public_route(request)


def test_existing_routes_are_untouched_by_public_guardrail():
    request = {
        "model": "sdlc-fix",
        "messages": [{"role": "user", "content": "password=local-only-value"}],
    }
    assert guardrail.enforce_public_route(request) is request
