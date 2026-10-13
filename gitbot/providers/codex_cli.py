import tempfile
from pathlib import Path

from .base import Provider, ProviderError
from .cli_support import AUTH_TIMEOUT_SECONDS, find_binary, require_success, run_cli


class CodexCLIProvider(Provider):
    """Use the Codex CLI's existing ChatGPT login, with a pinned Sol model."""

    name = "codex-cli"

    def generate_commit_message(self, prompt: str, model: str) -> str:
        binary = find_binary("codex")
        with tempfile.TemporaryDirectory(prefix="gitbot-codex-") as cwd:
            status = run_cli([binary, "login", "status"], cwd=cwd, timeout=AUTH_TIMEOUT_SECONDS)
            if status.returncode != 0 or "chatgpt" not in (status.stdout + status.stderr).lower():
                raise ProviderError("Codex is not signed in with ChatGPT — run `codex login`")
            output_file = Path(cwd) / "message.txt"
            result = run_cli(
                [binary, "exec", "--model", model, "--sandbox", "read-only",
                 "--ignore-user-config", "--ephemeral", "--skip-git-repo-check",
                 "-c", 'approval_policy="never"', "--color", "never",
                 "--output-last-message", str(output_file), "-"],
                prompt="Respond only to the supplied text. Do not use tools.\n\n" + prompt,
                cwd=cwd,
            )
            require_success(result, "codex exec")
            try:
                output = output_file.read_text().strip()
            except OSError as exc:
                raise ProviderError("codex exec did not write a final response") from exc
        if not output:
            raise ProviderError("codex exec returned empty output")
        return output
