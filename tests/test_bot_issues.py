import json
import subprocess

import bot_issues
from bot_issues import BOT, LABELS, GhIssues, ensure_labels, find_open, names, upsert
from tests.fakes import FakeIssues, issue


def test_a_persons_issue_with_the_bots_title_is_never_touched():
    theirs = issue(5, "Time for a release?", login="someone")
    labelled = issue(6, "Time for a release?", labels=("automated", "release"), login="someone")
    gh = FakeIssues([theirs, labelled])
    assert find_open(gh, "Time for a release?") is None
    upsert(gh, "Time for a release?", "body", ["automated", "release"])
    assert gh.created == [("Time for a release?", "body", ["automated", "release"])]
    quiet = FakeIssues([theirs, labelled])
    upsert(quiet, "Time for a release?", "", ["automated", "release"])
    assert quiet.created == [] and quiet.edited == [] and quiet.closed == []


def test_upsert_edits_then_closes_the_bots_own_issue():
    gh = FakeIssues([issue(7, "T", labels=("automated", "release"))])
    upsert(gh, "T", "new", ["automated", "release"])
    assert gh.edited == [(7, "new", ["automated", "release"])]
    upsert(gh, "T", "", ["automated", "release"])
    assert gh.closed == [7]


def test_upsert_opens_one_issue_and_then_finds_it():
    gh = FakeIssues()
    upsert(gh, "T", "first", ["automated", "release"])
    upsert(gh, "T", "second", ["automated", "release"])
    assert len(gh.created) == 1
    assert [number for number, *_ in gh.edited] == [find_open(gh, "T")]


def test_a_closed_bot_issue_is_not_reopened_or_edited():
    gh = FakeIssues([issue(3, "T", state="closed", closed="2026-11-02T00:00:00Z")])
    assert find_open(gh, "T") is None
    upsert(gh, "T", "", ["automated", "release"])
    assert gh.closed == [] and gh.edited == []


def test_every_missing_label_is_created():
    gh = FakeIssues(labels={"automated"})
    ensure_labels(gh)
    made = {name for name, *_ in gh.created_labels}
    assert {"release", "desk", "client-change", "confirmed", "false-alarm"} <= made
    assert "automated" not in made


def test_labels_are_unique_and_described():
    found = [name for name, *_ in LABELS]
    assert len(found) == len(set(found))
    for name, color, description in LABELS:
        assert len(color) == 6 and int(color, 16) >= 0, name
        assert description, name
    described = {name: text for name, _, text in LABELS}
    assert described["release"] == "Opened by the release watch"
    assert described["desk"] == "The owner's desk"
    assert described["confirmed"] == "Set by the owner: the bot was right; open until fixed"
    assert described["false-alarm"] == "Set by the owner on closing: the bot was wrong"


def test_names_are_the_label_names():
    assert names(issue(1, labels=("automated", "release"))) == {"automated", "release"}


class FakeRun:
    """subprocess.run for `gh api`: answers with `out` and records each command."""

    def __init__(self, out=""):
        self.out, self.commands, self.kwargs = out, [], []

    def __call__(self, command, **kwargs):
        self.commands.append(command)
        self.kwargs.append(kwargs)
        return subprocess.CompletedProcess(command, 0, self.out, "")


def test_gh_issues_asks_by_label_and_keeps_only_the_bots(monkeypatch):
    mine = issue(1, "T")
    theirs = issue(2, "T", login="someone")
    pull = {**issue(3, "T"), "pull_request": {"url": "https://api.github.com/x"}}
    # Two pages, as `gh api --paginate` prints them: one JSON array after another.
    run = FakeRun(json.dumps([mine, theirs]) + "\n" + json.dumps([pull]))
    monkeypatch.setattr(bot_issues.subprocess, "run", run)
    gh = GhIssues("o/kitden")
    assert gh.repo == "o/kitden"
    assert gh.by_bot() == [mine]
    command = run.commands[0]
    assert command[:2] == ["gh", "api"] and "--paginate" in command
    endpoint = command[2]
    assert endpoint.startswith("repos/o/kitden/issues?")
    assert "labels=automated" in endpoint and "state=open" in endpoint
    assert all(kw.get("check") is True for kw in run.kwargs)


def test_gh_issues_edit_adds_labels_and_never_replaces_them(monkeypatch):
    run = FakeRun("https://github.com/o/kitden/issues/4\n")
    monkeypatch.setattr(bot_issues.subprocess, "run", run)
    gh = GhIssues("o/kitden")
    assert gh.create("T", "b", ["automated", "release"]) == "https://github.com/o/kitden/issues/4"
    gh.edit(4, "c", ["automated", "release"])
    gh.close(4)
    gh.comment(4, "hi")
    create, body, add, close, comment = (c[2:] for c in run.commands)
    assert create[:3] == ["repos/o/kitden/issues", "--method", "POST"]
    assert "labels[]=automated" in create and "labels[]=release" in create
    assert body[:3] == ["repos/o/kitden/issues/4", "--method", "PATCH"]
    assert "body=c" in body and not any(x.startswith("labels") for x in body)
    assert add[:3] == ["repos/o/kitden/issues/4/labels", "--method", "POST"]
    assert "labels[]=automated" in add and "labels[]=release" in add
    assert close[:3] == ["repos/o/kitden/issues/4", "--method", "PATCH"] and "state=closed" in close
    assert comment[:3] == ["repos/o/kitden/issues/4/comments", "--method", "POST"]
    assert all(kw.get("check") is True for kw in run.kwargs)


def test_fake_comments_are_the_bots():
    gh = FakeIssues([issue(4)])
    gh.comment(4, "hello")
    assert gh.commented == [(4, "hello")]
    assert gh.comments(4) == [{"user": {"login": BOT}, "body": "hello"}]
    assert gh.comments(5) == []
