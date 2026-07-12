from anthropic import AsyncAnthropic

from .config import settings


class ClaudeNotConfiguredError(Exception):
    """Raised when ANTHROPIC_API_KEY isn't set — a clear, specific failure
    rather than letting the SDK raise its own opaque auth error deep in the
    pipeline."""


_client: AsyncAnthropic | None = None


def get_client() -> AsyncAnthropic:
    global _client
    if not settings.anthropic_api_key:
        raise ClaudeNotConfiguredError(
            "ANTHROPIC_API_KEY is not set. Copy backend/.env.example to backend/.env "
            "and fill it in."
        )
    if _client is None:
        _client = AsyncAnthropic(api_key=settings.anthropic_api_key)
    return _client
