"""src/carwatch/llm/client.py"""
from anthropic import AsyncAnthropic

from carwatch.settings import get_settings

_client: AsyncAnthropic | None = None

# Deliberate spec decision (SPEC.md SS10): pin the exact dated model ID rather
# than an undated alias. Do not "correct" this to a floating alias.
MODEL = "claude-haiku-4-5-20251001"


def get_anthropic_client() -> AsyncAnthropic:
    global _client
    if _client is None:
        _client = AsyncAnthropic(api_key=get_settings().anthropic_api_key)
    return _client


async def call_classify(system_prompt: str, user_content: str) -> tuple[str, dict]:
    """Return the raw response text plus the usage/stop metadata.

    The usage dict carries `tokens_in`/`tokens_out` (for SPEC.md §18's
    `llm.call` cost-tracking event) and `stop_reason`, which lets the caller
    tell a truncated response (`"max_tokens"`) apart from one that was
    malformed for some other reason.
    """
    client = get_anthropic_client()
    response = await client.messages.create(
        model=MODEL,
        # SPEC.md §10 specified max_tokens=300, which the Fase 1 final review
        # proved arithmetically impossible: one classify object is ~30-40
        # output tokens, so even the reduced 8-item batch needs ~300 and the
        # original 20-item batch needed 600-800. Any full batch truncated
        # mid-JSON, parsed as None and was dropped, then re-attempted (and
        # re-billed) the following week — an unbounded backlog. 1200 leaves
        # real headroom for a full batch; the split-and-retry in classify.py
        # bounds the damage if this ever gets out of step again.
        max_tokens=1200,
        temperature=0,
        system=[{"type": "text", "text": system_prompt, "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": user_content}],
    )
    text = "".join(block.text for block in response.content if block.type == "text")
    usage = getattr(response, "usage", None)
    return text, {
        "tokens_in": getattr(usage, "input_tokens", None),
        "tokens_out": getattr(usage, "output_tokens", None),
        "stop_reason": getattr(response, "stop_reason", None),
    }
