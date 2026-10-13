import argparse
import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from gitbot import cli, config, pipeline, state
from gitbot.providers import ProviderError


class NotificationTests(unittest.TestCase):
    def setUp(self):
        self.repo = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.cfg = dict(config.DEFAULTS)
        self.st = {"plan": [{"id": 1, "title": "update login", "status": "pending",
                             "files": ["login.py"]}], "slot": None, "queue": []}
        state.save(self.repo, self.st)
        self.git = dict(stage=Mock(return_value=[]), has_staged=Mock(return_value=True),
            head_sha=Mock(return_value="old-head"), run=Mock(return_value=""),
            head_subject=Mock(return_value="fix: update login"),
            repo_root=Mock(return_value=self.repo))
        self.enterContext(patch.multiple(pipeline.git_ops, **self.git))
        self.notifications = self.enterContext(patch.object(pipeline, "notify"))

    def generated(self, model="codex-cli / gpt-6.1-sol"):
        return self.enterContext(patch.object(pipeline.message, "generate_or_fallback",
                                             return_value=("fix: update login", model, None)))

    def test_auto_commit_notification_and_history_record_actual_fallback(self):
        self.generated()
        pipeline.task_done(self.repo, self.cfg, 1, ["login.py"])
        note = self.notifications.call_args.args[1]
        self.assertIn("auto-committed", note)
        self.assertIn("codex-cli / gpt-6.1-sol", note)
        task = state.load(self.repo)["plan"][0]
        self.assertEqual(task["status"], "committed")
        self.assertEqual(task["model"], "codex-cli / gpt-6.1-sol")

    def test_review_notification_and_plain_commit_include_gemini_model(self):
        self.cfg["auto_commit"] = False
        self.generated("gemini-cli / gemini-3.8-flash-medium")
        pipeline.task_done(self.repo, self.cfg, 1, ["login.py"])
        self.assertIn("gemini-cli / gemini-3.8-flash-medium", self.notifications.call_args.args[1])
        self.git["head_sha"].return_value = "new-head"
        pipeline.on_commit(self.repo, self.cfg)
        self.assertIn("committed · gemini-cli / gemini-3.8-flash-medium",
                      self.notifications.call_args.args[1])
        self.assertEqual(self.git["run"].call_count, 0)

    def test_all_providers_failed_preserves_task_and_never_commits_synthetic_message(self):
        with patch.object(pipeline.message, "generate_or_fallback",
                          return_value=("chore: synthetic fallback", "fallback", "all providers failed")):
            with self.assertRaises(ProviderError):
                pipeline.task_done(self.repo, self.cfg, 1, ["login.py"])
        self.git["run"].assert_not_called()
        current = state.load(self.repo)
        self.assertEqual(current["plan"][0]["status"], "done")
        self.assertIsNone(current["slot"])
        self.assertIsNone(state.read_commit_msg(self.repo))
        self.assertIn("Commit paused", self.notifications.call_args.args[1])

    def test_queue_notifications_keep_each_commits_own_model(self):
        self.st["plan"].append({"id": 2, "title": "update settings", "status": "done",
                                "files": ["settings.py"]})
        self.st["queue"] = [2]
        state.save(self.repo, self.st)
        with patch.object(pipeline.message, "generate_or_fallback", side_effect=[
            ("fix: update login", "claude-cli / sonnet", None),
            ("chore: update settings", "codex-cli / gpt-6.1-sol", None),
        ]):
            pipeline.task_done(self.repo, self.cfg, 1, ["login.py"])
        notes = [call.args[1] for call in self.notifications.call_args_list]
        self.assertIn("claude-cli / sonnet", notes[0])
        self.assertIn("codex-cli / gpt-6.1-sol", notes[1])

    def test_regeneration_updates_slot_metadata_used_by_commit_notification(self):
        self.cfg["auto_commit"] = False
        self.generated("claude-cli / sonnet")
        pipeline.task_done(self.repo, self.cfg, 1, ["login.py"])
        cli._update_slot_message(self.repo, "fix: regenerate login message", "codex-cli / gpt-6.1-sol")
        current = state.load(self.repo)
        self.assertEqual(current["slot"]["model"], "codex-cli / gpt-6.1-sol")
        self.assertEqual(current["plan"][0]["model"], "codex-cli / gpt-6.1-sol")

    def test_manual_commit_failure_returns_error_without_committing(self):
        args = argparse.Namespace(repo=str(self.repo), all=False, regenerate=False, model=None)
        with patch.object(cli.config, "load", return_value=self.cfg), \
                patch.object(cli.message, "generate_or_fallback",
                             return_value=("chore: synthetic", "fallback", "unavailable")), \
                contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(cli.cmd_commit(args), 1)
        self.git["run"].assert_not_called()


if __name__ == "__main__":
    unittest.main()
