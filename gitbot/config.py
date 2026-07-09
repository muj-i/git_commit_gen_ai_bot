import json
from pathlib import Path

CONFIG_DIR = Path.home() / ".gitbot"
CONFIG_FILE = CONFIG_DIR / "config.json"

DEFAULTS = {
    "provider": "claude-cli",
    "model_small": "haiku",
    "model_large": "sonnet",
    "small_max_lines": 150,
    "small_max_files": 5,
    "diff_max_chars": 15000,
    "notifications": True,
    "auto_commit": False,
    "daemon_poll_seconds": 15,
    "repos": [],
}


def load() -> dict:
    cfg = dict(DEFAULTS)
    if CONFIG_FILE.exists():
        try:
            cfg.update(json.loads(CONFIG_FILE.read_text()))
        except (json.JSONDecodeError, OSError):
            pass
    return cfg


def save(cfg: dict) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    tmp = CONFIG_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(cfg, indent=2, sort_keys=True) + "\n")
    tmp.replace(CONFIG_FILE)


def register_repo(path: Path) -> None:
    cfg = load()
    repo = str(Path(path).resolve())
    if repo not in cfg["repos"]:
        cfg["repos"].append(repo)
        save(cfg)


def registered_repos() -> list[Path]:
    return [Path(p) for p in load().get("repos", [])]
