import watch_harvest
from watch_harvest import harvest
from watch_pages import Section

ADDRESS = "https://github.com/o/kitden/issues/7"
PID = "claude-code-changelog#2.1.320"
PIECE = {"id": PID, "client": "claude-code", "kind": "release", "version": "2.1.320",
         "url": "https://example.com", "text": "text", "source": "claude-code-changelog",
         "key": "2.1.320", "hash": "h"}
LINE = {"date": "2026-11-11", "piece": PID, "client": "claude-code", "version": "2.1.320",
        "url": "https://example.com", "row": "the `skillOverrides` key", "title": "t",
        "effect": "breaks", "severity": "major", "sure": True, "why": "w", "issue": ADDRESS,
        "kitden": "a" * 40}


def issue(number=7, *labels, address=ADDRESS):
    return {"number": number, "address": address, "labels": ["client-change", *labels]}


def test_a_confirmed_issue_gives_a_touched_task_with_the_archive_row_and_effect():
    tasks, skipped = harvest([issue(7, "confirmed")], [LINE], {PID: PIECE})
    assert skipped == []
    assert tasks == [{"id": "issue-7", "kind": "touched", "source": "claude-code-changelog",
                      "piece": PIECE,
                      "expect": {"row": "the `skillOverrides` key", "effect": "breaks",
                                 "severity": "major"},
                      "kitden": "a" * 40}]


def test_a_line_without_a_kitden_commit_is_skipped():
    old = {k: v for k, v in LINE.items() if k != "kitden"}
    tasks, skipped = harvest([issue(7, "confirmed")], [old], {PID: PIECE})
    assert tasks == [] and skipped == [{"issue": 7, "why": "the archive line has no Kitden commit"}]


def test_a_gap_line_gives_a_gap_task():
    gap = {**LINE, "row": "", "effect": "gap"}
    tasks, _ = harvest([issue(7, "confirmed")], [gap], {PID: PIECE})
    assert tasks[0]["expect"] == {"row": "gap", "effect": "gap", "severity": "major"}


def test_an_old_minor_line_becomes_an_outdated_minor_task():
    old = {k: v for k, v in LINE.items() if k != "severity"} | {"effect": "minor"}
    tasks, skipped = harvest([issue(7, "confirmed")], [old], {PID: PIECE})
    assert skipped == [] and tasks[0]["expect"]["effect"] == "outdated"
    assert tasks[0]["expect"]["severity"] == "minor"


def test_a_false_alarm_issue_gives_an_untouched_task():
    tasks, skipped = harvest([issue(7, "false-alarm")], [LINE], {PID: PIECE})
    assert skipped == []
    assert tasks[0]["kind"] == "untouched"
    assert tasks[0]["expect"] == {"row": None, "effect": None, "severity": None}


def reasons(skipped):
    return {s["issue"]: s["why"] for s in skipped}


def test_both_labels_neither_label_no_line_and_no_piece_are_skipped_and_named():
    issues = [issue(1, "confirmed", "false-alarm", address="a1"), issue(2, address="a2"),
              issue(3, "confirmed", address="a3"), issue(4, "confirmed", address="a4")]
    archive = [{**LINE, "issue": f"a{n}"} for n in (1, 2, 4)]
    archive[2]["piece"] = "claude-code-changelog#9.9"
    tasks, skipped = harvest(issues, archive, {PID: PIECE})
    assert tasks == []
    assert sorted(reasons(skipped)) == [1, 2, 3, 4]
    assert "both" in reasons(skipped)[1]
    assert "neither" in reasons(skipped)[2]
    assert "archive" in reasons(skipped)[3]
    assert "piece" in reasons(skipped)[4]


def test_an_existing_id_is_not_made_again():
    tasks, skipped = harvest([issue(7, "confirmed")], [LINE], {PID: PIECE}, existing={"issue-7"})
    assert tasks == []
    assert reasons(skipped) == {7: "the task exists"}


def test_it_does_not_change_its_inputs():
    issues, archive, pieces = [issue(7, "confirmed")], [dict(LINE)], {PID: dict(PIECE)}
    harvest(issues, archive, pieces)
    assert issues == [issue(7, "confirmed")] and archive == [LINE] and pieces == {PID: PIECE}


DOC = "https://docs.example.com/hooks"


def test_fetch_pieces_reads_each_source_once_and_reads_doc_pages(tmp_path, monkeypatch):
    sources = tmp_path / "sources.yml"
    sources.write_text("- id: claude-code-changelog\n  client: claude-code\n  kind: page\n"
                       "  url: https://example.com\n")
    calls = []

    def fake_read(src):
        calls.append(src["id"])
        return [Section("2.1.320", "text", "h"), Section("2.1.321", "more", "h2")]

    monkeypatch.setattr(watch_harvest, "_read", fake_read)
    monkeypatch.setattr(watch_harvest, "get", lambda url: (f"<h2>Hooks</h2>{url}", "text/html"))
    lines = [LINE, {**LINE, "piece": "claude-code-changelog#2.1.321"},
             {**LINE, "piece": f"{DOC}#Hooks", "version": "", "url": DOC}]
    pieces = watch_harvest._fetch_pieces(lines, sources)
    assert calls == ["claude-code-changelog"]
    assert pieces[PID] == {**PIECE, "text": "text"}
    doc = pieces[f"{DOC}#Hooks"]
    assert (doc["kind"], doc["version"], doc["url"], doc["source"], doc["key"]) == (
        "doc", "", DOC, DOC, "Hooks")
    assert doc["client"] == "claude-code" and DOC in doc["text"]
