import argparse
import json
import sys
from pathlib import Path

from . import (
    __version__,
    config,
    daemon,
    git_ops,
    hooks,
    message,
    pipeline,
    service,
    state as state_mod,
)

CLAUDE_MD_MARKER = "## gitbot commit protocol"

CLAUDE_MD_SNIPPET = """
## gitbot commit protocol

This repo uses gitbot: it stages finished work and generates commit messages
for the user to review. Follow this protocol exactly:

1. When starting multi-task work, share your task plan with the bot:
   `gitbot plan set --json '[{"id": 1, "title": "...", "description": "..."}, ...]'`
2. After finishing each task, report it together with the files you changed:
   `gitbot task done <id> --files <file1> <file2> ...`
   gitbot stages those files and prepares a commit message; the user reviews
   the staged changes and commits themselves.
3. NEVER run `git add`, `git commit`, or `git push` yourself.
4. Move on to the next task immediately after `gitbot task done` — do not wait
   for the user to commit.
5. Run `gitbot status` if you need to see the plan / slot / queue state.
"""


def _repo(args) -> Path:
    return git_ops.repo_root(getattr(args, "repo", None) or ".")


def _next_id(plan: list[dict]) -> int:
    return max((t.get("id", 0) for t in plan), default=0) + 1


def cmd_init(args) -> int:
    repo = _repo(args)
    state_mod.save(repo, state_mod.load(repo))
    git_ops.exclude_gitbot_dir(repo)
    for action in hooks.install(repo):
        print(f"  {action}")
    config.register_repo(repo)

    if args.claude_md:
        claude_md = repo / "CLAUDE.md"
        existing = claude_md.read_text() if claude_md.exists() else ""
        if CLAUDE_MD_MARKER not in existing:
            with claude_md.open("a") as fh:
                fh.write(CLAUDE_MD_SNIPPET)
            print("  added gitbot protocol to CLAUDE.md")
        else:
            print("  CLAUDE.md already has the gitbot protocol")

    print(f"gitbot initialized in {repo}")
    print("next: `gitbot service install` (once, for the boot daemon) — then just work.")
    return 0


def cmd_plan_set(args) -> int:
    repo = _repo(args)
    raw = Path(args.file).read_text() if args.file else args.json
    try:
        tasks = json.loads(raw)
    except json.JSONDecodeError as exc:
        print(f"error: invalid JSON: {exc}", file=sys.stderr)
        return 1
    if not isinstance(tasks, list) or not all(isinstance(t, dict) and t.get("title") for t in tasks):
        print("error: expected a JSON list of {id?, title, description?, files?}", file=sys.stderr)
        return 1

    st = state_mod.load(repo)
    plan: list[dict] = []
    for task in tasks:
        plan.append(
            {
                "id": task.get("id") or _next_id(plan),
                "title": task["title"],
                "description": task.get("description", ""),
                "files": task.get("files", []),
                "status": "pending",
            }
        )
    if st.get("slot"):
        print("note: slot 1 is still awaiting review from the previous plan — commit it when ready.")
    st["plan"] = plan
    st["queue"] = []
    state_mod.save(repo, st)
    print(f"plan set: {len(plan)} task(s)")
    for task in plan:
        print(f"  [{task['id']}] {task['title']}")
    return 0


def cmd_plan_add(args) -> int:
    repo = _repo(args)
    st = state_mod.load(repo)
    task = {
        "id": args.id or _next_id(st["plan"]),
        "title": args.title,
        "description": args.desc or "",
        "files": args.files or [],
        "status": "pending",
    }
    st["plan"].append(task)
    state_mod.save(repo, st)
    print(f"added task [{task['id']}] {task['title']}")
    return 0


def cmd_plan_show(args) -> int:
    return cmd_status(args)


def cmd_plan_clear(args) -> int:
    repo = _repo(args)
    st = state_mod.load(repo)
    st["plan"] = []
    st["queue"] = []
    state_mod.save(repo, st)
    print("plan cleared (slot untouched)")
    return 0


def cmd_task_done(args) -> int:
    repo = _repo(args)
    outcome = pipeline.task_done(repo, config.load(), args.id, args.files)
    print(f"task {args.id}: {outcome}")
    msg = state_mod.read_commit_msg(repo)
    st = state_mod.load(repo)
    if st.get("slot") and st["slot"]["task_id"] == args.id and msg:
        print("--- commit message ready for review ---")
        print(msg)
    return 0


def cmd_msg(args) -> int:
    repo = _repo(args)
    if not git_ops.has_staged(repo):
        print("error: nothing staged — `git add` your changes first", file=sys.stderr)
        return 1
    cfg = config.load()
    if args.model:
        cfg = {**cfg, "model_small": args.model, "model_large": args.model}
    msg, model, error = message.generate_or_fallback(repo, cfg)
    if error:
        print(f"warning: generation failed, using fallback: {error}", file=sys.stderr)
    state_mod.write_commit_msg(repo, msg)
    print(f"# model: {model} — message saved; plain `git commit` will pre-fill it")
    print(msg)
    return 0


