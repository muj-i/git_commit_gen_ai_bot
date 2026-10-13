import contextlib
import io
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from gitbot import config, message
from gitbot.providers import ProviderError


class MessageFallbackTests(unittest.TestCase):
    def setUp(self):
        self.cfg = dict(config.DEFAULTS)
        self.enterContext(patch.multiple(
            message.git_ops, staged_numstat=Mock(return_value=(1, 10)),
            staged_diff=Mock(return_value="+new content"), recent_subjects=Mock(return_value=[]),
            staged_files=Mock(return_value=["file.py"]),
        ))
        self.enterContext(patch.object(message, "spin", side_effect=lambda *_: contextlib.nullcontext()))
        self.enterContext(contextlib.redirect_stdout(io.StringIO()))

    def providers(self, outputs):
        providers = {name: SimpleNamespace(generate_commit_message=Mock(side_effect=values))
                     for name, values in outputs.items()}
        resolver = self.enterContext(patch.object(message, "get_provider", side_effect=providers.__getitem__))
        return providers, resolver

    def test_claude_success_never_contacts_fallbacks(self):
        providers, resolver = self.providers({"claude-cli": ["feat: add login"]})
        self.assertEqual(message.generate("repo", self.cfg), ("feat: add login", "claude-cli / sonnet"))
        resolver.assert_called_once_with("claude-cli")
        self.assertEqual(providers["claude-cli"].generate_commit_message.call_args.args[1], "sonnet")

    def test_claude_quota_failure_uses_sol_and_reports_actual_provider(self):
        providers, resolver = self.providers({
            "claude-cli": [ProviderError("quota exhausted")], "codex-cli": ["fix: handle login"],
        })
        self.assertEqual(message.generate("repo", self.cfg)[1], "codex-cli / gpt-6.1-sol")
        self.assertEqual([call.args[0] for call in resolver.call_args_list], ["claude-cli", "codex-cli"])
        self.assertEqual(providers["codex-cli"].generate_commit_message.call_args.args[1], "gpt-6.1-sol")

    def test_missing_login_and_unavailable_sol_fall_back_to_gemini(self):
        providers, resolver = self.providers({
            "claude-cli": [ProviderError("not signed in")],
            "codex-cli": [ProviderError("model unavailable")], "gemini-cli": ["chore: update files"],
        })
        self.assertEqual(message.generate("repo", self.cfg)[1], "gemini-cli / gemini-3.8-flash-medium")
        self.assertEqual(resolver.call_count, 3)
        self.assertEqual(providers["gemini-cli"].generate_commit_message.call_args.args[1],
                         "gemini-3.8-flash-medium")

    def test_invalid_response_retries_then_moves_to_next_provider(self):
        providers, _ = self.providers({
            "claude-cli": ["explanation", "still explanation"], "codex-cli": ["fix: correct response"],
        })
        self.assertEqual(message.generate("repo", self.cfg)[1], "codex-cli / gpt-6.1-sol")
        self.assertEqual(providers["claude-cli"].generate_commit_message.call_count, 2)

    def test_retry_failure_does_not_label_synthetic_text_as_ai_generated(self):
        self.providers({"claude-cli": ["invalid", ProviderError("timed out")],
                        "codex-cli": [ProviderError("not signed in")],
                        "gemini-cli": [ProviderError("not signed in")]})
        _, label, error = message.generate_or_fallback("repo", self.cfg)
        self.assertEqual(label, "fallback")
        self.assertIn("all commit-message providers failed", error)

    def test_fallbacks_can_be_disabled_and_duplicate_providers_are_not_retried(self):
        self.cfg["fallback_providers"] = ["claude-cli"]
        providers, _ = self.providers({"claude-cli": [ProviderError("offline")]})
        with self.assertRaises(ProviderError):
            message.generate("repo", self.cfg)
        self.assertEqual(providers["claude-cli"].generate_commit_message.call_count, 1)

    def test_model_override_applies_only_to_primary_provider(self):
        self.cfg["model_override"] = "haiku"
        providers, _ = self.providers({"claude-cli": [ProviderError("unavailable")],
                                      "codex-cli": ["chore: update configuration"]})
        message.generate("repo", self.cfg)
        self.assertEqual(providers["claude-cli"].generate_commit_message.call_args.args[1], "haiku")
        self.assertEqual(providers["codex-cli"].generate_commit_message.call_args.args[1], "gpt-6.1-sol")

    def test_codex_primary_honors_explicit_model_override(self):
        self.cfg.update(provider="codex-cli", model_override="gpt-6-sol")
        providers, _ = self.providers({"codex-cli": ["chore: update configuration"]})
        self.assertEqual(message.generate("repo", self.cfg)[1], "codex-cli / gpt-6-sol")

    def test_grouping_uses_same_fallback_order_and_ignores_malformed_groups(self):
        self.providers({"claude-cli": [ProviderError("quota")],
                        "codex-cli": ['[{"files":null}]'],
                        "gemini-cli": ['[{"title":"update one","files":["a.py"]}]']})
        with patch.object(message.git_ops, "dirty_files", return_value=["a.py", "b.py"]), \
                patch.object(message.git_ops, "run", return_value="diff"):
            self.assertEqual(message.group_changes("repo", self.cfg), [
                {"title": "update one", "files": ["a.py"]},
                {"title": "update remaining files", "files": ["b.py"]},
            ])


if __name__ == "__main__":
    unittest.main()
