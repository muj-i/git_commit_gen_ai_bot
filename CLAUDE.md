
## gitbot commit protocol

This repo uses gitbot: it owns all git staging and committing. When you report
a finished task, gitbot stages the files, generates a Conventional Commits
message, and commits automatically (auto mode, the default — with auto off it
holds the staged changes for the user's review instead). Follow this protocol
exactly:

1. When starting multi-task work, share your task plan with the bot:
   `gitbot plan set --json '[{"id": 1, "title": "...", "description": "..."}, ...]'`
2. After finishing each task, report it together with the files you changed:
   `gitbot task done <id> --files <file1> <file2> ...`
   gitbot handles staging, the commit message, and the commit itself.
3. NEVER run `git add`, `git commit`, or `git push` yourself — gitbot owns git.
4. Move on to the next task immediately after `gitbot task done`.
5. Run `gitbot status` if you need to see the plan / slot / queue state.
