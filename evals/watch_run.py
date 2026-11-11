"""Run the watcher's judge on the watch tasks and save what it finds.

Usage: watch_run.py --kitden <clone> --tasks evals/watch/tasks --out <folder>

For each task: an input.json built the way watch_fetch.py builds it (the clone's
docs/clients.md and the files it names, the task's piece), the judge run on it, and
<folder>/<id>/findings.json saved. MAX_MODEL_CALLS is the limit for each task, as for one run
of the judge. It needs OPENAI_API_KEY and WATCH_MODEL.
"""

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from watch_fetch import _git, build_input  # noqa: E402
from watch_judge import MAX_MODEL_CALLS, OpenAIModel, judge  # noqa: E402
from watch_list import parse_list  # noqa: E402


def build_task_input(piece: dict, kitden) -> dict:
    list_text = (Path(kitden) / "docs/clients.md").read_text(encoding="utf-8")
    names = sorted({f for r in parse_list(list_text) for f in r.files})
    release = _git(kitden, "describe", "--tags", "--abbrev=0").stdout.strip()

    def same(name):
        return _git(kitden, "diff", "--quiet", release, "HEAD", "--", name).returncode == 0

    return build_input([piece], kitden, list_text, names, same, release, [], {})


def run_tasks(tasks_dir, kitden, out, model, max_calls: int) -> None:
    for path in sorted(Path(tasks_dir).glob("*/task.json")):
        task = json.loads(path.read_text(encoding="utf-8"))
        found = judge(build_task_input(task["piece"], kitden), model, max_calls)
        folder = Path(out) / task["id"]
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "findings.json").write_text(json.dumps(found, indent=1), encoding="utf-8")
        print(f"{task['id']}: {len(found['findings'])} findings")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    for name in ("kitden", "tasks", "out"):
        ap.add_argument(f"--{name}", required=True)
    a = ap.parse_args()
    name = os.environ.get("WATCH_MODEL")
    if not name:
        print("WATCH_MODEL is not set", file=sys.stderr)
        raise SystemExit(1)
    max_calls = int(os.environ.get("MAX_MODEL_CALLS") or MAX_MODEL_CALLS)
    run_tasks(a.tasks, a.kitden, a.out, OpenAIModel(name), max_calls)


if __name__ == "__main__":
    main()
