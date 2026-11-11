import json
import logging
import sys
import types
from datetime import UTC, datetime

import pytest

import watch_run
import watch_trace
from watch_run import dataset_items, run_name, run_tasks
from watch_score import load_tasks

LIST_TEXT = (
    "## Claude Code\n\n| What | Kind | Files | Seen in | macOS and Linux | Source |\n"
    "|---|---|---|---|---|---|\n"
    "| the `skillOverrides` key | key | `src/skills.py` | skills | same | guess |\n"
)
PIECE = {"id": "s#1", "client": "claude-code", "kind": "release", "version": "1",
         "url": "https://example.com", "text": "text", "source": "s", "key": "1", "hash": "h"}


class Fake:
    def __init__(self):
        self.pieces = []

    def screen(self, piece, list_text, known_titles):
        self.pieces.append(piece["id"])
        return [{"row": "the `skillOverrides` key", "title": "t", "changed": "c",
                 "user_gets": "u", "sure": False, "why": "w", "quote": piece["text"]}]

    def assess(self, change, row, files):
        self.files = sorted(files)
        return {"effect": "minor", "sure": False, "user_gets": "u", "systems": "s",
                "why": "w", "title": "t"}

    def refute(self, finding, row, files):
        return False


def test_each_task_gets_its_own_input_and_a_findings_file(tmp_path):
    kitden, tasks, out = tmp_path / "kitden", tmp_path / "tasks", tmp_path / "out"
    (kitden / "docs").mkdir(parents=True)
    (kitden / "src").mkdir()
    (kitden / "docs/clients.md").write_text(LIST_TEXT)
    (kitden / "src/skills.py").write_text("x = 1\n")
    (tasks / "001-a").mkdir(parents=True)
    task = {"id": "001-a", "kind": "touched", "source": "s", "piece": PIECE,
            "expect": {"row": "the `skillOverrides` key", "effect": "minor"}}
    (tasks / "001-a/task.json").write_text(json.dumps(task))
    model = Fake()
    run_tasks(tasks, kitden, out, model, 10)
    found = json.loads((out / "001-a/findings.json").read_text())
    assert found["judged"] == ["s#1"]
    assert [f["row"] for f in found["findings"]] == ["the `skillOverrides` key"]
    assert model.files == ["src/skills.py"]


def setup(tmp_path, *tasks):
    kitden, folder, out = tmp_path / "kitden", tmp_path / "tasks", tmp_path / "out"
    (kitden / "docs").mkdir(parents=True)
    (kitden / "src").mkdir()
    (kitden / "docs/clients.md").write_text(LIST_TEXT)
    (kitden / "src/skills.py").write_text("x = 1\n")
    for t in tasks:
        (folder / t["id"]).mkdir(parents=True)
        (folder / t["id"] / "task.json").write_text(json.dumps(t))
    return kitden, folder, out


TOUCHED = {"id": "001-a", "kind": "touched", "source": "s", "piece": PIECE,
           "expect": {"row": "the `skillOverrides` key", "effect": "minor"}}
UNTOUCHED = {"id": "002-b", "kind": "untouched", "source": "s",
             "piece": {**PIECE, "id": "s#2"}, "expect": {"row": None, "effect": None}}


class FakeLangfuse:
    """Records what the eval sends; runs the experiment the way the SDK does, in order."""

    def __init__(self, fail=None):
        self.fail, self.items, self.scores, self.created = fail, {}, [], []
        self.api = types.SimpleNamespace(datasets=types.SimpleNamespace(get=self.get))

    def get(self, dataset_name):
        if self.fail:
            raise self.fail
        raise LookupError("no dataset yet")

    def create_dataset(self, name, description):
        if self.fail:
            raise self.fail
        self.created.append(name)

    def create_dataset_item(self, dataset_name, id, input, expected_output, metadata):
        self.items[id] = types.SimpleNamespace(id=id, input=input,
                                               expected_output=expected_output,
                                               metadata=metadata)

    def get_dataset(self, name):
        return types.SimpleNamespace(items=[*self.items.values(),
                                            types.SimpleNamespace(id="gone")])

    def run_experiment(self, *, name, run_name, data, task, evaluators, max_concurrency,
                       metadata):
        self.run = (name, run_name, metadata, [i.id for i in data])
        for i, item in enumerate(data):
            try:
                out = task(item=item)
            except Exception as e:  # the SDK logs a failed item and goes on
                logging.getLogger("langfuse").error("Item %s failed: %s", i, e)
                continue
            for ev in evaluators:
                for e in ev(input=item.input, output=out, expected_output=item.expected_output,
                            metadata=item.metadata):
                    self.scores.append((item.id, e.name, e.value, e.data_type))

    def flush(self):
        pass


