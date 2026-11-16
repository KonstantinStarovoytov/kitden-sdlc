import re
from collections import Counter
from pathlib import Path

from watch_route import EFFECTS, SEVERITIES
from watch_score import in_bar, load_tasks, score

DIR = Path(__file__).resolve().parent.parent / "evals/watch/tasks"
TASKS = load_tasks(DIR)
SOURCES = {"claude-code-changelog", "codex-releases", "cursor-changelog"}


def test_the_set_has_the_planned_mix():
    kinds = Counter(
        "in the bar" if in_bar(t)
        else "gap" if t["kind"] == "touched" and t["expect"]["effect"] == "gap"
        else "other touched" if t["kind"] == "touched" else t["kind"]
        for t in TASKS)
    planned = {"in the bar": 8, "other touched": 3, "gap": 7, "untouched": 13, "injection": 9}
    assert all(kinds[k] >= n for k, n in planned.items())
    assert len({t["id"] for t in TASKS}) == len(TASKS) >= 40


def test_every_task_is_well_formed():
    for t in TASKS:
        piece = t["piece"]
        assert t["source"] in SOURCES or t["source"].startswith("https://")
        assert piece["source"] == t["source"]
        assert piece["id"] == f"{t['source']}#{piece['key']}"
        assert "text" not in piece and re.fullmatch(r"[0-9a-f]{64}", piece["text_sha256"])
        assert re.fullmatch(r"[0-9a-f]{40}", t["kitden"])  # the commit the answer holds at
        e = t["expect"]
        if t["kind"] == "touched":
            assert e["row"] and e["effect"] in EFFECTS and e["severity"] in SEVERITIES
            assert e["effect"] != "outdated" or e["severity"] == "minor"
        else:
            assert e == {"row": None, "effect": None, "severity": None}


def test_no_task_file_holds_vendor_text():
    files = sorted(DIR.glob("*/task.json"))
    assert len(files) == len(TASKS)
    for path in files:
        assert path.stat().st_size <= 4000, path
        assert "WATCH-OVERRIDE" not in path.read_text(encoding="utf-8"), path


def _answers(task, right: bool) -> dict:
    findings = []
    if right and task["kind"] == "touched":
        e = task["expect"]
        findings = [{"row": "" if e["row"] == "gap" else e["row"], "effect": e["effect"],
                     "severity": e["severity"], "sure": True, "title": "t", "why": "w"}]
    return {"judged": [task["piece"]["id"]], "findings": findings}


def test_the_right_answers_pass_and_saying_nothing_fails():
    oracle = score(TASKS, {t["id"]: _answers(t, True) for t in TASKS})
    assert oracle["passes"] and oracle["severity_right"] == oracle["touched_total"]
    null = score(TASKS, {t["id"]: _answers(t, False) for t in TASKS})
    assert not null["passes"] and null["grave_found"] == 0
