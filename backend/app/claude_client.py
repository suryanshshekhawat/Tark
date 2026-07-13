import asyncio

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import BaseMessage

from .config import settings


class ClaudeNotConfiguredError(Exception):
    """Raised when ANTHROPIC_API_KEY isn't set — a clear, specific failure
    rather than letting the SDK raise its own opaque auth error deep in the
    pipeline."""


# A proof with several steps, each firing ENSEMBLE_SIZE candidate-generation
# calls concurrently (real_pipeline.py), can reach dozens of simultaneous
# Claude calls from a single request with no cap at all. This semaphore is a
# process-wide ceiling on in-flight Claude calls, independent of the Lean
# subprocess semaphore in real_pipeline.py — that one protects CPU/disk, this
# one protects against tripping Anthropic's own rate limits.
_claude_semaphore = asyncio.Semaphore(settings.claude_concurrency_limit)


def get_llm(max_tokens: int) -> ChatAnthropic:
    """Constructs a LangChain chat model bound to Claude. Construction is
    cheap (no network call), so callers get a fresh instance per `max_tokens`
    they need rather than sharing a cache keyed on it.

    Switched from the raw `anthropic` SDK to `langchain-anthropic` so the
    formalize/decompose/repair stages can run as LangGraph nodes (see
    real_pipeline.py) — swarms.ai was evaluated first but its Agent class
    unconditionally sends a `temperature` param that the Claude Sonnet 5 API
    now rejects outright ("temperature is deprecated for this model"),
    verified directly against the live API and against swarms' own
    litellm_wrapper.py source, with no public way to suppress it.
    """
    if not settings.anthropic_api_key:
        raise ClaudeNotConfiguredError(
            "ANTHROPIC_API_KEY is not set. Copy backend/.env.example to backend/.env "
            "and fill it in."
        )
    return ChatAnthropic(
        model=settings.claude_model,
        api_key=settings.anthropic_api_key,
        max_tokens=max_tokens,
        max_retries=settings.claude_max_retries,
    )


async def invoke_llm(bound_llm, messages: list) -> BaseMessage:
    """Every Claude call in the pipeline goes through this rather than
    calling `.ainvoke()` directly, so `_claude_semaphore` actually applies
    process-wide instead of per-call-site.
    """
    async with _claude_semaphore:
        return await bound_llm.ainvoke(messages)


def cached_system_message(prompt: str) -> dict:
    """Wraps a system prompt as a cacheable content block (Anthropic's
    5-minute ephemeral prompt cache). Every decompose/formalize/repair call
    shares an unchanging system-prompt+tools prefix — verified live that a
    repeat call with an unchanged prefix reads ~100% of it from cache
    (`usage_metadata.input_token_details.cache_read`) instead of
    reprocessing it, which matters most for repair rounds and repeat runs of
    the same proof within the TTL, not for the very first call of a
    request (which still pays full price to populate the cache).
    """
    return {"role": "system", "content": [{"type": "text", "text": prompt, "cache_control": {"type": "ephemeral"}}]}


def cached_tool(tool: dict) -> dict:
    """Marks a tool schema as the end of the cacheable prefix — Anthropic
    caches the request up to and including the last content block or tool
    bearing `cache_control`, so this should be applied to the last tool in
    whatever list is passed to `bind_tools`.
    """
    return {**tool, "cache_control": {"type": "ephemeral"}}
