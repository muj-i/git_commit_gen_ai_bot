import subprocess
import sys

NOTIFICATION_SCRIPT = """on run argv
    display notification (item 2 of argv) with title (item 1 of argv)
end run
"""


def notify(title: str, message: str, enabled: bool = True) -> bool:
    """Submit a macOS notification; report sender failures without failing Git."""
    if not enabled or sys.platform != "darwin":
        return False
    try:
        result = subprocess.run(
            ["/usr/bin/osascript", "-e", NOTIFICATION_SCRIPT, "--", title, message],
            capture_output=True, text=True, timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        print(f"warning: gitbot notification could not be sent: {exc}", file=sys.stderr)
        return False
    if result.returncode != 0:
        detail = result.stderr.strip() or f"osascript exited {result.returncode}"
        print(f"warning: gitbot notification could not be sent: {detail}", file=sys.stderr)
        return False
    return True
