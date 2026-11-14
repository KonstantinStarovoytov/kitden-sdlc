# Working in this repository

Before each commit, run:

- `uv run pytest -q`
- `uv run ruff check .`
- `uv run python scripts/check_agent_workflows.py .github/workflows`

Other rules:

- Whoever edits a workflow also runs the `agentic-actions-auditor` skill locally.
- Pin every action by its full SHA, with the tag in a comment.
- Keep RULES.md and the README in step with the workflows.
- A change to a prompt, a skill or a model comes with its eval table, before and after, in the
  same pull request.

Several sessions at once:

- Each session works on its own branch in its own worktree
  (`git worktree add .claude/worktrees/<name> -b <branch> origin/main`), never in the main
  checkout and never on another session's branch.
- Do not edit, commit, stash or discard changes you did not make. If you find them, ask the
  owner whose they are.
- To set your own work aside, make a WIP commit on your branch. The stash is shared by every
  worktree, so never use a bare `git stash` or `git stash pop`.
