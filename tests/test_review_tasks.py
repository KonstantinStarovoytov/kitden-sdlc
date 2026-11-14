import re
from collections import Counter
from pathlib import Path

from score import load_tasks

TASKS_DIR = Path(__file__).resolve().parent.parent / "evals/tasks"
TASKS = load_tasks(TASKS_DIR)


def added_lines(patch: str, path: str) -> set[int]:
    """The line numbers, on the new side, of the lines the patch adds to `path`."""
    added, current, new = set(), None, 0
    for line in patch.splitlines():
        if line.startswith("diff --git "):
            current = None
        elif line.startswith("+++ "):
            current = line[6:] if line.startswith("+++ b/") else None
        elif line.startswith("@@"):
            new = int(re.match(r"@@ -\d+(?:,\d+)? \+(\d+)", line)[1])
        elif current == path and line[:1] in ("+", " "):
            if line[0] == "+":
                added.add(new)
            new += 1
    return added


def test_the_set_has_the_kinds_the_readme_names():
    assert Counter(t["kind"] for t in TASKS) == {"defect": 24, "clean": 13, "injection": 5}
    assert [t["id"] for t in TASKS] == sorted(p.name for p in TASKS_DIR.iterdir() if p.is_dir())


def test_a_defect_line_is_a_line_the_diff_adds():
    for task in TASKS:
        if task["kind"] != "defect":
            assert task["defect"] is None
            continue
        patch = (TASKS_DIR / task["id"] / "diff.patch").read_text()
        defect = task["defect"]
        assert defect["line"] in added_lines(patch, defect["path"]), task["id"]


def test_a_real_bug_names_its_commit_and_its_fix():
    for task in TASKS:
        if task["source"].startswith("commit:"):
            assert task["kind"] == "defect" and re.fullmatch(r"[0-9a-f]{40}", task["fix"])
