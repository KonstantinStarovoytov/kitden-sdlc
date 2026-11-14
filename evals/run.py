"""Run a reviewer on the review tasks, the way the review workflows run it.

Usage: run.py --reviewer {claude,luna} --model M --kitden ../kitden --tasks evals/tasks
              --out evals/results/<date>/<reviewer>-<model> [--only 001 002 ...]

For each task: a git worktree of Kitden at the task's base in a temporary folder, the diff
applied, `.review/` built as scripts/prepare_review.sh builds it, the reviewer run in that
folder, then <out>/<task-id>/findings.json, seconds and log.txt saved and the worktree removed.
"""

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PLUGIN = ROOT / "plugins/kitden-sdlc"
# The same tools as .github/workflows/review.yml (tests/test_run.py checks it).
ALLOWED = "Read(./**),Edit(./.review/**)"
DISALLOWED = (
    "Bash,WebFetch,WebSearch,NotebookEdit,Task,Read(**/.git/**),Read(**/.kitden-sdlc/**),"
    "Read(~/.*),Read(~/.*/**),Read(//proc/**)"
)
MAX_TURNS = 30
CODEX = ["npx", "-y", "@openai/codex@0.167.0"]
TIMEOUT = 15 * 60  # the review job's timeout-minutes
RULE_FILES = ("PRINCIPLES.md", "AGENTS.md")


def git(*args: str, cwd: Path | None = None, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(  # noqa: S603
        ["git", *args],  # noqa: S607
        cwd=cwd,
        capture_output=True,
        text=True,
        check=check,
    )


def build_review(kitden: Path, folder: Path, task: dict, patch: Path) -> None:
    """Apply the diff in `folder` and write .review/ as prepare_review.sh does."""
    git("apply", str(patch), cwd=folder)
    review = folder / ".review"
    shutil.rmtree(review, ignore_errors=True)
    review.mkdir()
    shutil.copyfile(patch, review / "diff.patch")
    numstat = git("apply", "--numstat", str(patch), cwd=folder).stdout
    names = [line.split("\t", 2)[2] for line in numstat.splitlines() if line]
    (review / "files.txt").write_text("".join(f"{name}\n" for name in names))
    (review / "pr.md").write_text(f"# {task['title']}\n\n{task.get('body', '')}")
    # The working rules come from the base commit, not from the change.
    for name in RULE_FILES:
        shown = git("-C", str(kitden), "show", f"{task['base']}:{name}", check=False)
        (review / name).write_text(shown.stdout if shown.returncode == 0 else "")


def claude_command(model: str) -> list[str]:
    return [
        "claude", "-p", "/kitden-sdlc:review-kitden",
        "--plugin-dir", str(PLUGIN),
        "--model", model,
        "--effort", "high",
        "--max-turns", str(MAX_TURNS),
        "--allowedTools", ALLOWED,
        "--disallowedTools", DISALLOWED,
        # CI runs in a clean home: leave out this computer's user settings and MCP servers.
        "--setting-sources", "project,local",
        "--strict-mcp-config",
    ]  # fmt: skip


def luna_command(model: str, answer: Path) -> list[str]:
    """As review.yml runs codex-action. Flags written from the workflow, not checked
    against `codex exec --help`; check them before the first run."""
    prompt = (ROOT / "prompts/review-luna.md").read_text()
    return [
        *CODEX, "exec",
        "--model", model,
        "--sandbox", "read-only",
        "-c", "project_doc_max_bytes=0",
        "-c", 'web_search="disabled"',
        "--output-schema", str(ROOT / "schemas/findings.openai.schema.json"),
        "--output-last-message", str(answer),
        prompt,
    ]  # fmt: skip


def remove_agent_files(folder: Path) -> None:
    """Codex reads these as its own instructions; the workflow deletes them first."""
    for name in ("AGENTS.md", "AGENTS.override.md", ".agents", ".codex"):
        path = folder / name
        if path.is_dir() and not path.is_symlink():
            shutil.rmtree(path)
        elif path.exists() or path.is_symlink():
            path.unlink()
    keep = {folder / ".git", folder / ".review"}
    for path in folder.rglob("AGENTS*.md"):
        if path.name in ("AGENTS.md", "AGENTS.override.md") and not any(
            k in path.parents for k in keep
        ):
            path.unlink()


def run_task(args: argparse.Namespace, task_dir: Path) -> None:
    task = json.loads((task_dir / "task.json").read_text())
    out = args.out / task["id"]
    out.mkdir(parents=True, exist_ok=True)
    for old in ("findings.json", "seconds", "log.txt"):
        (out / old).unlink(missing_ok=True)
    temp = Path(tempfile.mkdtemp(prefix="kitden-eval-"))
    folder = temp / "kitden"
    try:
        git("-C", str(args.kitden), "worktree", "add", "--detach", str(folder), task["base"])
        build_review(args.kitden, folder, task, (task_dir / "diff.patch").resolve())
        answer = folder / ".review/findings.json"
        if args.reviewer == "luna":
            remove_agent_files(folder)
            command = luna_command(args.model, temp / "answer.json")
            answer = temp / "answer.json"
        else:
            command = claude_command(args.model)
        started = time.monotonic()
        try:
            done = subprocess.run(  # noqa: S603
                command, cwd=folder, capture_output=True, text=True, timeout=TIMEOUT
            )
            log = f"exit {done.returncode}\n{done.stdout}\n{done.stderr}"
        except subprocess.TimeoutExpired:
            log = f"stopped after {TIMEOUT} seconds"
        seconds = time.monotonic() - started
        (out / "seconds").write_text(f"{seconds:.1f}\n")
        (out / "log.txt").write_text(log)
        if answer.is_file():
            shutil.copyfile(answer, out / "findings.json")
        print(f"{task['id']}: {seconds:.0f} s, findings {'saved' if answer.is_file() else 'none'}")
    finally:
        git("-C", str(args.kitden), "worktree", "remove", "--force", str(folder), check=False)
        git("-C", str(args.kitden), "worktree", "prune", check=False)
        shutil.rmtree(temp, ignore_errors=True)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--reviewer", choices=("claude", "luna"), required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--kitden", type=Path, required=True)
    parser.add_argument("--tasks", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--only", nargs="+", default=[], help="task ids or their numbers")
    args = parser.parse_args(argv)
    args.kitden = args.kitden.resolve()
    args.out = args.out.resolve()

    task_dirs = sorted(p.parent for p in args.tasks.glob("*/task.json"))
    if args.only:
        task_dirs = [d for d in task_dirs if any(d.name.startswith(o) for o in args.only)]
    if not task_dirs:
        print("No tasks to run.", file=sys.stderr)
        return 1
    for task_dir in task_dirs:
        run_task(args, task_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
