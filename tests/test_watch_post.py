import json
from datetime import date

import pytest

from bot_issues import LABELS
from tests.fakes import FakeIssues, issue
from watch_post import (
    AGENT,
    PAUSED_MEANS,
    SUMMARY_MAX,
    render_summary,
    render_urgent,
    run,
)

WED, MON = date(2026, 11, 11), date(2026, 11, 9)
URL = "https://example.com/changelog"
PID = "claude-code-changelog#2.1.320"
STATE = {"sources": {}, "fails": {}, "kept": [], "urgent": {"week": "", "count": 0}}
LIST = (
    "## Claude Code\n\n| What | Kind | Files | Seen in | Systems | Source |\n"
    "|---|---|---|---|---|---|\n"
    "| the `skillOverrides` key | setting | `src/kitden/skills.py` | 2.1 | all | https://x |\n"
)


def piece(n=0):
    return {"id": f"{PID}{n}", "client": "claude-code", "kind": "release", "version": "2.1.320",
            "url": URL, "text": "nothing", "source": "claude-code-changelog", "key": f"k{n}",
            "hash": "h"}


def inp(pieces=0, same=True, state=None):
    return {"pieces": [piece(n) for n in range(pieces)], "list": LIST, "release": "v0.7.2",
            "files": {"src/kitden/skills.py": {"text": "x", "same_in_release": same}},
            "known_titles": [], "state": state or json.loads(json.dumps(STATE))}


def finding(n=0, **kw):
    f = {"piece": f"{PID}{n}", "client": "claude-code", "title": "skillOverrides renamed",
         "changed": "The key was renamed.", "version": "2.1.320", "url": URL,
         "row": "the `skillOverrides` key", "files": ["src/kitden/skills.py"],
         "effect": "breaks", "severity": "major", "sure": True,
         "user_gets": "Skills fail to load.",
         "systems": "all", "why": "Read in the notes.",
         "fix": "Read the new key in skills.py."}
    return {**f, **kw}


def one(judged=1, **kw):
    return {"judged": [f"{PID}{n}" for n in range(judged)], "findings": [finding(**kw)],
            "failed": []}


def test_urgent_issue_has_first_line_labels_and_scale(tmp_path, capsys):
    gh = FakeIssues(labels={"client-change"})
    run(inp(1), one(), gh, tmp_path, WED)
    assert json.loads((tmp_path / "log.jsonl").read_text())["paused"] is False
    assert "paused" not in capsys.readouterr().out
    title, body, labels = gh.created[0]
    assert title == "Claude Code: skillOverrides renamed"
    first = body.splitlines()[0]
    assert first.startswith("<picture>") and 'alt="Claude Code: 2.1.320"' in first
    assert 'alt="risk: high"' in first and 'alt="sure: yes"' in first
    assert labels == ["automated", "client-change", "claude-code", "breaks", "major"]
    assert "main and v0.7.2" in body
    assert {"claude-code", "breaks"} <= {name for name, *_ in gh.created_labels}
    assert "client-change" not in {name for name, *_ in gh.created_labels}


def test_bad_findings_post_nothing_and_keep_the_memory(tmp_path):
    gh = FakeIssues()
    with pytest.raises(SystemExit):
        run(inp(1), {"nonsense": 1}, gh, tmp_path, WED)
    assert gh.created == [] and not (tmp_path / "state.json").exists()
    assert not (tmp_path / "log.jsonl").exists() and not (tmp_path / "archive.jsonl").exists()


def test_quiet_day_opens_nothing_but_saves_state(tmp_path):
    gh = FakeIssues()
    run(inp(0), None, gh, tmp_path, WED)
    assert gh.created == [] and (tmp_path / "state.json").exists()
    assert len((tmp_path / "log.jsonl").read_text().splitlines()) == 1


