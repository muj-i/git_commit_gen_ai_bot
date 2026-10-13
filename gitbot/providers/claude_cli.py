import json
import tempfile

from .base import Provider, ProviderError
from .cli_support import AUTH_TIMEOUT_SECONDS, find_binary, require_success, run_cli


class ClaudeCLIProvider(Provider):
    """Generates messages with `claude -p` — headless Claude Code using the
    logged-in subscription (no API key billing)."""

    name = "claude-cli"
    binary = "claude"

    def generate_commit_message(self, prompt: str, model: str) -> str:
        binary = find_binary(self.binary)
        with tempfile.TemporaryDirectory(prefix="gitbot-claude-") as cwd:
            status = run_cli([binary, "auth", "status"], cwd=cwd, timeout=AUTH_TIMEOUT_SECONDS)
            try:
                auth = json.loads(status.stdout)
            except json.JSONDecodeError as exc:
                raise ProviderError("could not check Claude subscription login") from exc
            if (status.returncode != 0 or not isinstance(auth, dict)
                    or not auth.get("loggedIn")
                    or auth.get("authMethod") not in ("claude.ai", "oauth_token")):
                raise ProviderError("Claude subscription is not signed in — run `claude auth login`")
            result = run_cli(
                [binary, "-p", "--model", model, "--output-format", "text",
                 "--tools", "", "--no-session-persistence", "--safe-mode"],
                prompt=prompt, cwd=cwd,
            )
        require_success(result, "claude -p")
        output = result.stdout.strip()
        if not output:
            raise ProviderError("claude -p returned empty output")
        return output
