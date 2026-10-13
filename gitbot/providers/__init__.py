from .base import Provider, ProviderError
from .claude_cli import ClaudeCLIProvider
from .codex_cli import CodexCLIProvider
from .gemini_cli import GeminiCLIProvider

_REGISTRY: dict[str, type[Provider]] = {
    ClaudeCLIProvider.name: ClaudeCLIProvider,
    CodexCLIProvider.name: CodexCLIProvider,
    GeminiCLIProvider.name: GeminiCLIProvider,
}


def get_provider(name: str) -> Provider:
    try:
        return _REGISTRY[name]()
    except KeyError:
        available = ", ".join(sorted(_REGISTRY))
        raise ProviderError(f"unknown provider '{name}' (available: {available})") from None
