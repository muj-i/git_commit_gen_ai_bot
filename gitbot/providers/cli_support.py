"""Find subscription CLIs and run them without API-key overrides."""

import os
import platform
import shutil
import subprocess
from pathlib import Path

from .base import ProviderError

TIMEOUT_SECONDS = 240
AUTH_TIMEOUT_SECONDS = 15


def subscription_env() -> dict[str, str]:
    env = os.environ.copy()
    for key in (
        "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL",
        "CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_VERTEX", "CLAUDE_CODE_USE_FOUNDRY",
        "OPENAI_API_KEY", "CODEX_API_KEY", "OPENAI_BASE_URL",
        "GEMINI_API_KEY", "GOOGLE_API_KEY", "GOOGLE_GEMINI_BASE_URL", "CLAUDECODE",
    ):
        env.pop(key, None)
    return env


def find_binary(name: str) -> str:
    found = shutil.which(name)
    if found:
        return found
    home = Path.home()
    candidates = [home / ".local/bin" / name, Path("/opt/homebrew/bin") / name,
                  Path("/usr/local/bin") / name]
    if name == "agy":
        candidates.insert(0, home / ".gemini/bin/agy")
    if name == "codex":
        target = "macos-aarch64" if platform.machine() == "arm64" else "macos-x86_64"
        candidates.extend(sorted(
            (home / ".vscode/extensions").glob(f"openai.chatgpt-*/bin/{target}/codex"),
            reverse=True,
        ))
    for path in candidates:
        if path.is_file() and os.access(path, os.X_OK):
            return str(path)
    raise ProviderError(f"{name} CLI not found — install it and sign in first")


def run_cli(args: list[str], *, cwd: str, prompt: str = "",
            timeout: int = TIMEOUT_SECONDS) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(
            args, input=prompt, capture_output=True, text=True, cwd=cwd,
            env=subscription_env(), timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise ProviderError(f"{Path(args[0]).name} timed out after {timeout}s") from exc
    except OSError as exc:
        raise ProviderError(f"{Path(args[0]).name} could not run: {exc}") from exc


def require_success(result: subprocess.CompletedProcess, command: str) -> None:
    if result.returncode != 0:
        detail = (result.stderr.strip() or result.stdout.strip())[:500]
        detail = detail or "request failed; check login and model access"
        raise ProviderError(f"{command} exited {result.returncode}: {detail}")
