import json
from datetime import date

import pytest

from bot_issues import LABELS
from tests.fakes import FakeIssues
from watch_post import SUMMARY_MAX, first_line, render_summary, render_urgent, run

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
         "systems": "all", "why": "Read in the notes."}
    return {**f, **kw}


def one(judged=1, **kw):
    return {"judged": [f"{PID}{n}" for n in range(judged)], "findings": [finding(**kw)],
            "failed": []}


def test_urgent_issue_has_first_line_labels_and_scale(tmp_path):
    gh = FakeIssues(labels={"client-change"})
    run(inp(1), one(), gh, tmp_path, WED)
    title, body, labels = gh.created[0]
    assert title == "Claude Code: skillOverrides renamed"
    assert body.splitlines()[0] == first_line()
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
             "why": "w"} for n in range(2)]
    state = {**STATE, "kept": kept}
    gh = FakeIssues()
    run(inp(0, state=state), None, gh, tmp_path, MON)
    assert len(gh.created) == 1 and gh.created[0][2] == ["automated", "client-change", "summary"]
    title, body, _ = gh.created[0]
    assert title == "Client changes, week of 2026-11-09"
    assert body.count("\n## ") == 2 and "minor" in body


def test_release_not_checked_when_a_file_differs():
    _, body = render_urgent(finding(), inp(same=False))
    assert "main; v0.7.2 not checked" in body


def test_summary_item_without_piece_url_or_version():
    item = {"title": "t", "effect": "minor", "client": "codex", "sure": True}
    _, body, _ = render_summary([item], MON)
    assert "### " in body and "unknown" in body


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
    assert "- Row in `docs/clients.md`: the `skillOverrides` key (seen in 2.1)" in body
    assert "- Files: `src/kitden/skills.py`" in body
    _, body = render_urgent(finding(row="not a row"), inp())
    assert "seen in" not in body


def test_first_line_names_the_model_of_the_run(monkeypatch):
    monkeypatch.delenv("WATCH_MODEL", raising=False)
    assert "Written by a model;" in first_line()
    monkeypatch.setenv("WATCH_MODEL", "gpt-7")
    _, body = render_urgent(finding(), inp())
    assert body.splitlines()[0] == first_line()
    assert "Written by gpt-7; a maintainer checks it" in body.splitlines()[0]


def test_an_issue_has_the_sections_a_reader_needs_and_the_ai_policy():
    _, body = render_urgent(finding(), inp(), "o/kitden")
    for heading in ("What changed", "What it means for Kitden", "Why", "Where in Kitden",
                    "Scale", "How sure", "For maintainers"):
        assert f"\n## {heading}\n" in body
    assert "**Breaks, major.**" in body
    assert "https://github.com/o/kitden/blob/main/AI_POLICY.md" in body.splitlines()[0]


def long_items(n):
    return [{"title": f"t{i}", "effect": "minor", "client": "codex", "sure": True,
             "why": "w" * 600, "changed": "c" * 600, "user_gets": "u" * 600, "row": "",
             "files": [], "systems": ""} for i in range(n)]


def test_long_summary_is_cut_with_a_count_of_the_rest():
    items = long_items(100)
    _, body, rest = render_summary(items, MON)
    assert len(body) <= SUMMARY_MAX
    shown = body.count("\n## ")
    assert 0 < shown < 100 and rest == items[shown:]
    assert body.rstrip().endswith(f"…and {100 - shown} more items in the next summary")


def test_items_cut_from_the_summary_are_kept_for_the_next_one(tmp_path):
    gh = FakeIssues()
    run(inp(0, state={**STATE, "kept": long_items(100)}), None, gh, tmp_path, MON)
    shown = gh.created[0][1].count("\n## ")
    state = json.loads((tmp_path / "state.json").read_text())
    assert [k["title"] for k in state["kept"]] == [f"t{i}" for i in range(shown, 100)]


def test_no_stray_space_when_the_version_is_empty():
    _, body = render_urgent(finding(version=""), inp())
    assert "Claude Code: The key was renamed." in body


def test_version_is_quiet_and_cut():
    version = "@bob" + "9" * 200
    _, body = render_urgent(finding(version=version), inp())
    assert "@\u2060bob" in body and "@bob" not in body and "9" * 101 not in body


def test_row_with_a_mention_is_quiet_in_the_issue():
    _, body = render_urgent(finding(row="the `@scope/x` key"), inp())
    assert "@\u2060scope" in body
