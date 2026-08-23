"""Fail-closed input guardrail for the optional Groq public-data route.

This module deliberately has no network access. It runs before provider selection
and rejects requests that were not explicitly classified as public or that contain
common secret/private-infrastructure indicators.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any

try:
    from litellm.integrations.custom_guardrail import CustomGuardrail
except ImportError:  # Allows deterministic unit tests without installing LiteLLM.
    class CustomGuardrail:  # type: ignore[no-redef]
        def __init__(self, **_: Any) -> None:
            pass


PUBLIC_ROUTE_NAMES = frozenset(
    {
        "groq-fast-public",
        "groq/qwen/qwen3.6-27b",
        "qwen/qwen3.6-27b",
    }
)

_SENSITIVE_PATTERNS = (
    ("private key", re.compile(r"-----BEGIN (?:[A-Z ]+ )?PRIVATE KEY-----", re.I)),
    (
        "authorization header",
        re.compile(r"\bauthorization\s*:\s*(?:bearer|basic)\s+\S+", re.I),
    ),
    (
        "provider token",
        re.compile(r"\b(?:gsk|gh[pousr]|glpat|xox[baprs])-?[A-Za-z0-9_-]{12,}\b"),
    ),
    ("OpenAI-style token", re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b")),
    ("AWS access key", re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b")),
    (
        "assigned secret",
        re.compile(
            r"(?im)['\"]?\b(?:api[_-]?key|secret|token|password|passwd|pwd)\b"
            r"['\"]?\s*(?::|=)\s*['\"]?"
            r"(?!\$\{|<|REDACTED\b|EXAMPLE\b|CHANGE_ME\b)"
            r"[^\s'\";,]{8,}"
        ),
    ),
    (
        "private network address",
        re.compile(
            r"\b(?:10(?:\.\d{1,3}){3}|192\.168(?:\.\d{1,3}){2}|"
            r"172\.(?:1[6-9]|2\d|3[01])(?:\.\d{1,3}){2})\b"
        ),
    ),
    (
        "local hostname",
        re.compile(r"\b(?:localhost|[a-z0-9-]+\.(?:local|internal))\b", re.I),
    ),
)


class SensitivePromptError(ValueError):
    """Raised before any provider call when the public-route contract fails."""


def _route_is_protected(model: object) -> bool:
    return isinstance(model, str) and model.casefold() in PUBLIC_ROUTE_NAMES


def _is_explicitly_public(data: dict[str, Any]) -> bool:
    metadata = data.get("metadata")
    return (
        isinstance(metadata, dict)
        and isinstance(metadata.get("data_classification"), str)
        and metadata["data_classification"].casefold() == "public"
    )


def _iter_text(value: object) -> Iterable[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for nested in value.values():
            yield from _iter_text(nested)
    elif isinstance(value, (list, tuple)):
        for nested in value:
            yield from _iter_text(nested)


def sensitive_reason(data: dict[str, Any]) -> str | None:
    """Return a non-sensitive rejection reason, or ``None`` for public text."""
    messages = data.get("messages")
    if not isinstance(messages, list) or not messages:
        return "missing messages"

    for message in messages:
        if not isinstance(message, dict):
            return "invalid message structure"
        content = message.get("content")
        if not isinstance(content, str):
            # Images, files and arbitrary content parts cannot be inspected by
            # this deterministic text-only guardrail, so the public route fails closed.
            return "non-text content"

    inspected = {"messages": messages, "tools": data.get("tools", [])}
    for text in _iter_text(inspected):
        for label, pattern in _SENSITIVE_PATTERNS:
            if pattern.search(text):
                return label
    return None


def enforce_public_route(data: dict[str, Any]) -> dict[str, Any]:
    """Validate the opt-in public route without modifying or logging its prompt."""
    if not _route_is_protected(data.get("model")):
        return data
    if not _is_explicitly_public(data):
        raise SensitivePromptError(
            "groq-fast-public requires metadata.data_classification=public"
        )
    reason = sensitive_reason(data)
    if reason:
        raise SensitivePromptError(
            f"groq-fast-public blocked request before provider call: {reason}"
        )
    return data


class PublicPromptGuardrail(CustomGuardrail):
    """LiteLLM pre-call hook for ``groq-fast-public``."""

    async def async_pre_call_hook(
        self,
        user_api_key_dict: Any,
        cache: Any,
        data: dict[str, Any],
        call_type: Any,
    ) -> dict[str, Any]:
        del user_api_key_dict, cache, call_type
        return enforce_public_route(data)
