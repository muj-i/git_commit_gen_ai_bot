import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from gitbot.providers import get_provider, ProviderError
from gitbot.providers import cli_support, claude_cli, codex_cli, gemini_cli


def result(stdout="", stderr="", code=0):
    return subprocess.CompletedProcess([], code, stdout, stderr)


class ProviderTests(unittest.TestCase):
    def test_api_key_environment_does_not_override_signed_in_accounts(self):
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "dummy", "OPENAI_API_KEY": "dummy",
                                    "GEMINI_API_KEY": "dummy", "CODEX_HOME": "/account"}):
            env = cli_support.subscription_env()
        self.assertNotIn("ANTHROPIC_API_KEY", env)
        self.assertNotIn("OPENAI_API_KEY", env)
        self.assertNotIn("GEMINI_API_KEY", env)
        self.assertEqual(env["CODEX_HOME"], "/account")

    def test_antigravity_discovered_outside_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            binary = Path(tmp) / ".gemini/bin/agy"
            binary.parent.mkdir(parents=True)
            binary.write_text("test")
            binary.chmod(0o755)
            with patch.object(cli_support.shutil, "which", return_value=None), \
                    patch.object(cli_support.Path, "home", return_value=Path(tmp)):
                self.assertEqual(cli_support.find_binary("agy"), str(binary))

    def test_codex_discovered_in_vscode_extension_without_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            binary = Path(tmp) / ".vscode/extensions/openai.chatgpt-26.1007/bin/macos-aarch64/codex"
            binary.parent.mkdir(parents=True)
            binary.write_text("test")
            binary.chmod(0o755)
            with patch.object(cli_support.shutil, "which", return_value=None), \
                    patch.object(cli_support.Path, "home", return_value=Path(tmp)), \
                    patch.object(cli_support.platform, "machine", return_value="arm64"), \
                    patch.object(cli_support.os, "access", side_effect=lambda p, _: p == binary):
                self.assertEqual(cli_support.find_binary("codex"), str(binary))

    def test_process_timeouts_and_launch_errors_become_provider_errors(self):
        for error in [subprocess.TimeoutExpired("codex", 1), FileNotFoundError("missing")]:
            with self.subTest(error=type(error).__name__), \
                    patch.object(cli_support.subprocess, "run", side_effect=error):
                with self.assertRaises(ProviderError):
                    cli_support.run_cli(["codex"], cwd="/tmp")

    def test_claude_checks_subscription_and_disables_tools(self):
        auth = result(json.dumps({"loggedIn": True, "authMethod": "claude.ai"}))
        with patch.object(claude_cli, "find_binary", return_value="claude"), \
                patch.object(claude_cli, "run_cli", side_effect=[auth, result("fix: correct login")]) as run:
            self.assertEqual(get_provider("claude-cli").generate_commit_message("prompt", "sonnet"),
                             "fix: correct login")
        args = run.call_args_list[1].args[0]
        self.assertEqual(args[args.index("--tools") + 1], "")

    def test_claude_api_login_is_not_used_for_subscription_fallback(self):
        auth = result(json.dumps({"loggedIn": True, "authMethod": "api_key"}))
        with patch.object(claude_cli, "find_binary", return_value="claude"), \
                patch.object(claude_cli, "run_cli", return_value=auth) as run:
            with self.assertRaises(ProviderError):
                get_provider("claude-cli").generate_commit_message("prompt", "sonnet")
        self.assertEqual(run.call_count, 1)

    def test_codex_reads_final_response_file_instead_of_progress_output(self):
        def run(args, **kwargs):
            if args[1] == "login":
                return result(stderr="Logged in using ChatGPT")
            self.assertIn("read-only", args)
            self.assertIn("--ignore-user-config", args)
            Path(args[args.index("--output-last-message") + 1]).write_text("feat: add login")
            return result("progress and diagnostics, not the commit message")
        with patch.object(codex_cli, "find_binary", return_value="codex"), \
                patch.object(codex_cli, "run_cli", side_effect=run):
            self.assertEqual(get_provider("codex-cli").generate_commit_message("prompt", "gpt-6.1-sol"),
                             "feat: add login")

    def test_codex_api_key_login_is_not_used(self):
        with patch.object(codex_cli, "find_binary", return_value="codex"), \
                patch.object(codex_cli, "run_cli", return_value=result(stderr="Logged in using an API key")):
            with self.assertRaises(ProviderError):
                get_provider("codex-cli").generate_commit_message("prompt", "gpt-6.1-sol")

    def test_gemini_uses_antigravity_json_response(self):
        with patch.object(gemini_cli, "find_binary", return_value="agy"), \
                patch.object(gemini_cli, "run_cli", return_value=result(json.dumps({
                    "status": "SUCCESS", "response": "chore: update settings",
                }))) as run:
            self.assertEqual(get_provider("gemini-cli").generate_commit_message("prompt", "flash"),
                             "chore: update settings")
        self.assertIn("prompt", run.call_args.args[0][2])
        self.assertIn("--sandbox", run.call_args.args[0])

    def test_gemini_rejects_authentication_errors_empty_output_and_invalid_json(self):
        for output in ['{"status":"ERROR","response":""}',
                       '{"status":"SUCCESS","response":""}', '{"status":"WAITING"}',
                       "not json", "[]"]:
            with self.subTest(output=output), \
                    patch.object(gemini_cli, "find_binary", return_value="agy"), \
                    patch.object(gemini_cli, "run_cli", return_value=result(output)):
                with self.assertRaises(ProviderError):
                    get_provider("gemini-cli").generate_commit_message("prompt", "flash")


if __name__ == "__main__":
    unittest.main()
