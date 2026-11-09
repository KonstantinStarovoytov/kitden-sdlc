# Working in this repository

Before each commit, run:

- `uv run pytest -q`
- `uv run ruff check .`
- `uv run python scripts/check_agent_workflows.py .github/workflows`

Other rules:

- Whoever edits a workflow also runs the `agentic-actions-auditor` skill locally.
- Pin every action by its full SHA, with the tag in a comment.
- Keep RULES.md and the README in step with the workflows.
