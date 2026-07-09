import fcntl
from contextlib import contextmanager
from pathlib import Path

from . import git_ops, message, state as state_mod
from .notify import notify


@contextmanager
def _lock(repo: Path):
    """Serialize pipeline mutations (hook vs daemon vs CLI) per repo."""
    state_mod.gitbot_dir(repo).mkdir(parents=True, exist_ok=True)
    lock_path = state_mod.gitbot_dir(repo) / "lock"
    with lock_path.open("w") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)


def _first_line(text: str) -> str:
    return text.splitlines()[0] if text else ""


def _stage_and_fill(repo: Path, cfg: dict, st: dict, task: dict) -> bool:
    """Stage a done task's files and fill slot 1 with a generated message.

    Returns False when the task produced no staged changes (nothing to commit).
    """
    git_ops.stage(repo, task.get("files") or None)
    if not git_ops.has_staged(repo):
        return False

    msg, model, error = message.generate_or_fallback(repo, cfg, task)
    st["slot"] = {
        "task_id": task["id"],
        "message": msg,
        "model": model,
        "staged_at": state_mod.now(),
        "head": git_ops.head_sha(repo),
    }
    task["status"] = "staged"
    state_mod.write_commit_msg(repo, msg)

    note = f"Task {task['id']} staged — review & commit: {_first_line(msg)}"
    if error:
        note = f"Task {task['id']} staged with FALLBACK message (generation failed)"
    notify("gitbot", note, cfg.get("notifications", True))
    if error:
        print(f"warning: message generation failed, used fallback: {error}")
    return True


def task_done(repo: Path, cfg: dict, task_id: int, files: list[str] | None = None) -> str:
    with _lock(repo):
        st = state_mod.load(repo)
        task = state_mod.get_task(st, task_id)
        if task is None:
            task = {
                "id": task_id,
                "title": f"Task {task_id}",
                "description": "",
                "files": [],
                "status": "pending",
            }
            st["plan"].append(task)

        if files:
            task["files"] = files
        elif not task.get("files"):
            task["files"] = git_ops.dirty_files(repo)
        task["status"] = "done"

        if st.get("slot") is None:
            if _stage_and_fill(repo, cfg, st, task):
                outcome = f"staged in slot 1 (message ready, model={st['slot']['model']})"
            else:
                task["status"] = "committed"
                outcome = "no changes to stage — task marked committed"
        else:
            if task_id not in st["queue"]:
                st["queue"].append(task_id)
            outcome = f"queued behind slot 1 (queue position {st['queue'].index(task_id) + 1})"

        state_mod.save(repo, st)
        return outcome


def on_commit(repo: Path, cfg: dict) -> str:
    """Called after a commit: retire slot 1, promote the next queued task."""
    with _lock(repo):
        st = state_mod.load(repo)
        head = git_ops.head_sha(repo)
        slot = st.get("slot")

        if slot and slot.get("head") == head:
            return "no-op (commit already accounted for)"

        state_mod.clear_commit_msg(repo)

        if slot:
            task = state_mod.get_task(st, slot["task_id"])
            if task:
                task["status"] = "committed"
            st["slot"] = None

        promoted = None
        while st["queue"]:
            next_id = st["queue"].pop(0)
            task = state_mod.get_task(st, next_id)
            if task is None:
                continue
            if _stage_and_fill(repo, cfg, st, task):
                promoted = next_id
                break
            task["status"] = "committed"  # absorbed by an earlier commit

        state_mod.save(repo, st)
        if promoted is not None:
            return f"promoted task {promoted} into slot 1"
        return "slot cleared (queue empty)"
