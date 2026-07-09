import os
import plistlib
import shutil
import subprocess
import sys
from pathlib import Path

from . import config

LABEL = "com.muj.gitbot"


def plist_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"


def gitbot_executable() -> str:
    exe = shutil.which("gitbot") or sys.argv[0]
    return str(Path(exe).resolve())


def _launchctl(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["launchctl", *args], capture_output=True, text=True)


def install() -> str:
    config.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    log = config.CONFIG_DIR / "daemon.log"
    payload = {
        "Label": LABEL,
        "ProgramArguments": [gitbot_executable(), "daemon"],
        "RunAtLoad": True,
        "KeepAlive": True,
        "StandardOutPath": str(log),
        "StandardErrorPath": str(log),
        "EnvironmentVariables": {
            "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
        },
    }
    plist_path().parent.mkdir(parents=True, exist_ok=True)
    with plist_path().open("wb") as fh:
        plistlib.dump(payload, fh)
    stop()  # reload cleanly if already running
    result = start()
    return f"installed {plist_path()} — {result}"


def uninstall() -> str:
    stop()
    plist_path().unlink(missing_ok=True)
    return f"removed {plist_path()}"


def start() -> str:
    if not plist_path().exists():
        return "not installed — run `gitbot service install` first"
    result = _launchctl("bootstrap", f"gui/{os.getuid()}", str(plist_path()))
    if result.returncode != 0 and "already" not in result.stderr.lower():
        return f"launchctl bootstrap failed: {result.stderr.strip()}"
    return "daemon started (survives restarts)"


def stop() -> str:
    result = _launchctl("bootout", f"gui/{os.getuid()}/{LABEL}")
    if result.returncode != 0:
        return "daemon was not running"
    return "daemon stopped"


def status() -> str:
    result = _launchctl("print", f"gui/{os.getuid()}/{LABEL}")
    if result.returncode != 0:
        return "not loaded"
    for line in result.stdout.splitlines():
        line = line.strip()
        if line.startswith("state =") or line.startswith("pid ="):
            return f"loaded ({line})"
    return "loaded"
