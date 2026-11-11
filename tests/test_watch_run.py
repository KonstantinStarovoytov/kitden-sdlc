import json

from watch_run import run_tasks

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
                 "user_gets": "u", "sure": False, "why": "w"}]

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
