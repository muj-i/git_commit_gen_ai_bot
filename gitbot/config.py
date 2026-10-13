import json
from pathlib import Path

CONFIG_DIR = Path.home() / ".gitbot"
CONFIG_FILE = CONFIG_DIR / "config.json"

DEFAULTS = {
    "provider": "claude-cli",
    "fallback_providers": ["codex-cli", "gemini-cli"],
    "codex_model": "gpt-6.1-sol",
    "gemini_model": "gemini-3.8-flash-medium",
    "model_small": "sonnet",
    "model_large": "sonnet",
    "small_max_lines": 150,
    "small_max_files": 5,
    "diff_max_chars": 15000,
    "notifications": True,
    "auto_commit": True,
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
