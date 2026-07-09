import time
from datetime import datetime
from pathlib import Path

from . import config, git_ops, pipeline, state as state_mod


def _log(message: str) -> None:
    print(f"[{datetime.now().isoformat(timespec='seconds')}] {message}", flush=True)


def check_repo(repo: Path, cfg: dict) -> None:
    """Recover pipeline state when a commit happened without the hook firing
    (GUI git clients, hook bypassed, gitbot missing from the hook's PATH)."""
    st = state_mod.load(repo)
    slot = st.get("slot")
    if not slot:
        return
    if slot.get("head") != git_ops.head_sha(repo):
        outcome = pipeline.on_commit(repo, cfg)
        _log(f"{repo}: recovered missed commit — {outcome}")


def run() -> None:
    _log(f"gitbot daemon started (poll every {config.load().get('daemon_poll_seconds', 15)}s)")
    while True:
        cfg = config.load()
        for repo in config.registered_repos():
            if not state_mod.gitbot_dir(repo).exists():
                continue
            try:
                check_repo(repo, cfg)
            except Exception as exc:
                _log(f"{repo}: error: {exc}")
        time.sleep(cfg.get("daemon_poll_seconds", 15))