def fake_langfuse(monkeypatch, client):
    for name in ("LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY"):
        monkeypatch.setenv(name, "test")
    monkeypatch.setenv("GITHUB_SHA", "abc1234def")
    lf = types.ModuleType("langfuse")
    lf.get_client = lambda: client
    lf.Evaluation = lambda **kw: types.SimpleNamespace(**kw)
    lc = types.ModuleType("langfuse.langchain")
    lc.CallbackHandler = object
    monkeypatch.setitem(sys.modules, "langfuse", lf)
    monkeypatch.setitem(sys.modules, "langfuse.langchain", lc)
    watch_trace._handler.cache_clear()


def test_dataset_items_come_from_the_task_files(tmp_path):
    _, folder, _ = setup(tmp_path, TOUCHED, UNTOUCHED)
    items = dataset_items(load_tasks(folder))
    assert items == [
        {"id": "001-a", "input": PIECE, "expected_output": TOUCHED["expect"],
         "metadata": {"id": "001-a", "kind": "touched", "source": "s"}},
        {"id": "002-b", "input": UNTOUCHED["piece"], "expected_output": UNTOUCHED["expect"],
         "metadata": {"id": "002-b", "kind": "untouched", "source": "s"}},
    ]


def test_the_run_name_has_the_model_the_short_commit_and_the_utc_time(monkeypatch):
    monkeypatch.setenv("GITHUB_SHA", "abc1234def")
    when = datetime(2026, 11, 11, 9, 5, tzinfo=UTC)
    assert run_name("gpt-6-luna", when) == "gpt-6-luna abc1234 2026-11-11T09:05Z"


def test_with_keys_the_run_is_an_experiment_with_scores(tmp_path, monkeypatch):
    kitden, folder, out = setup(tmp_path, TOUCHED, UNTOUCHED)
    client = FakeLangfuse()
    fake_langfuse(monkeypatch, client)
    run_tasks(folder, kitden, out, Fake(), 10, "gpt-test")
    assert client.created == ["watch-eval"] and sorted(client.items) == ["001-a", "002-b"]
    name, rname, meta, ids = client.run
    assert name == "watch-eval" and rname.startswith("gpt-test abc1234 ")
    assert meta == {"model": "gpt-test", "commit": "abc1234def"} and ids == ["001-a", "002-b"]
    assert client.scores == [
        ("001-a", "found", 1, "BOOLEAN"), ("001-a", "severity_right", 1, "BOOLEAN"),
        ("001-a", "judge_failed", 0, "BOOLEAN"),
        ("002-b", "false_alarm", 1, "BOOLEAN"), ("002-b", "judge_failed", 0, "BOOLEAN"),
    ]
    assert (out / "001-a/findings.json").exists() and (out / "002-b/findings.json").exists()


def test_a_langfuse_failure_does_not_fail_the_run(tmp_path, monkeypatch, capsys):
    kitden, folder, out = setup(tmp_path, TOUCHED, UNTOUCHED)
    fake_langfuse(monkeypatch, FakeLangfuse(fail=ConnectionError("sk-test")))
    model = Fake()
    run_tasks(folder, kitden, out, model, 10, "gpt-test")
    assert model.pieces == ["s#1", "s#2"]
    assert (out / "002-b/findings.json").exists()
    assert "langfuse failed: ConnectionError\n" in capsys.readouterr().err


def test_without_keys_nothing_of_langfuse_is_imported(tmp_path, monkeypatch, capsys):
    for name in ("LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setitem(sys.modules, "langfuse", None)
    kitden, folder, out = setup(tmp_path, TOUCHED)
    run_tasks(folder, kitden, out, Fake(), 10, "gpt-test")
    assert (out / "001-a/findings.json").exists()
    assert "langfuse" not in capsys.readouterr().err


def test_a_task_that_raises_runs_twice_at_most_and_still_fails_the_run(tmp_path, monkeypatch,
                                                                         capsys):
    kitden, folder, out = setup(tmp_path, TOUCHED, UNTOUCHED)
    fake_langfuse(monkeypatch, FakeLangfuse())
    real, tries = watch_run.build_task_input, []

    def build(piece, kitden):
        tries.append(piece["id"])
        if piece["id"] == "s#2":
            raise RuntimeError("clone text sk-test")
        return real(piece, kitden)

    monkeypatch.setattr(watch_run, "build_task_input", build)
    model = Fake()
    with pytest.raises(RuntimeError):
        run_tasks(folder, kitden, out, model, 10, "gpt-test")
    assert tries == ["s#1", "s#2", "s#2"] and model.pieces == ["s#1"]
    assert (out / "001-a/findings.json").exists()
    assert "sk-test" not in capsys.readouterr().err
