import contextlib
import importlib
import io
import subprocess
import unittest
from unittest.mock import patch

notifications = importlib.import_module("gitbot.notify")


class NotificationDeliveryTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch.object(notifications.sys, "platform", "darwin"))

    def test_unicode_and_quotes_are_arguments_instead_of_applescript_source(self):
        title = 'gitbot "commit"'
        message = 'auto-committed · codex-cli / gpt-6.1-sol: fix: বাংলা "quote" \\path\nbody'
        with patch.object(notifications.subprocess, "run", return_value=
                          subprocess.CompletedProcess([], 0, "", "")) as run:
            self.assertTrue(notifications.notify(title, message))
        args = run.call_args.args[0]
        self.assertEqual(args[-3:], ["--", title, message])
        self.assertNotIn(message, args[2])
        self.assertNotIn("\\u00b7", args[2])
        self.assertIn("item 2 of argv", args[2])

    def test_applescript_errors_are_reported_without_failing_commit(self):
        error = io.StringIO()
        with patch.object(notifications.subprocess, "run", return_value=
                          subprocess.CompletedProcess([], 1, "", "syntax error (-2741)")), \
                contextlib.redirect_stderr(error):
            self.assertFalse(notifications.notify("gitbot", "committed"))
        self.assertIn("notification could not be sent", error.getvalue())
        self.assertIn("syntax error (-2741)", error.getvalue())

    def test_missing_sender_and_timeout_are_reported(self):
        for failure in [FileNotFoundError("missing osascript"),
                        subprocess.TimeoutExpired("osascript", 10)]:
            error = io.StringIO()
            with self.subTest(failure=type(failure).__name__), \
                    patch.object(notifications.subprocess, "run", side_effect=failure), \
                    contextlib.redirect_stderr(error):
                self.assertFalse(notifications.notify("gitbot", "committed"))
            self.assertIn("notification could not be sent", error.getvalue())

    def test_disabled_or_unsupported_notifications_do_not_launch_sender(self):
        with patch.object(notifications.subprocess, "run") as run:
            self.assertFalse(notifications.notify("gitbot", "committed", enabled=False))
            with patch.object(notifications.sys, "platform", "linux"):
                self.assertFalse(notifications.notify("gitbot", "committed"))
        run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
