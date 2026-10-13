# gitbot — AI commit-message bot for macOS

gitbot uses your existing **Claude, Codex, and Antigravity logins** to generate [Conventional Commits](https://www.conventionalcommits.org/) messages. It stages finished work task-by-task and commits automatically by default; `gitbot auto off` holds each changeset for review. It tries **Claude first → Codex Sol → Gemini Flash** when a CLI is missing, signed out, timed out, quota-limited, or unable to use its model. Each provider authenticates through its own CLI; gitbot does not copy credentials between platforms.

## Features

- **Existing account logins** — Claude via `claude -p`, Codex Sol via `codex exec`, and Gemini Flash via Antigravity's `agy --print`. API-key environment overrides are removed for these requests.
- **Ordered fallback** — Claude remains the primary provider. Codex uses `gpt-6.1-sol`; Gemini uses `gemini-3.8-flash-medium`. Each fallback has its own model setting.
- **2-slot pipeline** — the bot holds one review-ready changeset in the git index (slot 1) while queued done-tasks wait (slot 2+); committing one automatically stages and describes the next.
- **Sonnet by default, switchable per size** — `sonnet` generates every message out of the box; set `model_small: "haiku"` to burn less quota on small diffs (thresholds configurable).
- **You always review** — generated messages land in your `git commit` editor via a hook; nothing is ever committed for you.
- **…unless you want hands-off (the default)** — auto-commit mode is on out of the box: Claude reports a finished task, gitbot stages it, writes the message, and commits it. `gitbot auto off` switches a repo back to review mode.
- **Manual mode too** — stage anything yourself and run `gitbot msg`.
- **Provider-pluggable** — one small Python class per AI backend; Claude, Codex, and Gemini adapters are included.
- **Survives restarts** — a launchd daemon (auto-started at login) recovers state even when commits happen from GUI clients that skip hooks.
- **macOS notifications** show the provider/model that generated each staged or committed message. For example: `auto-committed · codex-cli / gpt-6.1-sol: fix: handle expired login`.

---

## How it works

```
             ┌──────────────────────────────────────────────────────────┐
             │                   Claude Code (or any agent)             │
             │  1. gitbot plan set --json '[{...task list...}]'         │
             │  2. ...does task 1...   gitbot task done 1 --files ...   │
             │  3. ...does task 2...   gitbot task done 2 --files ...   │
             └───────────────┬──────────────────────────────────────────┘
                             ▼
   ┌──────────────────── gitbot ────────────────────────────────────────┐
   │                                                                    │
   │  SLOT 1 (the git index)          QUEUE (slot 2, 3, …)              │
   │  ┌───────────────────────┐       ┌─────────┐ ┌─────────┐           │
   │  │ task 1 files staged   │ ◄──── │ task 2  │ │ task 3  │  ...      │
   │  │ + commit msg ready    │       └─────────┘ └─────────┘           │
   │  └───────────┬───────────┘        (done, waiting for the index)    │
   │              │  Claude → Codex Sol → Gemini Flash                  │
   │              │  (existing CLI logins; models configurable)         │
   └──────────────┼─────────────────────────────────────────────────────┘
                  ▼
   ┌───────────────────────────── you ─────────────────────────────────┐
   │  🔔 notification → review staged diff → plain `git commit`        │
   │  (prepare-commit-msg hook pre-fills the message in your editor)   │
   │  post-commit hook → gitbot promotes the next queued task ↩        │
   └────────────────────────────────────────────────────────────────────┘
```

The git index can only hold one coherent changeset at a time — that *is* slot 1. Everything else waits in the queue. Each commit you make automatically pulls the next finished task into the index, generates its message, and notifies you.

---

## Requirements

| Requirement | Notes |
|---|---|
| macOS | notifications + launchd autostart are macOS-specific; core CLI works anywhere |
| Python ≥ 3.10 | stdlib only, no third-party packages |
| git | any modern version |
| [Claude Code](https://code.claude.com/docs/en/cli-reference) CLI | primary: installed and signed in to your subscription (`claude auth login`) |
| [Codex CLI](https://learn.chatgpt.com/docs/cli/reference) | optional first fallback: signed in with ChatGPT (`codex login`) |
| [Antigravity CLI](https://www.antigravity.google/docs/cli/install/) | optional second fallback: run `agy` interactively once to sign in to your Google account |

At least one provider must have a working login and model access. Gitbot discovers `~/.local/bin`, Homebrew, Codex's macOS VS Code extension binary, and `~/.gemini/bin/agy` when the daemon's PATH does not include them. Signing in to an IDE alone may still require signing in to its CLI; gitbot uses whatever account the CLI has authenticated.

---

## Installation

```sh
git clone <this repo> && cd git_commit_gen_ai_bot

# install into a private venv and expose the `gitbot` command
python3 -m venv .venv
.venv/bin/pip install -e .
ln -sf "$PWD/.venv/bin/gitbot" ~/.local/bin/gitbot   # ~/.local/bin must be on PATH

gitbot --version
```

Then, **per repository** you want gitbot in:

```sh
cd ~/code/my-project
gitbot init --claude-md     # installs hooks, creates .gitbot/, teaches Claude the protocol
```

And **once**, to start the recovery daemon on every mac boot:

```sh
gitbot service install
```

`gitbot init` never pollutes your repo history: runtime state lives in `.gitbot/` which is auto-added to `.git/info/exclude`.

---

## Usage

### Manual mode — you stage, gitbot writes the message

```sh
git add src/login.py tests/test_login.py
gitbot msg                    # generates + prints the message
git commit                    # editor opens pre-filled — review, tweak, save
```

`gitbot msg --model sonnet` forces the primary provider's model for one run. Fallback providers keep their own model settings.

In a hurry (or you trust the message)? Skip the editor entirely:

```sh
git add <files you want>      # you decide what goes in
gitbot commit                 # generate + commit the staged changes; uses the slot 1 message if ready
gitbot commit -a              # nothing staged? step through the plan task by task (see below)
```

**Task-scoped stepping.** When nothing is staged, `gitbot commit` looks at the plan and stages **only the next task's files** (queue first, then plan order — never `git add -A` while task files match). After every commit it pre-stages the *following* task's files with a fresh message, so you can walk a whole plan one clean commit at a time:

```sh
gitbot commit -a   # stages ONLY task 1's files → commits → pre-stages task 2
gitbot commit      # commits task 2 → pre-stages task 3
gitbot commit      # ...and so on, one task-scoped commit per trigger
```

**No plan? gitbot groups for you.** When no task info matches the dirty files, gitbot asks the model to split them into logical commit groups (related files together, unrelated work separated). The first group is staged with its message ready; the remaining groups join the queue as ad-hoc tasks — so repeated `gitbot commit` still walks your changes one clean commit at a time, never `git add -A` blobs. Grouping runs at the start of `gitbot commit -a`, and after **every** `gitbot commit` for whatever is left.

### Pipeline mode — working with Claude Code

Start your Claude session with a prompt like:

> Implement X, Y and Z. Break it into tasks and **share your task plan with gitbot** (`gitbot plan set`). After finishing each task run `gitbot task done <id> --files <changed files>` and continue to the next task. Never commit yourself.

(If you ran `gitbot init --claude-md`, this protocol is already in the repo's `CLAUDE.md` and Claude follows it without being reminded.)

What happens next:

1. Claude registers the plan: `gitbot plan set --json '[{"id":1,"title":"..."},...]'`
2. Claude finishes task 1 → `gitbot task done 1 --files a.py b.py` → gitbot stages those files, generates a message, 🔔 notifies you. Claude has already moved on to task 2.
3. You review at your own pace: `gitbot status`, `git diff --cached`, then plain `git commit`.
4. The moment you commit, gitbot promotes task 2 from the queue: stages it, generates its message, notifies you again. Claude is meanwhile on task 3.
5. Repeat until the plan is done — every commit reviewed by you, every message written for you.

**Auto mode (the default):** every `gitbot task done` immediately becomes its own commit — staged, message generated, committed, 🔔 notified — and the queue drains itself. The review loop above (steps 3–4) only applies when you switch a repo to review mode with `gitbot auto off` (`gitbot auto` shows the current setting; the global default lives in `~/.gitbot/config.json` as `"auto_commit"`).

### CLI reference

| Command | What it does |
|---|---|
| `gitbot init [--claude-md]` | Set up the current repo: hooks, `.gitbot/` state, git-exclude, registry. `--claude-md` appends the agent protocol to `CLAUDE.md`. |
| `gitbot plan set --json '<list>' \| --file plan.json` | Replace the task plan. Tasks: `{"id": 1, "title": "...", "description": "...", "files": [...]}` (only `title` required). |
| `gitbot plan add "title" [--desc D] [--files ...]` | Append a single task. |
| `gitbot plan show` | Alias of `gitbot status`. |
| `gitbot plan clear` | Empty the plan and queue (slot untouched). |
| `gitbot task done <id> [--files f1 f2 ...]` | Mark a task finished. Slot free → stage + generate message; slot busy → queue. Without `--files`, all dirty files are snapshotted. Unknown ids create ad-hoc tasks. |
| `gitbot msg [--model m]` | Generate a message for whatever is currently staged (manual mode). |
| `gitbot commit [-a] [--model m] [--regenerate]` | Generate the message **and commit** in one step (no editor). Commits what's staged; with nothing staged (`-a`) it stages **only the next task's files** — or, without a plan, AI-groups the dirty files into logical commits. After each commit the next task/group is pre-staged automatically, so repeated triggers walk all changes one clean commit at a time. |
| `gitbot auto [on\|off\|status]` | Per-repo auto-commit toggle (default **on**): finished tasks are committed by gitbot immediately; `off` holds them staged for your review instead. |
| `gitbot status` | Auto-commit setting, plan, slot 1 (with full message), queue, staged files. |
| `gitbot service install/uninstall/start/stop/status` | Manage the launchd daemon. `install` = one-time setup for start-on-boot. |
| `gitbot daemon` | Run the watcher in the foreground (what launchd runs). |
| `gitbot --repo <path> <cmd>` | Operate on a repo other than the current directory. |

---

## Configuration

Global config: `~/.gitbot/config.json` (created on first use; edit freely).

| Key | Default | Meaning |
|---|---|---|
| `provider` | `"claude-cli"` | Primary AI backend; remains Claude by default. |
| `fallback_providers` | `["codex-cli", "gemini-cli"]` | Providers tried in order after primary failure. Use `[]` to disable fallback. Duplicate providers are skipped. |
| `codex_model` | `"gpt-6.1-sol"` | Sol model passed to the signed-in Codex CLI. |
| `gemini_model` | `"gemini-3.8-flash-medium"` | Flash model passed to Antigravity CLI (`agy`). See `agy models` for your account's available models. |
| `model_small` | `"sonnet"` | Model for small changes (set to `"haiku"` to save subscription quota). |
| `model_large` | `"sonnet"` | Model for large changes. |
| `small_max_lines` | `150` | A staged diff with more changed lines than this uses `model_large`. |
| `small_max_files` | `5` | …or more files than this. |
| `diff_max_chars` | `15000` | Diffs longer than this are truncated (a `--stat` summary is appended) before prompting. |
| `notifications` | `true` | macOS notification when a slot becomes ready. |
| `auto_commit` | `true` | Global default for auto-commit mode (per-repo `gitbot auto on/off` overrides it). |
| `daemon_poll_seconds` | `15` | Daemon poll interval. |
| `repos` | `[]` | Repos registered by `gitbot init` (watched by the daemon). |

Existing configuration files inherit the new fallback defaults without changing their Claude provider or model settings. `model_small` and `model_large` control Claude's size-based selection; Codex and Gemini use their dedicated model keys. Grouping uncommitted changes uses the same provider order.

Per-repo state: `.gitbot/` inside each repo — `state.json` (plan/slot/queue and each task's successful provider/model), `COMMIT_MSG` (message the hook injects), `hook.log`, `lock`. Never committed (auto-excluded).

---

## Git hooks

`gitbot init` installs two hooks (existing hooks are preserved as `<name>.pre-gitbot` and still run first):

| Hook | Fires | Does |
|---|---|---|
| `prepare-commit-msg` | on plain `git commit` | Pre-fills your editor with `.gitbot/COMMIT_MSG`. Skipped for `-m`, `-t`, merge, squash, and amend commits. |
| `post-commit` | after every commit | Backgrounds `gitbot _on-commit`: marks the slot task committed, promotes the next queued task (stage → generate → notify). Never blocks or fails your commit. |

- Bypass everything: `git commit --no-verify` (the daemon will still reconcile state within ~15 s).
- The generated message is a *starting point* — whatever you save in the editor is what gets committed.

---

## Adding another AI provider

Providers are tiny. Implement one class:

```python
# gitbot/providers/custom_cli.py
import subprocess
from .base import Provider, ProviderError

class CustomCLIProvider(Provider):
    name = "custom-cli"

    def generate_commit_message(self, prompt: str, model: str) -> str:
        result = subprocess.run(
            ["custom-model-cli", "--model", model],
            input=prompt, capture_output=True, text=True, timeout=240,
        )
        if result.returncode != 0:
            raise ProviderError(result.stderr.strip()[:500])
        return result.stdout.strip()
```

Register it in `gitbot/providers/__init__.py`:

```python
from .custom_cli import CustomCLIProvider
_REGISTRY[CustomCLIProvider.name] = CustomCLIProvider
```

Select `"provider": "custom-cli"` in `~/.gitbot/config.json` and set `model_small` / `model_large` to its model names, or add it to `fallback_providers`. Add dedicated model selection in `message.provider_candidates` if the provider needs different model names. Prompting, validation, retries, slots, and hooks stay shared.

---

## Autostart on mac restart (launchd)

`gitbot service install` writes `~/Library/LaunchAgents/com.muj.gitbot.plist` (`RunAtLoad` + `KeepAlive`) and bootstraps it — the daemon starts at every login/restart and is relaunched if it dies.

The daemon is a safety net, not a requirement: it reconciles pipeline state when a commit happened without the hooks completing (GUI git clients, `--no-verify`, gitbot missing from a hook's PATH). Logs: `~/.gitbot/daemon.log`.

```sh
gitbot service status     # loaded (state = running)
gitbot service stop       # stop until next boot
gitbot service uninstall  # remove entirely
```

---

## Troubleshooting & FAQ

**A file was edited in task 1 (staged) and edited again in task 2 — what happens?**
The git index keeps task 1's version until you commit, so task 1's commit contains exactly what task 1 wrote. When task 2 is promoted, re-staging picks up the file's current (task 2) content. This is normal git staging behavior and exactly what the pipeline expects.

**The commit editor wasn't pre-filled.**
The hook only fills *plain* `git commit` — `-m`, merges, squashes, and amends are deliberately left alone. Also check the hook exists: `.git/hooks/prepare-commit-msg` (rerun `gitbot init` if missing), and that `.gitbot/COMMIT_MSG` was written (`gitbot status`).

**A provider fails / times out.**
Gitbot tries the next provider with its own model. Check the relevant login with `claude auth status`, `codex login status`, or an interactive `agy` session. Generation runs in a temporary directory so repository agent instructions cannot recursively trigger commits; Claude also runs with tools and custom hooks disabled. If every provider fails, gitbot reports the errors and leaves the task/files staged for retry without committing a synthetic message. Run `gitbot task done <id> --files <task files>` again after fixing the login or quota issue.

**Nothing was promoted after my commit.**
Promotion is asynchronous (a few seconds — it calls Claude). Check `.gitbot/hook.log`. If you committed from a GUI client that skips hooks, the daemon reconciles within `daemon_poll_seconds`.

**No notifications appear.**
Gitbot passes notification text directly to AppleScript as arguments, preserving Unicode model labels and commit subjects. Delivery errors print a warning in the terminal (or `.gitbot/hook.log` / `~/.gitbot/daemon.log` for background calls). macOS may ask you to allow notifications from "Script Editor"/"osascript" the first time — approve it in System Settings → Notifications. A successful send request can still be hidden by notification settings or Focus. Set `"notifications": false` to disable notifications.

**Claude committed by itself!**
Make sure the protocol is in `CLAUDE.md` (`gitbot init --claude-md`) — rule 3 is *NEVER run `git add`/`git commit`*. You can also deny git-commit permissions in Claude Code's settings.

**Does this cost money per commit?**
No API charges — `claude -p` uses your Claude subscription. It does consume a small amount of your plan's usage; set `"model_small": "haiku"` if you want small diffs to cost less quota.

**Can I use it without an AI agent?**
Yes — that's manual mode: `git add ...` then `gitbot msg`.

---

## The CLAUDE.md protocol snippet

`gitbot init --claude-md` appends this to your repo's `CLAUDE.md` (copy-paste it anywhere you like):

```markdown
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
```

---

## Project layout

```
gitbot/
├── cli.py           # argparse entrypoint (`gitbot ...`)
├── config.py        # ~/.gitbot/config.json
├── state.py         # per-repo .gitbot/state.json (plan / slot / queue)
├── git_ops.py       # git subprocess wrappers
├── pipeline.py      # 2-slot state machine (task done / on-commit promotion)
├── message.py       # prompt build, model auto-switch, validation, fallbacks
├── hooks.py         # prepare-commit-msg + post-commit templates & installer
├── notify.py        # macOS notifications
├── daemon.py        # launchd watcher (missed-commit recovery)
├── service.py       # launchd plist install/start/stop
└── providers/       # AI backends (claude-cli today; add your own)
```

MIT licensed.