def test_monday_summary_is_one_issue_with_two_labels(tmp_path):
    kept = [{"title": f"t{n}", "effect": "minor", "client": "codex", "sure": True,
             "changed": "c", "row": "", "files": [], "user_gets": "u", "systems": "",
             "why": "w", "fix": ""} for n in range(2)]
    state = {**STATE, "kept": kept}
    gh = FakeIssues()
    run(inp(0, state=state), None, gh, tmp_path, MON)
    assert len(gh.created) == 1 and gh.created[0][2] == ["automated", "client-change", "summary"]
    title, body, _ = gh.created[0]
    assert title == "Client changes, week of 2026-11-09"
    assert body.count("\n### ") == 2
    head = body.splitlines()[0].replace("&nbsp;", "")  # hard spaces keep the columns wide
    assert head == "| # | Client | Change | Risk | Sure |"
    # The table holds each item's badges, so the items under it do not repeat them.
    assert body.count('alt="risk: low"') == 2 and body.count('alt="client: Codex"') == 2
    row = body.splitlines()[2]
    assert row.startswith("| 1 | <picture>") and row.count("<picture>") == 3 and "| t0 |" in row
    assert "### 1. Codex: t0\n\nOnly Kitden's own notes are out of date. u\n" in body


def test_release_not_checked_when_a_file_differs():
    _, body = render_urgent(finding(), inp(same=False))
    assert "main (v0.7.2 not checked)" in body


def test_summary_item_without_piece_url_or_version():
    item = {"title": "t", "effect": "minor", "client": "codex", "sure": True}
    _, body, _ = render_summary([item], MON)
    assert "### 1. t" in body and 'alt="client: Codex"' in body and 'alt="risk: low"' in body


def test_archive_has_a_line_per_finding_and_per_quiet_piece(tmp_path):
    gh = FakeIssues()
    run(inp(2), one(judged=2), gh, tmp_path, WED)
    lines = [json.loads(x) for x in (tmp_path / "archive.jsonl").read_text().splitlines()]
    assert [x["effect"] for x in lines] == ["breaks", "none"]
    assert lines[0]["issue"] == gh.issues[0]["html_url"] and lines[1]["issue"] == ""


def test_archive_lines_keep_the_kitden_commit_of_the_run(tmp_path):
    run({**inp(2), "kitden": "c" * 40}, one(judged=2), FakeIssues(), tmp_path, WED)
    lines = [json.loads(x) for x in (tmp_path / "archive.jsonl").read_text().splitlines()]
    assert [x["kitden"] for x in lines] == ["c" * 40, "c" * 40]


def test_failed_pieces_count_their_tries_in_the_memory(tmp_path):
    gh = FakeIssues()
    run(inp(2), {"judged": [], "findings": [], "failed": [f"{PID}0", f"{PID}1"]}, gh,
        tmp_path, WED)
    state = json.loads((tmp_path / "state.json").read_text())
    assert state["tries"] == {f"{PID}0": 1, f"{PID}1": 1} and gh.created == []
    log = json.loads((tmp_path / "log.jsonl").read_text())
    assert log["failed"] == 2


def test_every_missing_label_is_created_on_each_run(tmp_path):
    gh = FakeIssues(labels={"client-change"})
    run(inp(0), None, gh, tmp_path, WED)
    names = [name for name, *_ in LABELS]
    assert [name for name, *_ in gh.created_labels] == [n for n in names if n != "client-change"]


def test_what_it_touches_shows_where_the_user_sees_it():
    _, body = render_urgent(finding(), inp())
    assert "**Files:** `src/kitden/skills.py`" in body
    assert "the `skillOverrides` key" not in body  # the list's row is for the judge


def test_the_issue_names_no_model_and_no_author(monkeypatch):
    monkeypatch.setenv("WATCH_MODEL", "gpt-7")
    _, body = render_urgent(finding(), inp())
    assert "gpt-7" not in body and "Automated" not in body  # the label says it
    assert "Lantern" not in body and "Urgent" not in body  # GitHub shows the author


