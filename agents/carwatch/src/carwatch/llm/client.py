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


async def call_classify(system_prompt: str, user_content: str) -> str:
    client = get_anthropic_client()
    response = await client.messages.create(
        model=MODEL,
        max_tokens=300,  # SPEC.md §10's exact value; tight for a full 20-item batch, may truncate — see README's known risks once written (Task 17)
        temperature=0,
        system=[{"type": "text", "text": system_prompt, "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": user_content}],
    )
    return "".join(block.text for block in response.content if block.type == "text")
