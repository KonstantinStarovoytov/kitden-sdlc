"""desk_post.py: one ci-failure issue per red nightly part, rewritten each day and closed when the
part is green. The desk's own state is on the desk page (tests/test_desk_page.py)."""
import json
import re

import pytest

import desk_post
from bot_issues import BOT
from desk_post import ci_body, ci_title, main, post, post_nightly
from post_findings import WORD_JOINER, one_line
from tests.fakes import FakeIssues, issue
from tests.test_desk import JOB_URL, RUN_URL
from tests.test_desk import row as desk_row

URL = "https://github.com/KonstantinStarovoytov/kitden/issues/12"

# desk.json as desk_gather writes it (the page's tests read it too).
DESK = {
    "version": 1,
    "updated": "2026-11-16T06:41:00Z",
    "repo": "KonstantinStarovoytov/kitden",
    "overall": "amber",
    "lights": [
        {"id": "works", "name": "Works", "state": "grey",
         "why": "Not measured yet: no check run of main was read."},
        {"id": "clients", "name": "Clients", "state": "amber",
         "why": "Issue #12 (a confirmed major client change) has been open 4.0 days."},
        {"id": "bugs", "name": "Bugs", "state": "green", "why": ""},
        {"id": "agents", "name": "Agents", "state": "green", "why": ""},
        {"id": "queue", "name": "Queue", "state": "green", "why": ""},
    ],
    "use": {"issues_from_others": 0, "pulls_from_others": 1, "stars": 12, "downloads": 340},
    "waiting": [{"kind": "verdict", "title": "Codex: the hooks key was renamed", "url": URL,
                 "do": "Put `confirmed` on it, or close it with `false-alarm`.", "days": 2.0}],
    "week": [{"agent": "claude", "name": "Claude reviewer", "runs": 12, "failed": 1, "did": 9,
              "agreed": 3, "disagreed": 1, "no_answer": 2}],
    "review": {"clean": 4, "fixed": 6, "days_to_merge": 1.5},
    "found_by": [{"month": "2026-11", "review": 6, "nightly": None, "tester": None,
                  "watcher": 0, "owner": 4, "others": 0}],
    "misses": [{"issue": 81, "pull": 70,
                "url": "https://github.com/KonstantinStarovoytov/kitden/issues/81"}],
    "budget": {
        "agents": [{"agent": "claude", "runs": 12, "cap": "20 reviews a day, 5 findings each"}],
        "keys": [{"name": "OPENAI_API_KEY", "stored": "Kitden", "used_by": ["luna reviewer"],
                  "money_cap": "$5 a month", "dashboard": "https://platform.openai.com/usage"}],
    },
}


# --- One ci-failure issue per red part ---


def row(part, state, failed=(), **keys):
    """One row of desk.json's `nightly`, with its failed jobs."""
    return {**desk_row(part, state, **keys), "failed": list(failed)}


RED = row("clients", "red", since="2026-11-18")
TITLE_RED = "Nightly tests: clients is red"


def red_issue(number=5, title=TITLE_RED, login=BOT):
    return issue(number, title, ("automated", "ci-failure"), login=login)


def test_a_red_part_opens_one_issue_with_both_labels():
    gh = FakeIssues()
    post_nightly(gh, [RED])
    ((title, body, labels),) = gh.created
    assert (title, labels) == (TITLE_RED, ["automated", "ci-failure"])
    assert "2026-11-18" in body and "no AI model" in body


def test_the_next_day_the_same_issue_is_rewritten_not_opened_again():
    gh = FakeIssues([red_issue()])
    post_nightly(gh, [RED])
    assert gh.created == [] and [number for number, _, _ in gh.edited] == [5]


def test_a_grey_part_leaves_its_issue_alone_and_a_green_one_closes_it():
    gh = FakeIssues([red_issue()])
    post_nightly(gh, [row("clients", "grey")])
    assert gh.closed == [] and gh.edited == []
    post_nightly(gh, [row("clients", "green")])
    assert gh.closed == [5]


def test_an_issue_of_a_job_that_is_gone_closes_only_when_no_row_is_grey():
    gh = FakeIssues([red_issue(6, "Nightly tests: old-job is red")])
    post_nightly(gh, [row("systems", "green"), row("browser", "grey")])
    assert gh.closed == []
    post_nightly(gh, [row("systems", "green"), row("browser", "green")])
    assert gh.closed == [6]


def test_a_row_that_cannot_be_read_keeps_the_issues_of_gone_jobs_open():
    gh = FakeIssues([red_issue(6, "Nightly tests: old-job is red")])
    post_nightly(gh, [row("systems", "green"), "?", {"part": None, "state": "red"}])
    assert (gh.created, gh.closed) == ([], [])


