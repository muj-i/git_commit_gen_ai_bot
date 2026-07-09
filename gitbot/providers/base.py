from abc import ABC, abstractmethod


class ProviderError(RuntimeError):
    pass


class Provider(ABC):
    """One AI backend able to turn a prompt into a commit message.

    Implementations must be side-effect free: read the prompt, return raw
    model text. Model selection, prompt construction, validation, and
    fallbacks live outside the provider.
    """

    name = "base"

    @abstractmethod
    def generate_commit_message(self, prompt: str, model: str) -> str:
        """Return the raw model output for the given prompt."""
