from pathlib import Path

from . import git_ops

MARKER = "managed by gitbot"

PREPARE_COMMIT_MSG = """#!/bin/sh
# gitbot prepare-commit-msg hook (managed by gitbot)
HOOK_DIR="$(cd "$(dirname "$0")" && pwd)"
[ -x "$HOOK_DIR/prepare-commit-msg.pre-gitbot" ] && "$HOOK_DIR/prepare-commit-msg.pre-gitbot" "$@"

COMMIT_MSG_FILE="$1"
COMMIT_SOURCE="$2"
# Only fill plain `git commit` (no -m/-t/merge/amend/squash).
[ -n "$COMMIT_SOURCE" ] && exit 0
REPO="$(git rev-parse --show-toplevel 2>/dev/null)" || exit 0
GITBOT_MSG="$REPO/.gitbot/COMMIT_MSG"
if [ -s "$GITBOT_MSG" ]; then
  TMP="$COMMIT_MSG_FILE.gitbot"
  cat "$GITBOT_MSG" > "$TMP"
  printf '\\n' >> "$TMP"
  cat "$COMMIT_MSG_FILE" >> "$TMP"
  mv "$TMP" "$COMMIT_MSG_FILE"
fi
exit 0
"""

POST_COMMIT = """#!/bin/sh
# gitbot post-commit hook (managed by gitbot)
HOOK_DIR="$(cd "$(dirname "$0")" && pwd)"
[ -x "$HOOK_DIR/post-commit.pre-gitbot" ] && "$HOOK_DIR/post-commit.pre-gitbot" "$@"

command -v gitbot >/dev/null 2>&1 || exit 0
REPO="$(git rev-parse --show-toplevel 2>/dev/null)" || exit 0
[ -d "$REPO/.gitbot" ] || exit 0
# Background so `git commit` returns immediately; promotion runs async.
nohup gitbot _on-commit --repo "$REPO" >> "$REPO/.gitbot/hook.log" 2>&1 &
exit 0
"""

_HOOKS = {
    "prepare-commit-msg": PREPARE_COMMIT_MSG,
    "post-commit": POST_COMMIT,
}


def install(repo: Path) -> list[str]:
    """Install gitbot hooks, preserving any existing hooks as *.pre-gitbot."""
    hooks_dir = git_ops.git_path(repo, "hooks")
    hooks_dir.mkdir(parents=True, exist_ok=True)
    actions = []
    for name, content in _HOOKS.items():
        target = hooks_dir / name
        if target.exists() and MARKER not in target.read_text():
            backup = hooks_dir / f"{name}.pre-gitbot"
            target.replace(backup)
            actions.append(f"existing {name} hook preserved as {name}.pre-gitbot (still runs first)")
        target.write_text(content)
        target.chmod(0o755)
        actions.append(f"installed {name} hook")
    return actions
