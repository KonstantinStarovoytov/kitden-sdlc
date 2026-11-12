import json
from collections import Counter
from pathlib import Path

from watch_fetch import PIECE_CHARS
from watch_score import GRAVE, load_tasks, score

TASKS = load_tasks(Path(__file__).resolve().parent.parent / "evals/watch/tasks")
SOURCES = {"claude-code-changelog", "codex-releases", "cursor-changelog"}


def test_the_set_has_the_planned_mix():
    kinds = Counter(
        "grave" if t["kind"] == "touched" and t["expect"]["effect"] in GRAVE
        else "minor" if t["kind"] == "touched" and t["expect"]["effect"] == "minor"
        else "gap" if t["kind"] == "touched" else t["kind"]
        for t in TASKS)
    planned = {"grave": 5, "minor": 2, "gap": 2, "untouched": 5, "injection": 1}
    assert all(kinds[k] >= n for k, n in planned.items())
    assert len({t["id"] for t in TASKS}) == len(TASKS) >= 15


def test_every_task_is_well_formed():
    for t in TASKS:
        piece = t["piece"]
        assert t["source"] in SOURCES or t["source"].startswith("https://")
        assert piece["source"] == t["source"]
        assert piece["id"] == f"{t['source']}#{piece['key']}"
        assert piece["text"].strip() and len(piece["text"]) <= PIECE_CHARS + 400
        if t["kind"] == "touched":
            assert t["expect"]["row"] and t["expect"]["effect"]
        else:
            assert t["expect"] == {"row": None, "effect": None}


def test_the_injection_task_carries_the_planted_line():
    (planted,) = [t for t in TASKS if t["kind"] == "injection"]
    assert "WATCH-OVERRIDE" in planted["piece"]["text"]
    assert json.dumps([t for t in TASKS if t is not planted]).count("WATCH-OVERRIDE") == 0


def _answers(task, right: bool) -> dict:
    findings = []
    if right and task["kind"] == "touched":
        e = task["expect"]
        findings = [{"row": "" if e["row"] == "gap" else e["row"], "effect": e["effect"],
                     "sure": True, "title": "t", "why": "w"}]
    return {"judged": [task["piece"]["id"]], "findings": findings}


def test_the_right_answers_pass_and_saying_nothing_fails():
    oracle = score(TASKS, {t["id"]: _answers(t, True) for t in TASKS})
    assert oracle["passes"] and oracle["severity_right"] == oracle["touched_total"]
    null = score(TASKS, {t["id"]: _answers(t, False) for t in TASKS})
    assert not null["passes"] and null["grave_found"] == 0
