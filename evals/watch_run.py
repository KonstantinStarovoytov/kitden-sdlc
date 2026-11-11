"""Run the watcher's judge on the watch tasks and save what it finds.

Usage: watch_run.py --kitden <clone> --tasks evals/watch/tasks --out <folder>

For each task: an input.json built the way watch_fetch.py builds it (the clone's
docs/clients.md and the files it names, the task's piece), the judge run on it, and
<folder>/<id>/findings.json saved. MAX_MODEL_CALLS is the limit for each task, as for one run
of the judge. It needs OPENAI_API_KEY and WATCH_MODEL. With the Langfuse keys set, the run is
also an experiment on the Langfuse dataset `watch-eval`, with the scores of each task.
"""

import argparse
import json
import os
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import watch_trace  # noqa: E402
from watch_fetch import _git, build_input  # noqa: E402
from watch_judge import MAX_MODEL_CALLS, OpenAIModel, judge  # noqa: E402
from watch_list import parse_list  # noqa: E402
from watch_score import load_tasks, task_scores  # noqa: E402

DATASET = "watch-eval"


def build_task_input(piece: dict, kitden) -> dict:
    list_text = (Path(kitden) / "docs/clients.md").read_text(encoding="utf-8")
    names = sorted({f for r in parse_list(list_text) for f in r.files})
    release = _git(kitden, "describe", "--tags", "--abbrev=0").stdout.strip()

    def same(name):
        return _git(kitden, "diff", "--quiet", release, "HEAD", "--", name).returncode == 0

    return build_input([piece], kitden, list_text, names, same, release, [], {})


def run_task(task: dict, kitden, out, model, max_calls: int) -> dict:
    start = time.monotonic()
    found = judge(build_task_input(task["piece"], kitden), model, max_calls)
    folder = Path(out) / task["id"]
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "findings.json").write_text(json.dumps(found, indent=1), encoding="utf-8")
    # Flushed, so the run's log shows each task as it ends.
    state = "judged" if found["judged"] else "not judged"
    seconds = round(time.monotonic() - start)
    print(f"{task['id']}: {state}, {len(found['findings'])} findings, {seconds} s", flush=True)
    return found


def dataset_items(tasks: list[dict]) -> list[dict]:
    """The Langfuse dataset items, made from the task files: the repo is the source."""
    return [{"id": t["id"], "input": t["piece"], "expected_output": t["expect"],
             "metadata": {"id": t["id"], "kind": t["kind"], "source": t["source"]}}
            for t in tasks]


def run_name(model_name: str, now: datetime) -> str:
    return f"{model_name} {watch_trace.commit()[:7] or 'local'} {now:%Y-%m-%dT%H:%MZ}"


def experiment(tasks: list[dict], run_one, model_name: str) -> None:
    """Run the tasks as one experiment on the dataset; each trace gets its task's scores."""
    watch_trace.setup()
    from langfuse import Evaluation, get_client

    lf = get_client()
    try:
        lf.api.datasets.get(dataset_name=DATASET)
    except Exception:  # noqa: BLE001 - not there yet; a real failure fails the create too
        lf.create_dataset(name=DATASET, description="The tasks of evals/watch/tasks.")
    for item in dataset_items(tasks):
        lf.create_dataset_item(dataset_name=DATASET, **item)
    by_id = {t["id"]: t for t in tasks}
    items = [i for i in lf.get_dataset(DATASET).items if i.id in by_id]

    def task(*, item, **kwargs):
        return run_one(by_id[item.id])

    def scores(*, output, metadata, **kwargs):
        return [Evaluation(name=k, value=v, data_type="BOOLEAN")
                for k, v in task_scores(by_id[metadata["id"]], output).items()]

    lf.run_experiment(name=DATASET, run_name=run_name(model_name, datetime.now(UTC)),
                      data=items, task=task, evaluators=[scores], max_concurrency=1,
                      metadata={"model": model_name, "commit": watch_trace.commit()})


def run_tasks(tasks_dir, kitden, out, model, max_calls: int, model_name: str = "") -> None:
    tasks = load_tasks(tasks_dir)
    done = {}

    def one(task: dict) -> dict:
        done[task["id"]] = run_task(task, kitden, out, model, max_calls)
        return done[task["id"]]

    if watch_trace.enabled():
        try:
            experiment(tasks, one, model_name)
        except Exception as e:  # noqa: BLE001 - Langfuse must never stop the eval
            watch_trace.warn(e)
    # Without Langfuse, or for what its experiment did not finish.
    for task in tasks:
        if task["id"] not in done:
            one(task)


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
    try:
        run_tasks(a.tasks, a.kitden, a.out, OpenAIModel(name), max_calls, name)
    finally:
        watch_trace.flush()


if __name__ == "__main__":
    main()
