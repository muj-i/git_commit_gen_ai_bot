import shutil
import subprocess

from .base import Provider, ProviderError

TIMEOUT_SECONDS = 240


class ClaudeCLIProvider(Provider):
    """Generates messages with `claude -p` — headless Claude Code using the
    logged-in subscription (no API key billing)."""

    name = "claude-cli"
    binary = "claude"

    def generate_commit_message(self, prompt: str, model: str) -> str:
        if shutil.which(self.binary) is None:
            raise ProviderError(
                "claude CLI not found on PATH — install Claude Code and run `claude` once to log in"
            )
        try:
            result = subprocess.run(
                [self.binary, "-p", "--model", model, "--output-format", "text"],
                input=prompt,
                capture_output=True,
                text=True,
                timeout=TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired as exc:
            raise ProviderError(f"claude -p timed out after {TIMEOUT_SECONDS}s") from exc
        if result.returncode != 0:
            raise ProviderError(
                f"claude -p exited {result.returncode}: {result.stderr.strip()[:500]}"
            )
        output = result.stdout.strip()
        if not output:
            raise ProviderError("claude -p returned empty output")
        return output
