import json
import subprocess
from datetime import date, timedelta

import pytest

import bot_issues
from bot_issues import (
    BOT,
    LABELS,
    PAUSE_AFTER,
    VERDICTS,
    GhIssues,
    ensure_labels,
    find_open,
    names,
    pause,
    paused_title,
    upsert,
    verdict,
)
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
    # GitHub's schema allows a label as a bare name too.
    assert names({"labels": ["automated", {"name": "release"}]}) == {"automated", "release"}


def test_the_verdict_is_the_one_verdict_label_or_none():
    assert verdict(issue(1, labels=("automated", "confirmed"))) == "confirmed"
    assert verdict(issue(1, labels=("automated", "false-alarm"))) == "false-alarm"
    assert verdict(issue(1, labels=("automated", "confirmed", "false-alarm"))) is None
    assert verdict(issue(1, labels=("automated", "summary"))) is None
    assert verdict({"labels": ["client-change", "false-alarm"]}) == "false-alarm"


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


class FailingRun:
    """subprocess.run for a `gh api` call that fails: exit 1, the response body on stdout and
    gh's one-line message on stderr, as gh prints them."""

    def __init__(self, body: dict | str, message: str):
        self.out = body if isinstance(body, str) else json.dumps(body)
        self.err = message

    def __call__(self, command, **kwargs):
        raise subprocess.CalledProcessError(1, command, self.out, self.err)


def test_a_label_another_run_just_made_is_no_failure_and_any_other_failure_is(monkeypatch):
    exists = {"message": "Validation Failed", "documentation_url": "https://docs.github.com",
              "errors": [{"resource": "Label", "code": "already_exists", "field": "name"}],
              "status": "422"}
    bad_color = {**exists, "errors": [{"resource": "Label", "code": "invalid",
                                       "field": "color"}]}
    gh = GhIssues("o/kitden")
    monkeypatch.setattr(bot_issues.subprocess, "run",
                        FailingRun(exists, "gh: Validation Failed (HTTP 422)\n"))
    gh.create_label("desk", "006b75", "The owner's desk")
    for run in (FailingRun(bad_color, "gh: Validation Failed (HTTP 422)\n"),
                FailingRun({"message": "Resource not accessible by integration"},
                           "gh: Resource not accessible by integration (HTTP 403)\n"),
                FailingRun("", "error connecting to api.github.com\n")):
        monkeypatch.setattr(bot_issues.subprocess, "run", run)
        with pytest.raises(subprocess.CalledProcessError):
            gh.create_label("desk", "006b75", "The owner's desk")


def test_fake_comments_are_the_bots():
    gh = FakeIssues([issue(4)])
    gh.comment(4, "hello")
    assert gh.commented == [(4, "hello")]
    assert gh.comments(4) == [{"user": {"login": BOT}, "body": "hello"}]
    assert gh.comments(5) == []


FOUND = "Codex: the hooks key was renamed"  # a title a model wrote


def verdicts(n: int, wrong: int) -> list[dict]:
    """`n` bot issues of the watcher with a verdict, the first `wrong` of them `false-alarm`,
    each opened a day after the one before, from 1 November."""
    out = []
    for k in range(n):
        mark = "false-alarm" if k < wrong else "confirmed"
        day = (date(2026, 11, 1) + timedelta(days=k)).isoformat()
        out.append(issue(k + 1, FOUND, labels=("automated", "client-change", mark),
                         state="closed" if mark == "false-alarm" else "open",
                         created=f"{day}T00:00:00Z"))
    return out


AGENT, TITLE = "The client watcher", "The client watcher is paused"
MEANS = "What it finds waits for its next report."


def test_the_pause_names_are_fixed():
    assert VERDICTS == ("confirmed", "false-alarm") and PAUSE_AFTER == 10
    assert paused_title(AGENT) == TITLE


def test_six_false_alarms_in_the_last_ten_pause_the_agent():
    gh = FakeIssues(verdicts(10, wrong=6))
    assert pause(gh, AGENT, "client-change", MEANS) is True
    title, body, labels = gh.created[0]
    assert title == TITLE and labels == ["automated", "desk"]
    assert "6 of its last 10" in body and "close this issue" in body
    assert pause(gh, AGENT, "client-change", MEANS) is True and len(gh.created) == 1


