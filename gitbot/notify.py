import json
import subprocess
import sys


def notify(title: str, message: str, enabled: bool = True) -> None:
    if not enabled or sys.platform != "darwin":
        return
    script = f"display notification {json.dumps(message)} with title {json.dumps(title)}"
    try:
        subprocess.run(["osascript", "-e", script], capture_output=True, timeout=10)
    except Exception:
        pass
