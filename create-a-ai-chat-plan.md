# gitbot — AI commit-message bot (Python)

## Context

Build a new tool in the empty repo `/Users/muj/codeSpace/git_commit_gen_ai_bot` that generates Conventional-Commits messages for staged changes using the user's **Claude subscription** (via the installed `claude` CLI in headless `-p` mode — no API key billing; verified: claude v2.1.187 at `~/.local/bin/claude`, Python 3.14 available, codex not installed).

It supports two workflows:

1. **Manual mode** — user stages files themselves, runs `gitbot msg`, gets a generated commit message.
2. **Pipeline mode (2 slots)** — while working with Claude Code:
   - User asks Claude to share its task plan with the bot (`gitbot plan set`).
   - When Claude finishes task N it runs `gitbot task done N --files ...`. The bot stages those files, generates a commit message, and holds them in **slot 1** (git index + message, uncommitted). Claude keeps working on task N+1.
   - The user reviews slot 1 and commits with plain `git commit` — a `prepare-commit-msg` hook injects the generated message into the editor.
   - A `post-commit` hook promotes the next queued done-task (**slot 2** = queue) into the index, generates its message, and notifies the user. Claude moves to task N+2. Repeat.

Design must be provider-scalable (Codex etc. later) and include a launchd service so the bot daemon starts on mac restart, plus a terminal command to control it.

## Decisions (confirmed with user)

- **Language:** Python 3 (stdlib only — argparse, subprocess, json; no third-party deps).
- **Agent interface:** CLI commands + per-repo state file (works with any shell-capable agent, Codex included).
- **Model:** auto-switch by change size — small staged diff → `haiku`, large/complex → `sonnet` (thresholds configurable).
- **Commit UX:** plain `git commit` with `prepare-commit-msg` hook filling the message; `post-commit` hook triggers queue promotion.

## Project layout

```
git_commit_gen_ai_bot/
├── pyproject.toml            # console_scripts: gitbot = gitbot.cli:main
├── readme.md
├── gitbot/
│   ├── __init__.py
│   ├── cli.py                # argparse entrypoint, subcommand dispatch
│   ├── config.py             # ~/.gitbot/config.json — provider, models, thresholds, registered repos
│   ├── state.py              # per-repo .gitbot/state.json — plan, slot, queue (atomic writes)
│   ├── git_ops.py            # subprocess wrappers: stage files, diff --cached (+numstat), log, hook install
│   ├── pipeline.py           # slot state machine: on_task_done, promote_on_commit
│   ├── message.py            # prompt build, diff truncation, Conventional Commits validation/retry
│   ├── notify.py             # macOS notification via osascript
│   ├── daemon.py             # launchd-run watcher (recovery + notifications)
│   └── providers/
│       ├── __init__.py       # registry: get_provider(name)
│       ├── base.py           # Provider ABC: generate_commit_message(prompt, model) -> str
│       └── claude_cli.py     # subprocess: `claude -p --model <haiku|sonnet> --output-format text`, prompt on stdin
├── hooks/
│   ├── prepare-commit-msg    # injects slot message (skips merge/amend/-m with message)
│   └── post-commit           # calls `gitbot _on-commit` → mark committed + promote queue
└── launchd/
    └── com.muj.gitbot.plist  # RunAtLoad + KeepAlive → `gitbot daemon`
```

## Key components

### State (`.gitbot/state.json` per repo)
```json
{
  "plan":  [{"id": 1, "title": "...", "description": "...", "files": [], "status": "pending|in_progress|done|staged|committed"}],
  "slot":  {"task_id": 1, "message": "feat(auth): ...", "staged_at": "..."},
  "queue": [2, 3]
}
```
Invariant: at most one task's files occupy the git index (slot 1). Done tasks wait in `queue` until the index frees up. Writes are atomic (write temp + rename). Generated message also mirrored to `.gitbot/COMMIT_MSG` for the hook.

### CLI surface
- `gitbot init` — create `.gitbot/`, install both hooks into `.git/hooks/`, register repo in `~/.gitbot/config.json`, optionally append an agent-protocol snippet to the repo's `CLAUDE.md` (how Claude should call `gitbot plan set` / `gitbot task done`, and that it must never commit itself).
- `gitbot plan set --json '[...]'` / `gitbot plan add "title" [--desc ... --files ...]` / `gitbot plan show`
- `gitbot task done <id> [--files a b c]` — core pipeline entry. If `--files` omitted, snapshot all dirty (unstaged/untracked) paths. Slot empty → stage files, generate message, fill slot, notify; slot occupied → enqueue.
- `gitbot msg` — manual mode: generate message for currently staged changes → `.gitbot/COMMIT_MSG` + stdout (hook will pick it up on next `git commit`).
- `gitbot status` — plan, slot (with message preview), queue.
- `gitbot _on-commit` — internal, called by post-commit hook: mark slot task committed, promote next queued task (stage its files, generate message, notify).
- `gitbot service install|uninstall|start|stop|status` — manage the launchd agent (`launchctl bootstrap/bootout gui/$UID`). `install` = the "init on mac restart" trigger command.
- `gitbot daemon` — the long-running process launchd starts: periodically checks registered repos for missed promotions (e.g. commit made while hook failed or from a GUI client without hooks) and re-notifies about slots awaiting review.