def test_an_issue_is_badges_a_lead_line_then_problem_fix_checklist_and_a_box():
    _, body = render_urgent(finding(), inp())
    lines = body.splitlines()
    assert lines[2] == "A Kitden action fails. Skills fail to load."
    heads = [line for line in lines if line.startswith("#")]
    assert heads == ["### Problem", "### Fix", "### Checklist"]
    assert "### Problem\nThe key was renamed. Read in the notes." in body
    assert "### Fix\nRead the new key in skills.py.\n**Files:** `src/kitden/skills.py`" in body
    assert "### Checklist\n- [ ] Test with a sandbox home" in body
    assert "preview → Apply with a backup → verify → Undo" in body  # a break: settings rule
    assert "> [!IMPORTANT]\n> Add `confirmed` if this is right" in body
    assert lines[-1].startswith("<sub>Checked on Kitden main and v0.7.2 · ")
    assert "[source](" in lines[-1] and "[how the watcher works](" in lines[-1]


def test_the_checklist_follows_the_type():
    _, gap = render_urgent(finding(effect="gap", fix=""), inp())
    assert "add a row to `docs/clients.md`" in gap and "PRIVACY.md" in gap
    assert "### Fix\n**Files:**" in gap  # no fix written: only the files
    _, old = render_urgent(finding(effect="outdated"), inp())
    assert old.count("- [ ] ") == 1 and "checked date" in old


def test_a_summary_names_the_checks_once_at_the_end():
    items = [finding(n) for n in range(3)]
    _, body, _ = render_summary(items, MON, inp())
    assert body.count("**When you fix one:**") == 1
    assert body.count("sandbox home") == 1 and "- [ ]" not in body
    assert "> [!NOTE]\n> Nothing here is urgent." in body


def test_an_issue_says_confirmed_keeps_it_open():
    _, body = render_urgent(finding(), inp(1))
    assert "Add `confirmed` if this is right (it stays open until it is fixed)" in body
    assert "close it with `false-alarm`" in body


def long_items(n):
    return [{"title": f"t{i}", "effect": "minor", "client": "codex", "sure": True,
             "why": "w" * 600, "changed": "c" * 600, "user_gets": "u" * 600, "row": "",
             "files": [], "systems": "", "fix": ""} for i in range(n)]


def test_long_summary_is_cut_with_a_count_of_the_rest():
    items = long_items(100)
    _, body, rest = render_summary(items, MON)
    assert len(body) <= SUMMARY_MAX
    shown = body.count("\n### ")
    assert 0 < shown < 100 and rest == items[shown:]
    assert f"…and {100 - shown} more items in the next summary" in body


def test_items_cut_from_the_summary_are_kept_for_the_next_one(tmp_path):
    gh = FakeIssues()
    run(inp(0, state={**STATE, "kept": long_items(100)}), None, gh, tmp_path, MON)
    shown = gh.created[0][1].count("\n### ")
    state = json.loads((tmp_path / "state.json").read_text())
    assert [k["title"] for k in state["kept"]] == [f"t{i}" for i in range(shown, 100)]


def test_no_stray_space_when_the_version_is_empty():
    _, body = render_urgent(finding(version=""), inp())
    assert 'alt="client: Claude Code"' in body and "### Problem\nThe key was renamed." in body


def test_version_is_quiet_and_cut():
    version = "@bob" + "9" * 200
    _, body = render_urgent(finding(version=version), inp())
    assert 'alt="Claude Code: bob999' in body  # a badge shows plain text only, cut short
    assert "@bob" not in body and "9" * 41 not in body


def test_a_word_the_model_passed_over_is_one_line_not_an_item():
    hints = [{"title": f"Mentions `{w}`", "hint": True, "client": "claude-code",
              "version": "2.1.325", "effect": "unknown", "severity": "minor", "sure": False}
             for w in (".claude/settings.json", ".claude")]
    _, body, _ = render_summary(hints, MON)
    assert "###" not in body and "| # |" not in body
    assert ("**Mentioned, nothing found:** Claude Code 2.1.325 mentions "
            "`.claude/settings.json`, `.claude`.") in body


