
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
