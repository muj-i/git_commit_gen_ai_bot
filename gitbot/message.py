import json
import re

from . import git_ops
from .providers import ProviderError, get_provider
from .spinner import spin

CONVENTIONAL_RE = re.compile(
    r"^(feat|fix|refactor|perf|docs|test|chore|style|build|ci|revert)"
    r"(\([^)]+\))?!?: .+"
)

RULES = """Rules:
- Conventional Commits format: type(scope): subject
- Allowed types: feat, fix, refactor, perf, docs, test, chore, style, build, ci, revert
- Subject line at most 72 characters, imperative mood, no trailing period
- Add a blank line and a short body (2-4 bullet points) only when the change is non-trivial
- Output ONLY the commit message. No preamble, no code fences, no explanation."""


def choose_model(cfg: dict, n_files: int, n_lines: int) -> str:
    small = n_files <= cfg["small_max_files"] and n_lines <= cfg["small_max_lines"]
    return cfg["model_small"] if small else cfg["model_large"]


def provider_candidates(cfg: dict, n_files: int, n_lines: int):
    """Keep the configured primary, then try each fallback with its own model."""
    primary = cfg["provider"]
    names = [primary, *cfg.get("fallback_providers", ["codex-cli", "gemini-cli"])]
    seen = set()
    for name in names:
        if name in seen:
            continue
        seen.add(name)
        if name == primary and cfg.get("model_override"):
            model = cfg["model_override"]
        elif name == "codex-cli":
            model = cfg.get("codex_model", "gpt-6.1-sol")
        elif name == "gemini-cli":
            model = cfg.get("gemini_model", "gemini-3.8-flash-medium")
        else:
            model = choose_model(cfg, n_files, n_lines)
        yield name, model


def build_prompt(diff: str, task: dict | None = None, subjects: list[str] | None = None) -> str:
    parts = ["Write a git commit message for the staged changes below.", "", RULES]
    if task:
        parts += ["", "Task context:", f"Title: {task.get('title', '')}"]
        if task.get("description"):
            parts.append(f"Description: {task['description']}")
    if subjects:
        parts += ["", "Recent commit subjects in this repo (match their style):"]
        parts += [f"- {s}" for s in subjects]
    parts += ["", "Staged diff:", "```diff", diff, "```"]
    return "\n".join(parts)


def clean(raw: str) -> str:
    text = raw.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    text = re.sub(r"^(here.s |the |a )?commit message:?\s*", "", text, flags=re.IGNORECASE)
    return text.strip()


def is_conventional(message: str) -> bool:
    first = message.splitlines()[0] if message else ""
    return bool(CONVENTIONAL_RE.match(first))


def fallback_message(repo, task: dict | None = None) -> str:
    if task and task.get("title"):
        subject = f"chore: {task['title']}"
    else:
        files = git_ops.staged_files(repo)
        target = files[0] if len(files) == 1 else f"{len(files)} files"
        subject = f"chore: update {target}"
    return subject[:72]


def truncated_diff(repo, cfg: dict) -> str:
    diff = git_ops.staged_diff(repo)
    limit = cfg["diff_max_chars"]
    if len(diff) > limit:
        diff = (
            diff[:limit]
            + "\n... [diff truncated] ...\n\nFull change summary:\n"
            + git_ops.staged_stat(repo)
        )
    return diff


def generate(repo, cfg: dict, task: dict | None = None) -> tuple[str, str]:
    """Return (message, provider/model) from the first usable signed-in CLI."""
    n_files, n_lines = git_ops.staged_numstat(repo)
    prompt = build_prompt(
        truncated_diff(repo, cfg), task=task, subjects=git_ops.recent_subjects(repo)
    )
    retry_prompt = (
        prompt
        + "\n\nYour previous attempt did not follow the Conventional Commits format. "
        + "The first line MUST match `type(scope): subject`. Try again."
    )
    errors = []
    for name, model in provider_candidates(cfg, n_files, n_lines):
        label = f"{name} / {model}"
        try:
            provider = get_provider(name)
            with spin(f"generating commit message · {label} · {n_files} file(s), {n_lines} line(s)"):
                message = clean(provider.generate_commit_message(prompt, model))
            if not is_conventional(message):
                with spin(f"retrying · {label} · first attempt wasn't Conventional Commits"):
                    message = clean(provider.generate_commit_message(retry_prompt, model))
            if not is_conventional(message):
                raise ProviderError("response did not follow Conventional Commits after retry")
            return message, label
        except ProviderError as exc:
            errors.append(f"{label}: {exc}")
            print(f"note: {label} unavailable: {exc}")
    raise ProviderError("all commit-message providers failed — " + "; ".join(errors))


def group_changes(repo, cfg: dict) -> list[dict] | None:
    """Ask the model to split the dirty working tree into logical commit groups.

    Returns [{"title": ..., "files": [...]}, ...] in commit order, or None when
    there is nothing to group or the model output is unusable.
    """
    dirty = git_ops.dirty_files(repo)
    if not dirty:
        return None

    diff_excerpt = git_ops.run(repo, "diff")[:8000]
    prompt = (
        "Group the following uncommitted changes into logical, self-contained commits.\n\n"
        "Changed files:\n"
        + "\n".join(f"- {f}" for f in dirty)
        + "\n\nUnstaged diff (tracked files only; untracked files are new):\n```diff\n"
        + diff_excerpt
        + "\n```\n\n"
        "Rules:\n"
        "- Every file appears in exactly ONE group.\n"
        "- Group files that belong to the same change/topic; separate unrelated work.\n"
        "- Order groups so foundational changes come first.\n"
        '- Output ONLY a JSON array: [{"title": "imperative summary", "files": ["path", ...]}]\n'
        "- No prose, no code fences, no explanation."
    )
    for name, model in provider_candidates(cfg, 0, 0):
        try:
            provider = get_provider(name)
            with spin(f"grouping {len(dirty)} changed file(s) into commits · {name} / {model}"):
                raw = provider.generate_commit_message(prompt, model)
            groups = _parse_groups(raw, dirty)
            if groups:
                return groups
        except ProviderError:
            continue
    return None


def _parse_groups(raw: str, dirty: list[str]) -> list[dict] | None:
    match = re.search(r"\[.*\]", clean(raw), re.DOTALL)
    if not match:
        return None
    try:
        groups = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None

    dirty_set = set(dirty)
    seen: set[str] = set()
    valid: list[dict] = []
    for group in groups if isinstance(groups, list) else []:
        if not isinstance(group, dict):
            continue
        paths = group.get("files", [])
        if not isinstance(paths, list):
            continue
        files = [f for f in paths if isinstance(f, str) and f in dirty_set and f not in seen]
        if not files:
            continue
        seen.update(files)
        valid.append({"title": str(group.get("title") or "update files"), "files": files})
    leftovers = [f for f in dirty if f not in seen]
    if leftovers and valid:
        valid.append({"title": "update remaining files", "files": leftovers})
    return valid or None


def generate_or_fallback(repo, cfg: dict, task: dict | None = None) -> tuple[str, str, str | None]:
    """Return (message, provider/model, error); callers must stop on error."""
    try:
        message, model = generate(repo, cfg, task)
        return message, model, None
    except (ProviderError, git_ops.GitError) as exc:
        return fallback_message(repo, task), "fallback", str(exc)
