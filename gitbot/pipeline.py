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


def _auto_enabled(cfg: dict, st: dict) -> bool:
    if "auto_commit" in st:
        return bool(st["auto_commit"])
    return bool(cfg.get("auto_commit", False))


def _stage_and_fill(repo: Path, cfg: dict, st: dict, task: dict, announce: bool = True) -> bool:
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

    if announce:
        note = f"Task {task['id']} staged — review & commit: {_first_line(msg)}"
        if error:
            note = f"Task {task['id']} staged with FALLBACK message (generation failed)"
        notify("gitbot", note, cfg.get("notifications", True))
    if error:
        print(f"warning: message generation failed, used fallback: {error}")
    return True


def _auto_commit_all(repo: Path, cfg: dict, st: dict) -> list[str]:
    """Auto mode: commit slot 1 and keep draining the queue. Returns subjects."""
    subjects: list[str] = []
    while st.get("slot"):
        slot = st["slot"]
        git_ops.run(repo, "commit", "-m", slot["message"])
        subject = _first_line(slot["message"])
        subjects.append(subject)
        task = state_mod.get_task(st, slot["task_id"])
        if task:
            task["status"] = "committed"
        st["slot"] = None
        state_mod.clear_commit_msg(repo)
        notify("gitbot", f"auto-committed: {subject}", cfg.get("notifications", True))

        while st["queue"]:
            next_id = st["queue"].pop(0)
            queued = state_mod.get_task(st, next_id)
            if queued is None:
                continue
            if _stage_and_fill(repo, cfg, st, queued, announce=False):
                break
            queued["status"] = "committed"
    return subjects


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

        auto = _auto_enabled(cfg, st)
        if st.get("slot") is None:
            if _stage_and_fill(repo, cfg, st, task, announce=not auto):
                outcome = f"staged in slot 1 (message ready, model={st['slot']['model']})"
            else:
                task["status"] = "committed"
                outcome = "no changes to stage — task marked committed"
        else:
            if task_id not in st["queue"]:
                st["queue"].append(task_id)
            outcome = f"queued behind slot 1 (queue position {st['queue'].index(task_id) + 1})"

        if auto and st.get("slot"):
            subjects = _auto_commit_all(repo, cfg, st)
            if subjects:
                outcome = f"auto-committed {len(subjects)} commit(s): " + "; ".join(subjects)

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

        if promoted is not None and _auto_enabled(cfg, st):
            subjects = _auto_commit_all(repo, cfg, st)
            state_mod.save(repo, st)
            return f"auto-committed {len(subjects)} commit(s): " + "; ".join(subjects)

        state_mod.save(repo, st)
        if promoted is not None:
            return f"promoted task {promoted} into slot 1"
        return "slot cleared (queue empty)"