def cmd_commit(args) -> int:
    repo = _repo(args)
    cfg = config.load()
    if not git_ops.has_staged(repo):
        print("error: nothing staged — `git add` what you want committed first", file=sys.stderr)
        return 1

    st = state_mod.load(repo)
    slot = st.get("slot")
    if slot and not args.regenerate and not args.model:
        msg, model = slot["message"], slot.get("model", "?")
        source = f"slot 1, task {slot['task_id']}"
    else:
        if args.model:
            cfg = {**cfg, "model_small": args.model, "model_large": args.model}
        msg, model, error = message.generate_or_fallback(repo, cfg)
        if error:
            print(f"warning: generation failed, using fallback: {error}", file=sys.stderr)
        source = "generated now"

    git_ops.run(repo, "commit", "-m", msg)
    print(f"committed ({source}, model {model}):")
    for line in msg.splitlines():
        print(f"  | {line}")
    # Idempotent with the post-commit hook: whoever runs first promotes the queue.
    outcome = pipeline.on_commit(repo, cfg)
    print(f"pipeline: {outcome}")
    return 0


def cmd_status(args) -> int:
    repo = _repo(args)
    st = state_mod.load(repo)

    print(f"repo: {repo}")
    if st["plan"]:
        print("plan:")
        for task in st["plan"]:
            print(f"  [{task['id']}] {task['status']:<10} {task['title']}")
    else:
        print("plan: (empty)")

    slot = st.get("slot")
    if slot:
        print("slot 1: staged, awaiting your review — run `git commit`")
        print(f"  task {slot['task_id']} · model {slot['model']} · staged {slot['staged_at']}")
        for line in slot["message"].splitlines():
            print(f"  | {line}")
    else:
        print("slot 1: empty")

    print(f"queue: {st['queue'] or '(empty)'}")
    staged = git_ops.staged_files(repo)
    if staged:
        print(f"staged files: {', '.join(staged)}")
    return 0


def cmd_on_commit(args) -> int:
    repo = _repo(args)
    outcome = pipeline.on_commit(repo, config.load())
    print(f"on-commit: {outcome}")
    return 0


def cmd_daemon(_args) -> int:
    daemon.run()
    return 0


def cmd_service(args) -> int:
    action = {
        "install": service.install,
        "uninstall": service.uninstall,
        "start": service.start,
        "stop": service.stop,
        "status": service.status,
    }[args.action]
    print(action())
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="gitbot",
        description="AI commit-message bot — stages task work and generates "
        "Conventional Commits messages with your Claude subscription.",
    )
    parser.add_argument("--version", action="version", version=f"gitbot {__version__}")
    parser.add_argument("--repo", help="repo path (default: current directory)")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("init", help="set up gitbot in the current repo (hooks, state, exclude)")
    p.add_argument("--claude-md", action="store_true", help="append the agent protocol to CLAUDE.md")
    p.set_defaults(func=cmd_init)

    plan = sub.add_parser("plan", help="manage the task plan")
    plan_sub = plan.add_subparsers(dest="plan_command", required=True)
    p = plan_sub.add_parser("set", help="replace the plan from JSON")
    group = p.add_mutually_exclusive_group(required=True)
    group.add_argument("--json", help='JSON list: [{"id":1,"title":"...","description":"..."}]')
    group.add_argument("--file", help="path to a JSON file with the plan")
    p.set_defaults(func=cmd_plan_set)
    p = plan_sub.add_parser("add", help="append one task")
    p.add_argument("title")
    p.add_argument("--desc")
    p.add_argument("--id", type=int)
    p.add_argument("--files", nargs="+")
    p.set_defaults(func=cmd_plan_add)
    p = plan_sub.add_parser("show", help="show plan / slot / queue")
    p.set_defaults(func=cmd_plan_show)
    p = plan_sub.add_parser("clear", help="clear plan and queue")
    p.set_defaults(func=cmd_plan_clear)

    task = sub.add_parser("task", help="report task progress")
    task_sub = task.add_subparsers(dest="task_command", required=True)
    p = task_sub.add_parser("done", help="task finished: stage files + generate message (or queue)")
    p.add_argument("id", type=int)
    p.add_argument("--files", nargs="+", help="files changed by this task (default: all dirty files)")
    p.set_defaults(func=cmd_task_done)

    p = sub.add_parser("msg", help="generate a message for whatever is currently staged")
    p.add_argument("--model", help="force a model (default: auto haiku/sonnet by change size)")
    p.set_defaults(func=cmd_msg)

    p = sub.add_parser("commit", help="generate the message AND commit the staged changes (no editor)")
    p.add_argument("--model", help="force a model (implies regenerating the message)")
    p.add_argument("--regenerate", action="store_true", help="ignore the slot message and generate fresh")
    p.set_defaults(func=cmd_commit)

    p = sub.add_parser("status", help="show plan / slot / queue / staged files")
    p.set_defaults(func=cmd_status)

    p = sub.add_parser("service", help="manage the launchd daemon (starts on mac login/restart)")
    p.add_argument("action", choices=["install", "uninstall", "start", "stop", "status"])
    p.set_defaults(func=cmd_service)

    p = sub.add_parser("daemon", help="run the watcher in the foreground (launchd entrypoint)")
    p.set_defaults(func=cmd_daemon)

    p = sub.add_parser("_on-commit")  # internal: called by the post-commit hook
    p.add_argument("--repo", help="repo path (hook passes this explicitly)")
    p.set_defaults(func=cmd_on_commit)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except git_ops.GitError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
