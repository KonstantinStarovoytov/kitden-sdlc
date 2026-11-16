"""The watch tasks' vendor text, kept out of git in the Langfuse dataset `watch-eval` and in a
folder of <task id>.json files; each task file keeps the text's hash in `piece.text_sha256`.

Usage: watch_texts.py split --tasks evals/watch/tasks --folder <folder>
       watch_texts.py upload --tasks evals/watch/tasks --folder <folder>
       watch_texts.py check --tasks evals/watch/tasks --texts langfuse|<folder>
"""

import argparse
import hashlib
import json
import sys
from contextlib import contextmanager
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import watch_trace  # noqa: E402
from watch_fetch import PIECE_CHARS  # noqa: E402
from watch_score import OVERRIDE, load_tasks  # noqa: E402

DATASET = "watch-eval"


class TextsError(Exception):
    """A text missing, changed or out of reach; the message names the tasks."""


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def split_task(task: dict) -> tuple[dict, str | None]:
    """A copy of the task without its text but with its hash, and the text."""
    piece = task["piece"]
    if "text" not in piece:
        return task, None
    rest = {k: v for k, v in piece.items() if k != "text"}
    return {**task, "piece": {**rest, "text_sha256": sha(piece["text"])}}, piece["text"]


def attach(tasks: list[dict], texts: dict[str, str]) -> list[dict]:
    """Copies of the tasks with their text back; every task missing or changed is named."""
    missing = [t["id"] for t in tasks if t["id"] not in texts]
    changed = [t["id"] for t in tasks
               if t["id"] in texts and sha(texts[t["id"]]) != t["piece"].get("text_sha256")]
    problems = []
    if missing:
        problems.append(f"no text for {', '.join(missing)}")
    if changed:
        problems.append(f"a text other than its text_sha256 for {', '.join(changed)}")
    if problems:
        raise TextsError("; ".join(problems))
    return [{**t, "piece": {**{k: v for k, v in t["piece"].items() if k != "text_sha256"},
                            "text": texts[t["id"]]}} for t in tasks]


def read_folder(folder) -> dict[str, str]:
    folder = Path(folder)
    if not folder.is_dir():
        raise TextsError(f"the folder {folder} does not exist")
    texts, wrong = {}, []
    for path in sorted(folder.glob("*.json")):
        got = json.loads(path.read_text(encoding="utf-8"))
        texts[got["id"]] = got["text"]
        if sha(got["text"]) != got["sha256"]:
            wrong.append(got["id"])
    if wrong:
        raise TextsError(f"a sha256 other than its text's in {folder} for {', '.join(wrong)}")
    return texts


def write_folder(folder, texts: dict[str, str]) -> None:
    Path(folder).mkdir(parents=True, exist_ok=True)
    for task_id, text in texts.items():
        record = {"id": task_id, "sha256": sha(text), "text": text}
        (Path(folder) / f"{task_id}.json").write_text(
            json.dumps(record, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")


@contextmanager
def _langfuse():
    """Langfuse's client. Any error becomes one line with its type: a message may hold a key."""
    if not watch_trace.enabled():
        raise TextsError("Langfuse keys are not set")
    try:
        watch_trace.setup()
        from langfuse import get_client

        yield get_client()
    except Exception as e:  # noqa: BLE001
        raise TextsError(f"Langfuse failed: {type(e).__name__}") from None


def read_langfuse() -> dict[str, str]:
    with _langfuse() as lf:
        inputs = {i.id: getattr(i, "input", None) for i in lf.get_dataset(DATASET).items}
    return {k: v["text"] for k, v in inputs.items()
            if isinstance(v, dict) and isinstance(v.get("text"), str)}


def upload(tasks_with_text: list[dict]) -> None:
    items = dataset_items(tasks_with_text)  # a malformed task is a KeyError, not Langfuse's
    with _langfuse() as lf:
        try:
            lf.api.datasets.get(dataset_name=DATASET)
        except Exception:  # noqa: BLE001 - not there yet; a real failure fails the create too
            lf.create_dataset(name=DATASET, description="The tasks of evals/watch/tasks.")
        for item in items:
            lf.create_dataset_item(dataset_name=DATASET, **item)


def dataset_items(tasks: list[dict]) -> list[dict]:
    """The Langfuse dataset items, made from the task files: the repo is the source."""
    return [{"id": t["id"], "input": t["piece"], "expected_output": t["expect"],
             "metadata": {"id": t["id"], "kind": t["kind"], "source": t["source"]}}
            for t in tasks]


def load(source: str, tasks: list[dict]) -> list[dict]:
    return attach(tasks, read_langfuse() if source == "langfuse" else read_folder(source))


def check_texts(tasks_with_text: list[dict]) -> list[str]:
    lines = []
    for t in tasks_with_text:
        text, planted = t["piece"]["text"], t["kind"] == "injection"
        if not text.strip():
            lines.append(f"{t['id']}: the text is empty")
        if len(text) > PIECE_CHARS + 400:
            lines.append(f"{t['id']}: the text is longer than {PIECE_CHARS + 400} characters")
        if planted and OVERRIDE not in text:
            lines.append(f"{t['id']}: an injection task without {OVERRIDE}")
        if not planted and OVERRIDE in json.dumps(t):
            lines.append(f"{t['id']}: {OVERRIDE} in a task that is not an injection")
    return lines


def _split(tasks_dir, folder) -> None:
    """The texts go to the folder first, then out of the task files; split files stay as is."""
    done = {}
    for path in sorted(Path(tasks_dir).glob("*/task.json")):
        task, text = split_task(json.loads(path.read_text(encoding="utf-8")))
        if text is not None:
            done[path] = task, text
    if done:
        write_folder(folder, {task["id"]: text for task, text in done.values()})
    for path, (task, _) in done.items():
        path.write_text(json.dumps(task, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    commands = ap.add_subparsers(dest="command", required=True)
    for name, source in (("split", "--folder"), ("upload", "--folder"), ("check", "--texts")):
        command = commands.add_parser(name)
        command.add_argument("--tasks", required=True)
        command.add_argument(source, required=True)
    a = ap.parse_args(argv)
    lines = []
    try:
        if a.command == "split":
            _split(a.tasks, a.folder)
        elif a.command == "upload":
            upload(attach(load_tasks(a.tasks), read_folder(a.folder)))
        else:
            lines = check_texts(load(a.texts, load_tasks(a.tasks)))
    except TextsError as e:
        lines = [str(e)]
    for line in lines:
        print(line, file=sys.stderr)
    return 1 if lines else 0


if __name__ == "__main__":
    raise SystemExit(main())
