import subprocess
from pathlib import Path


class GitError(RuntimeError):
    pass


def run(repo: Path, *args: str, check: bool = True) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True
    )
    if check and result.returncode != 0:
        raise GitError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout


def repo_root(cwd: str | Path = ".") -> Path:
    result = subprocess.run(
        ["git", "-C", str(cwd), "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise GitError("not inside a git repository")
    return Path(result.stdout.strip())


def git_path(repo: Path, name: str) -> Path:
    out = run(repo, "rev-parse", "--git-path", name).strip()
    path = Path(out)
    return path if path.is_absolute() else Path(repo) / path


def head_sha(repo: Path) -> str | None:
    result = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, text=True
    )
    return result.stdout.strip() if result.returncode == 0 else None


def head_subject(repo: Path) -> str | None:
    result = subprocess.run(
        ["git", "-C", str(repo), "log", "-1", "--format=%s"],
        capture_output=True,
        text=True,
    )
    return result.stdout.strip() if result.returncode == 0 else None


def is_tracked(repo: Path, path: str) -> bool:
    result = subprocess.run(
        ["git", "-C", str(repo), "ls-files", "--error-unmatch", "--", path],
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


def stage(repo: Path, files: list[str] | None = None) -> None:
    if not files:
        run(repo, "add", "-A")
        return
    stageable = [f for f in files if (Path(repo) / f).exists() or is_tracked(repo, f)]
    if stageable:
        run(repo, "add", "-A", "--", *stageable)


def staged_files(repo: Path) -> list[str]:
    out = run(repo, "diff", "--cached", "--name-only")
    return [line for line in out.splitlines() if line.strip()]


def has_staged(repo: Path) -> bool:
    return bool(staged_files(repo))


def staged_diff(repo: Path) -> str:
    return run(repo, "diff", "--cached")


def staged_stat(repo: Path) -> str:
    return run(repo, "diff", "--cached", "--stat")


def staged_numstat(repo: Path) -> tuple[int, int]:
    """Return (files_changed, total_lines_changed) for the staged diff."""
    out = run(repo, "diff", "--cached", "--numstat")
    files = 0
    lines = 0
    for line in out.splitlines():
        parts = line.split("\t")
        if len(parts) < 3:
            continue
        files += 1
        added, deleted = parts[0], parts[1]
        if added.isdigit():
            lines += int(added)
        if deleted.isdigit():
            lines += int(deleted)
    return files, lines


def dirty_files(repo: Path) -> list[str]:
    """Unstaged modifications, deletions, and untracked files (worktree side only)."""
    out = run(repo, "status", "--porcelain=v1", "-z", "-uall")
    entries = out.split("\0")
    files: list[str] = []
    i = 0
    while i < len(entries):
        entry = entries[i]
        i += 1
        if len(entry) < 4:
            continue
        index_status, worktree_status, path = entry[0], entry[1], entry[3:]
        if index_status in "RC":
            i += 1  # rename/copy entries carry the original path in the next field
        if worktree_status != " " or entry[:2] == "??":
            files.append(path)
    return files


def recent_subjects(repo: Path, n: int = 10) -> list[str]:
    result = subprocess.run(
        ["git", "-C", str(repo), "log", f"-{n}", "--format=%s"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return []
    return [s for s in result.stdout.splitlines() if s.strip()]


def exclude_gitbot_dir(repo: Path) -> None:
    """Keep .gitbot/ out of git status via .git/info/exclude."""
    exclude = git_path(repo, "info/exclude")
    exclude.parent.mkdir(parents=True, exist_ok=True)
    existing = exclude.read_text() if exclude.exists() else ""
    if ".gitbot/" not in existing:
        with exclude.open("a") as fh:
            if existing and not existing.endswith("\n"):
                fh.write("\n")
            fh.write(".gitbot/\n")
