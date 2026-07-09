import json
from datetime import datetime, timezone
from pathlib import Path

EMPTY = {"plan": [], "slot": None, "queue": []}


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def gitbot_dir(repo: Path) -> Path:
    return Path(repo) / ".gitbot"


def state_file(repo: Path) -> Path:
    return gitbot_dir(repo) / "state.json"


def commit_msg_file(repo: Path) -> Path:
    return gitbot_dir(repo) / "COMMIT_MSG"


def load(repo: Path) -> dict:
    state = {k: (v.copy() if isinstance(v, (dict, list)) else v) for k, v in EMPTY.items()}
    path = state_file(repo)
    if path.exists():
        try:
            state.update(json.loads(path.read_text()))
        except (json.JSONDecodeError, OSError):
            pass
    return state


def save(repo: Path, state: dict) -> None:
    gitbot_dir(repo).mkdir(parents=True, exist_ok=True)
    state["updated_at"] = now()
    tmp = state_file(repo).with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2) + "\n")
    tmp.replace(state_file(repo))


def get_task(state: dict, task_id) -> dict | None:
    return next((t for t in state.get("plan", []) if t.get("id") == task_id), None)


def write_commit_msg(repo: Path, message: str) -> None:
    gitbot_dir(repo).mkdir(parents=True, exist_ok=True)
    commit_msg_file(repo).write_text(message.rstrip("\n") + "\n")


def read_commit_msg(repo: Path) -> str | None:
    path = commit_msg_file(repo)
    if path.exists():
        return path.read_text().strip() or None
    return None


def clear_commit_msg(repo: Path) -> None:
    commit_msg_file(repo).unlink(missing_ok=True)