def test_a_persons_issue_with_the_bots_title_and_label_is_never_touched():
    gh = FakeIssues([red_issue(login="someone")])
    post_nightly(gh, [RED])
    assert (gh.edited, gh.closed, len(gh.created)) == ([], [], 1)


def test_without_rows_nothing_is_opened_or_closed():
    gh = FakeIssues([red_issue()])
    post_nightly(gh, None)
    assert (gh.created, gh.edited, gh.closed) == ([], [], [])


def test_the_title_names_the_workflow_and_is_never_empty():
    assert ci_title(RED) == TITLE_RED
    assert ci_title({**RED, "name": None}) == "nightly.yml: clients is red"
    assert ci_title({**RED, "name": " ", "workflow": None}) == "Nightly run: clients is red"
    assert ci_title({**RED, "name": "a\nb"}) == "a b: clients is red"


@pytest.mark.parametrize("name", ["@owner", "[x](http://e.example)", "<!-- x", "a | b", "a\nb",
                                  "me@evil.example"])
def test_a_job_or_step_name_cannot_ping_link_or_break_the_page(name):
    body = ci_body(row("systems", "red", failed=[{"job": name, "step": name, "url": JOB_URL}]))
    assert name not in body and "http://e.example" not in body
    assert WORD_JOINER + "@" not in body  # a joiner before "@" would make "@evil" a mention
    assert not re.search(r"(?<!\w)@evil", body)


def test_the_issue_lists_each_failed_job_linked_and_says_what_to_do():
    failed = [{"job": "systems (macos-15-intel, 3.13)", "step": "Run uv run pytest -q",
               "url": JOB_URL},
              {"job": "systems (b, 3.12)", "step": None, "url": "http://e.example/job"}]
    body = ci_body(row("systems", "red", failed=failed, since="2026-11-13"))
    assert body.startswith("<picture>") and 'alt="red since: 2026-11-13"' in body
    assert "2 jobs of the nightly part systems failed." in body
    one = ci_body(row("systems", "red", failed=failed[:1], since="2026-11-13"))
    assert "1 job of the nightly part systems failed." in one
    first, second = (one_line(item["job"]) for item in failed)
    assert f"- [{first}]({JOB_URL}): the step \"Run uv run pytest -q\" failed" in body
    assert f"- {second} (`http://e.example/job`): no failed step is named" in body
    assert "Kitden may not work on that system or Python" in body
    assert "`tests/set-aside.txt`" in body and f"]({RUN_URL})" in body
    places = [body.index(part) for part in ("### Failed", "### What it means", "### What to do")]
    assert places == sorted(places) and body.rstrip().endswith("</sub>")
    assert "closes itself when the job is green" in body


@pytest.mark.parametrize(("part", "means"), [
    ("clients", "newest Claude Code or Codex"), ("browser", "in a real browser"),
    ("test", "scheduled test run failed")])
def test_what_it_means_depends_on_the_part(part, means):
    assert means in ci_body(row(part, "red", since="2026-11-18"))


def test_post_makes_the_labels_and_opens_only_the_red_parts_issue():
    gh = FakeIssues()
    post(gh, {**DESK, "nightly": [row("systems", "green"), RED]})
    assert [title for title, _, _ in gh.created] == [TITLE_RED]  # no desk issue any more
    assert "ci-failure" in {name for name, *_ in gh.created_labels}


def test_no_rows_at_all_close_no_issue():
    gh = FakeIssues([red_issue()])
    post_nightly(gh, [])
    assert (gh.created, gh.edited, gh.closed) == ([], [], [])


# --- The command ---


def write_desk(tmp_path, desk=DESK):
    path = tmp_path / "desk.json"
    path.write_text(json.dumps(desk))
    return path


def test_dry_run_prints_the_issue_of_each_red_part_and_calls_nothing(tmp_path, capsys,
                                                                     monkeypatch):
    def no_github(repo):
        raise AssertionError("a dry run called GitHub")

    monkeypatch.setattr(desk_post, "GhIssues", no_github)
    path = write_desk(tmp_path, {**DESK, "nightly": [row("systems", "green"), RED]})
    assert main(["--desk", str(path), "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert f"----- The issue {TITLE_RED!r}, opened or rewritten -----" in out
    assert ci_body(RED) in out and "systems is red" not in out


def test_the_command_posts_to_the_repository_given(tmp_path, monkeypatch):
    made = []

    def fake(repo):
        made.append(repo)
        return FakeIssues()

    monkeypatch.setattr(desk_post, "GhIssues", fake)
    path = write_desk(tmp_path, {**DESK, "nightly": [RED]})
    assert main(["--desk", str(path), "--repo", "o/kitden"]) == 0
    assert made == ["o/kitden"]


def test_posting_needs_the_repository(tmp_path, capsys):
    with pytest.raises(SystemExit):
        main(["--desk", str(write_desk(tmp_path))])
    assert "--repo is needed" in capsys.readouterr().err
