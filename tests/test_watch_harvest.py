import json
import subprocess
import sys
from pathlib import Path

import pytest

import bot_issues
import watch_harvest
from watch_harvest import harvest
from watch_pages import Section
from watch_texts import sha, split_task

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


def test_harvest_reads_open_and_closed_issues(monkeypatch):
    commands = []

    def run(command, **kwargs):
        commands.append(command)
        return subprocess.CompletedProcess(command, 0, json.dumps(issue(7, "confirmed")) + "\n", "")

    monkeypatch.setattr(watch_harvest.subprocess, "run", run)
    assert watch_harvest._issues("o/kitden") == [issue(7, "confirmed")]
    address = commands[0][3]
    assert "state=all" in address and "labels=client-change" in address


def test_only_issues_with_one_verdict_need_their_piece_fetched():
    both = issue(1, "confirmed", "false-alarm")
    open_and_undecided = issue(2)
    confirmed, false_alarm = issue(3, "confirmed"), issue(4, "false-alarm")
    assert watch_harvest._judged([both, open_and_undecided, confirmed, false_alarm]) == [
        confirmed, false_alarm]
    assert watch_harvest.verdict is bot_issues.verdict  # one predicate for the pause and here


def test_fetch_pieces_skips_a_source_with_no_client(tmp_path, monkeypatch):
    sources = tmp_path / "sources.yml"
    sources.write_text("- id: m\n  kind: manifest\n  url: https://example.com/m.json\n")
    monkeypatch.setattr(watch_harvest, "_read", lambda src: [Section("x", "text", "h")])
    assert watch_harvest._fetch_pieces([{**LINE, "piece": "m#x"}], sources) == {}


def test_the_feed_source_of_the_config_changes_nothing_here(monkeypatch):
    calls = []

    def fake_read(src):
        calls.append(src["id"])
        return [Section("2.1.320", "text", "h")]

    def no_get(url):
        raise AssertionError(url)

    monkeypatch.setattr(watch_harvest, "_read", fake_read)
    monkeypatch.setattr(watch_harvest, "get", no_get)
    config = Path(__file__).parents[1] / "config/watch-sources.yml"
    feed_line = {**LINE, "piece": "agent-docs-feed#https://code.claude.com/docs/en/x@2026-11-15",
                 "version": "", "url": "https://code.claude.com/docs/en/x"}
    pieces = watch_harvest._fetch_pieces([LINE, feed_line], config)
    assert list(pieces) == [PID] and calls == ["claude-code-changelog"]


def test_harvest_writes_the_task_without_text_and_the_text_to_the_folder(tmp_path, monkeypatch,
                                                                       capsys):
    tasks, texts, archive = tmp_path / "tasks", tmp_path / "texts", tmp_path / "archive.jsonl"
    tasks.mkdir()
    archive.write_text(json.dumps(LINE) + "\n")
    monkeypatch.setattr(watch_harvest, "_issues", lambda repo: [issue(7, "confirmed")])
    monkeypatch.setattr(watch_harvest, "_fetch_pieces", lambda archive, sources: {PID: PIECE})
    monkeypatch.setattr(sys, "argv", ["watch_harvest.py", "--repo", "o/kitden", "--archive",
                                      str(archive), "--tasks", str(tasks), "--texts", str(texts)])
    watch_harvest.main()
    made = harvest([issue(7, "confirmed")], [LINE], {PID: PIECE})[0][0]
    assert json.loads((tasks / "issue-7/task.json").read_text()) == split_task(made)[0]
    assert json.loads((texts / "issue-7.json").read_text()) == {
        "id": "issue-7", "sha256": sha("text"), "text": "text"}
    assert capsys.readouterr().out.splitlines() == [
        "made 1 tasks: issue-7",
        "upload their text: uv run --locked --only-group watch --only-group watch-io python "
        f"evals/watch_texts.py upload --tasks {tasks} --folder {texts}"]


def run_main_with_texts(tmp_path, monkeypatch, texts):
    tasks, archive = tmp_path / "tasks", tmp_path / "archive.jsonl"
    tasks.mkdir()
    archive.write_text(json.dumps(LINE) + "\n")

    def fetched(*args):
        raise AssertionError("fetched")

    monkeypatch.setattr(watch_harvest, "_issues", fetched)
    monkeypatch.setattr(watch_harvest, "_fetch_pieces", fetched)
    monkeypatch.setattr(sys, "argv", ["watch_harvest.py", "--repo", "o/kitden", "--archive",
                                      str(archive), "--tasks", str(tasks), "--texts", texts])
    with pytest.raises(SystemExit) as stop:
        watch_harvest.main()
    assert stop.value.code == 1 and list(tasks.iterdir()) == []


def test_harvest_refuses_langfuse_as_texts(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    run_main_with_texts(tmp_path, monkeypatch, "langfuse")
    assert not (tmp_path / "langfuse").exists()
    assert len(capsys.readouterr().err.splitlines()) == 1


def test_harvest_refuses_a_texts_folder_inside_the_repository(tmp_path, monkeypatch, capsys):
    inside = Path(__file__).parents[1] / "evals/watch/texts-harvest-test"
    run_main_with_texts(tmp_path, monkeypatch, str(inside))
    assert not inside.exists()
    assert len(capsys.readouterr().err.splitlines()) == 1
