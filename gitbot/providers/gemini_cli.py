import json
import tempfile

from .base import Provider, ProviderError
from .cli_support import find_binary, require_success, run_cli


class GeminiCLIProvider(Provider):
    """Use Gemini Flash through Antigravity's supported CLI and cached login."""

    name = "gemini-cli"

    def generate_commit_message(self, prompt: str, model: str) -> str:
        binary = find_binary("agy")
        with tempfile.TemporaryDirectory(prefix="gitbot-gemini-") as cwd:
            result = run_cli(
                [binary, "--print", "Respond only to the supplied text. Do not use tools.\n\n" + prompt,
                 "--model", model, "--output-format", "json", "--mode", "plan",
                 "--sandbox", "--disable-slash-commands", "--print-timeout", "240s"],
                cwd=cwd,
            )
        require_success(result, "agy --print")
        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise ProviderError("Antigravity returned invalid JSON") from exc
        if not isinstance(payload, dict) or payload.get("status") != "SUCCESS":
            raise ProviderError("Antigravity did not complete the request; check login and model access")
        output = payload.get("response")
        if not isinstance(output, str) or not output.strip():
            raise ProviderError("Antigravity returned empty output")
        return output.strip()