def test_the_pause_issue_links_each_false_alarm_and_says_no_model_wrote_it():
    gh = FakeIssues(verdicts(10, wrong=6))
    pause(gh, AGENT, "client-change", MEANS)
    _, body, _ = gh.created[0]
    assert "no AI model" in body.splitlines()[0]
    for heading in ("What happened", "What it means", "What to do"):
        assert f"\n## {heading}\n" in body
    links = [line for line in body.splitlines() if line.startswith("- https://")]
    assert links == [f"- https://github.com/o/kitden/issues/{n}" for n in range(6, 0, -1)]
    assert FOUND not in body and "hooks" not in body  # the issues' own titles are not copied


def test_the_pause_says_what_it_means_in_the_callers_words():
    gh = FakeIssues(verdicts(10, wrong=6))
    pause(gh, AGENT, "client-change", MEANS)
    _, body, _ = gh.created[0]
    means = body.split("## What it means\n\n")[1].split("\n\n")[0]
    assert means == f"{AGENT} opens no issue while this one is open. {MEANS}"


def test_no_pause_at_five_of_ten_or_with_nine_verdicts():
    assert pause(FakeIssues(verdicts(10, wrong=5)), AGENT, "client-change", MEANS) is False
    assert pause(FakeIssues(verdicts(9, wrong=9)), AGENT, "client-change", MEANS) is False


def test_only_the_newest_ten_count():
    # Twelve verdicts: the two oldest false alarms fall out, leaving 5 of the last 10.
    assert pause(FakeIssues(verdicts(12, wrong=7)), AGENT, "client-change", MEANS) is False
    assert pause(FakeIssues(verdicts(12, wrong=8)), AGENT, "client-change", MEANS) is True


def test_summaries_two_verdicts_and_other_authors_do_not_count():
    noise = [
        issue(90, labels=("automated", "client-change", "summary", "false-alarm")),
        issue(91, labels=("automated", "client-change", "confirmed", "false-alarm")),
        issue(92, labels=("automated", "client-change", "false-alarm"), login="someone"),
    ]
    assert pause(FakeIssues(verdicts(9, wrong=5) + noise), AGENT, "client-change", MEANS) is False


def test_another_origin_does_not_count():
    other = [{**item, "labels": [{"name": "automated"}, {"name": "qa-finding"},
                                 *item["labels"][2:]]} for item in verdicts(10, wrong=10)]
    gh = FakeIssues(other)
    assert pause(gh, AGENT, "client-change", MEANS) is False
    assert pause(gh, "The tester", "qa-finding", "Its findings wait for its next run.") is True
    title, body, _ = gh.created[0]
    assert title == "The tester is paused"
    assert "The tester opens no issue while this one is open. Its findings wait" in body
    assert "summary" not in body and "watcher" not in body


def test_the_count_starts_again_after_the_owner_closes_the_pause():
    lifted = issue(50, TITLE, labels=("automated", "desk"), state="closed",
                   closed="2026-12-01T00:00:00Z")
    old = verdicts(10, wrong=10)  # all opened in November
    gh = FakeIssues([lifted, *old])
    assert pause(gh, AGENT, "client-change", MEANS) is False and gh.created == []


def test_the_newest_closed_pause_is_the_one_that_counts():
    older = issue(50, TITLE, labels=("automated", "desk"), state="closed",
                  closed="2026-10-01T00:00:00Z")
    newer = issue(51, TITLE, labels=("automated", "desk"), state="closed",
                  closed="2026-11-03T12:00:00Z")
    # Only the 7 issues opened from 4 November count: fewer than 10, so no pause.
    lifted = FakeIssues([older, newer, *verdicts(10, wrong=10)])
    assert pause(lifted, AGENT, "client-change", MEANS) is False
    assert pause(FakeIssues([older, *verdicts(10, wrong=10)]), AGENT, "client-change",
                 MEANS) is True


def test_a_persons_issue_with_the_pause_title_pauses_nothing():
    theirs = issue(60, TITLE, labels=("automated", "desk"), login="someone")
    assert pause(FakeIssues([theirs]), AGENT, "client-change", MEANS) is False