### Provider abstraction (scalability)
`Provider` ABC with one required method: `generate_commit_message(prompt: str, model: str) -> str`. Registry maps config name → class. Ships with `claude-cli`; adding Codex later = new `codex_cli.py` (wrapping `codex exec`) + config change `"provider": "codex-cli"`. An `anthropic-api` provider (official SDK) can be added the same way if the user ever wants API billing.

`claude-cli` invocation: `claude -p --model <model> --output-format text` with the prompt on stdin — headless, uses the logged-in subscription.

### Model auto-switch
From `git diff --cached --numstat`: if changed lines ≤ 150 **and** files ≤ 5 → `haiku`, else `sonnet`. Thresholds + model names live in `~/.gitbot/config.json` (`model_small`, `model_large`, `small_max_lines`, `small_max_files`).

### Message generation
Prompt = task title/description (pipeline mode) + `git diff --cached` (truncated ~15k chars; overflow summarized with `--stat`) + last 10 commit subjects for style + strict instruction to output only a Conventional Commits message (`type(scope): subject` ≤ 72 chars, blank line, short body). Validate the first line against a conventional-commit regex; one retry on failure, then fall back to a `chore:`-prefixed subject.

### Hooks
- `prepare-commit-msg`: if `.gitbot/COMMIT_MSG` exists and the commit isn't a merge/amend/`-m`-with-message, write it into the commit message file (user still reviews/edits in editor).
- `post-commit`: `gitbot _on-commit` (fails silently if gitbot missing so git never breaks).

Edge case (documented in readme): a file edited in task 1 (staged) and again in task 2 — the index keeps task 1's content until commit; re-staging on promotion picks up task 2's content. This is correct git behavior and matches the pipeline.

### launchd
`gitbot service install` writes `~/Library/LaunchAgents/com.muj.gitbot.plist` (Label `com.muj.gitbot`, ProgramArguments → `gitbot daemon`, RunAtLoad + KeepAlive, logs to `~/.gitbot/daemon.log`) and bootstraps it — daemon then survives restarts.

## Implementation order

0. `git init` the project repo + `.gitignore` (Python artifacts, `.gitbot/`, `~` logs); commit incrementally as milestones land, using gitbot's own conventional-commit style
1. `pyproject.toml` + package skeleton + `config.py`/`state.py`
2. `git_ops.py` + `providers/` (base + claude_cli) + `message.py` (with model auto-switch)
3. `gitbot msg` + `gitbot init` + hooks (manual mode working end-to-end)
4. `pipeline.py` + `plan`/`task done`/`status`/`_on-commit` (pipeline mode)
5. `notify.py`, `daemon.py`, `service` subcommands + plist
6. Full README (see below) + the CLAUDE.md protocol snippet

## README.md (full, proper doc — user-requested deliverable)

Replace the empty `readme.md` with a complete `README.md` covering:

- **What it is** — one-paragraph pitch + feature list (subscription-based generation, 2-slot pipeline, auto model switch, provider-pluggable, launchd autostart)
- **How it works** — architecture diagram (ASCII) of the 2-slot pipeline and the Claude ↔ gitbot ↔ user flow
- **Requirements** — macOS, Python 3.10+, git, `claude` CLI logged in to a subscription
- **Installation** — `pip install -e .`, `gitbot init` per repo, `gitbot service install` for boot autostart
- **Usage**
  - Manual mode walkthrough (`git add` → `gitbot msg` → `git commit`)
  - Pipeline mode walkthrough (plan set → task done → review → commit → auto-promotion), incl. the exact prompt to give Claude
  - Full CLI reference table (every subcommand, args, examples)
- **Configuration** — `~/.gitbot/config.json` reference table (provider, model_small/model_large, thresholds) + per-repo `.gitbot/` contents
- **Git hooks** — what gets installed, when each fires, how to bypass (`git commit --no-verify`, merge/amend behavior)
- **Adding a new AI provider** — Provider ABC contract + a short Codex example stub
- **Autostart on mac restart** — launchd details, log location, service commands
- **Troubleshooting & FAQ** — same-file-in-two-tasks edge case, hook not firing, claude CLI auth, notification permissions
- **CLAUDE.md snippet** — the copy-paste block that teaches Claude the gitbot protocol

## Verification

In a scratch git repo (scratchpad dir):
1. `pip install -e .` → `gitbot init` → assert `.gitbot/` + both hooks installed.
2. Sanity-check provider: `echo hi | claude -p --model haiku` returns text.
3. Manual mode: edit file, `git add`, `gitbot msg` → valid conventional message in `.gitbot/COMMIT_MSG`; `git commit` (hook fills editor; use `GIT_EDITOR=true` in test) → commit message matches.
4. Pipeline: `gitbot plan set` with 3 tasks; edit files → `gitbot task done 1 --files ...` → assert files staged + slot filled; edit more → `task done 2` → assert queued (index untouched); `git commit` → assert task 1 committed with generated message **and** task 2 auto-promoted (staged + new message + notification fired).
5. Large-diff case → assert provider called with `sonnet`; small diff → `haiku` (log the chosen model).
6. `gitbot service install` → `launchctl list | grep com.muj.gitbot` shows the daemon running.