def paused(state="open"):
    return issue(50, "The client watcher is paused", labels=("automated", "desk"), state=state,
                 closed="2026-11-10T00:00:00Z" if state == "closed" else None)


def test_the_agent_name_is_the_watchers():
    assert AGENT == "The client watcher"


def test_a_paused_watcher_opens_nothing_and_keeps_what_it_found(tmp_path):
    gh = FakeIssues([issue(50, "The client watcher is paused", labels=("automated", "desk"))])
    run(inp(1), one(), gh, tmp_path, WED)
    state = json.loads((tmp_path / "state.json").read_text())
    assert gh.created == []
    assert [k["title"] for k in state["kept"]] == ["skillOverrides renamed"]
    assert state["urgent"]["count"] == 0 and "summary_week" not in state


def test_a_paused_day_writes_the_log_and_archive_with_nothing_posted(tmp_path, capsys):
    run(inp(1), one(), FakeIssues([paused()]), tmp_path, WED)
    log = json.loads((tmp_path / "log.jsonl").read_text())
    assert log["findings"] == 1 and log["urgent"] == 0 and log["summary"] == 0
    assert log["paused"] is True
    assert capsys.readouterr().out.splitlines() == [
        "The client watcher is paused: nothing posted, 1 finding kept for its first summary "
        "after the pause."]
    archive = [json.loads(x) for x in (tmp_path / "archive.jsonl").read_text().splitlines()]
    assert [x["title"] for x in archive] == ["skillOverrides renamed"]
    assert archive[0]["issue"] == ""


def test_a_paused_monday_keeps_the_summary_for_after_the_pause(tmp_path, capsys):
    kept = [{"title": f"t{n}", "effect": "minor", "client": "codex", "sure": True,
             "changed": "c", "row": "", "files": [], "user_gets": "u", "systems": "",
             "why": "w", "fix": ""} for n in range(2)]
    gh = FakeIssues([paused()])
    run(inp(1, state={**STATE, "kept": kept, "summary_week": "2026-W45"}), one(), gh,
        tmp_path, MON)
    state = json.loads((tmp_path / "state.json").read_text())
    assert gh.created == [] and "summary_week" not in state
    assert [k["title"] for k in state["kept"]][0] == "skillOverrides renamed"
    assert {k["title"] for k in state["kept"]} == {"skillOverrides renamed", "t0", "t1"}
    assert state["urgent"]["count"] == 0
    assert "3 findings kept" in capsys.readouterr().out

    # The owner closes the pause: the next run posts everything in one summary.
    lifted = FakeIssues([paused("closed")])
    run(inp(0, state=state), None, lifted, tmp_path, WED)
    assert len(lifted.created) == 1
    title, body, labels = lifted.created[0]
    assert labels == ["automated", "client-change", "summary"]
    assert all(f": {t}\n" in body for t in ("skillOverrides renamed", "t0", "t1"))


def test_a_noisy_watcher_opens_only_its_pause_issue(tmp_path):
    wrong = [issue(n, labels=("automated", "client-change", "false-alarm"), state="closed",
                   created=f"2026-10-{n:02d}T00:00:00Z") for n in range(1, 11)]
    gh = FakeIssues(wrong)
    run(inp(1), one(), gh, tmp_path, WED)
    assert [(title, labels) for title, _, labels in gh.created] == [
        ("The client watcher is paused", ["automated", "desk"])]
    means = gh.created[0][1].split("## What it means\n\n")[1].split("\n\n")[0]
    assert means == f"The client watcher opens no issue while this one is open. {PAUSED_MEANS}"
    assert "summary" in PAUSED_MEANS
    assert "desk" in {name for name, *_ in gh.created_labels}
    state = json.loads((tmp_path / "state.json").read_text())
    assert [k["title"] for k in state["kept"]] == ["skillOverrides renamed"]
