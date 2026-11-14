import http.client
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from subprocess import CalledProcessError

import pytest

import count_reviews
import desk_gather
from count_reviews import REPO
from desk_gather import fetch_downloads, gather, main
from tests.fakes import issue

ROOT = Path(__file__).resolve().parent.parent
ROSTER = json.loads((ROOT / "config/agents.json").read_text())
NOW = datetime(2026, 11, 16, 7, tzinfo=UTC)  # a Monday
SDLC = "KonstantinStarovoytov/kitden-sdlc"
WEEK_AGO = "2026-11-09T07:00:00Z"
DOWNLOADS = '{"data": {"last_month": 340}}'


def ago(days):
    return (NOW - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")


def pull(number, updated, state="open", created=None, **extra):
    return {"number": number, "state": state, "updated_at": updated,
            "created_at": created or updated, "user": {"login": "someone"},
            "head": {"ref": "x"}, **extra}


def run(conclusion, event="pull_request"):
    return {"conclusion": conclusion, "status": "completed" if conclusion else "in_progress",
            "event": event}


def runs_address(repo, workflow):
    return f"repos/{repo}/actions/workflows/{workflow}/runs?created=>={WEEK_AGO}&per_page=100"


REVIEW = (
    "Text.\n\n<!-- kitden-sdlc:review claude=0 luna=0 both=0 -->"
)
SHA = "12a94bced323dc0f70d6e4b39f7d46c04282deaa"
CHECKS = f"repos/{REPO}/commits/main/check-runs?per_page=100"
HEAD_RUNS = f"repos/{REPO}/actions/runs?head_sha={SHA}&per_page=100"


def check_run(name, run_id, conclusion="success", started="2026-11-13T21:46:00Z"):
    """A check run as GitHub gives it, with the fields the desk reads."""
    url = f"https://github.com/{REPO}/actions/runs/{run_id}/job/132189677309"
    return {"id": run_id * 10, "name": name, "status": "completed", "conclusion": conclusion,
            "started_at": started, "head_sha": SHA, "details_url": url, "html_url": url,
            "app": {"slug": "github-actions"}}
# What GitHub answers, by address. The pulls lists are kept apart: see FakeApi.list_pulls.
ANSWERS = {
    f"repos/{REPO}/issues?state=all&per_page=100": [
        issue(1, "a bug", ("bug",), login="someone"),
        {**issue(2, "a pull request"), "pull_request": {"url": "u"}},
        issue(3, "found"),
    ],
    f"repos/{REPO}/pulls?state=open&per_page=100": [
        pull(5, ago(200), created=ago(210)),  # open and left alone for months
        pull(6, ago(2), title="open now"),
    ],
    CHECKS: {
        "total_count": 2,
        "check_runs": [check_run("prepare / agent", 43513690445, "failure"),
                       check_run("build (ubuntu-latest)", 43513577178)],
    },
    HEAD_RUNS: {"total_count": 2, "workflow_runs": [
        {"id": 43513690445, "name": "Release prep", "event": "workflow_dispatch",
         "head_sha": SHA},
        {"id": 43513577178, "name": "Checks and release", "event": "push", "head_sha": SHA},
    ]},
    f"repos/{REPO}/branches/main": {
        "name": "main",
        "protection": {"required_status_checks": {"contexts": ["build (ubuntu-latest)"]}},
    },
    f"repos/{REPO}/rules/branches/main": [
        {"type": "deletion"},
        {"type": "required_status_checks", "parameters": {"required_status_checks": [
            {"context": "build (ubuntu-latest)", "integration_id": 15368}]}},
    ],
    f"repos/{REPO}": {"stargazers_count": 12},
    runs_address(REPO, "agents-review.yml"): {"workflow_runs": [
        run("success"), run("failure"), run("success"),
        run("skipped"), run("cancelled"), run(None),
    ]},
    runs_address(SDLC, "watch.yml"): {"workflow_runs": [
        *[run("success", "schedule") for _ in range(6)], run("failure", "schedule"),
        run("success", "workflow_dispatch"), run("skipped", "schedule"), run(None, "schedule"),
    ]},
    runs_address(REPO, "release-prep.yml"): {"workflow_runs": []},
}
LISTED = [  # every state, newest update first, as count_reviews.list_pulls gives them
    pull(6, ago(2), created=ago(3), title="open now"),
    pull(7, ago(10), state="closed", merged_at=ago(10), created=ago(12)),
    pull(8, ago(95), state="closed", created=ago(100)),
    pull(5, ago(200), created=ago(210)),
]
SILENT = "Text.\n\n<!-- kitden-sdlc:review claude=x luna=x both=0 -->"
COMMENTS = {7: [{"id": 70, "user": {"login": "github-actions[bot]"}, "body": REVIEW,
                 "updated_at": ago(10)}],
            6: [{"id": 60, "user": {"login": "github-actions[bot]"}, "body": SILENT,
                 "updated_at": ago(2)}]}


class FakeApi:
    """The gh calls, answered from `answers` by address. An exception is raised; an address
    nobody listed fails like a 404."""

    def __init__(self, answers, listed=LISTED):
        self.answers, self.listed, self.asked = answers, listed, []

    def get(self, address):
        self.asked.append(address)
        answer = self.answers.get(address, CalledProcessError(1, "gh"))
        if isinstance(answer, Exception):
            raise answer
        return answer

    def pages(self, address, key=None):
        return desk_gather.page_items(self.get(address), key)  # the shape check is the real one

    def list_pulls(self, repo):
        self.asked.append(f"list_pulls {repo}")
        yield from self.listed

    def list_issue_comments(self, repo, pr):
        self.asked.append(f"comments {pr}")
        return COMMENTS.get(pr, [])

    def list_issue_comment_reactions(self, repo, comment_id):
        return []


def read(answers=ANSWERS, log=None, fetch=lambda url: DOWNLOADS, **changes):
    return gather(FakeApi({**answers, **changes}), REPO, ROSTER, NOW, log, fetch=fetch)


def failing(address):
    return {address: CalledProcessError(1, "gh")}


def test_gather_reads_every_fact(tmp_path):
    log = tmp_path / "log.jsonl"
    log.write_text('{"date": "2026-11-15"}\nnot json\n\n{"date": "2026-11-16"}\n[1]\n')
    facts = read(log=log)
    assert [i["number"] for i in facts.issues] == [1, 3] and facts.issues[0]["title"] == "a bug"
    assert facts.required == ["build (ubuntu-latest)"] and facts.stars == 12
    assert [c["name"] for c in facts.checks] == ["prepare / agent", "build (ubuntu-latest)"]
    assert facts.runs == {"claude": 3, "luna": 3, "watcher": 7, "release-prep": 0}
    assert facts.failed == {"claude": 1, "luna": 1, "watcher": 1, "release-prep": 0}
    assert facts.watch_log[-1]["date"] == "2026-11-16" and len(facts.watch_log) == 2
    assert facts.downloads == 340
    assert [r.pr for r in facts.reviews] == [7]
    assert [r.pr for r in facts.silent] == [6]  # neither reviewer answered there


def test_pulls_hold_every_open_one_and_the_closed_ones_of_90_days():
    facts = read()
    assert sorted(p["number"] for p in facts.pulls) == [5, 6, 7]
    assert [p["number"] for p in facts.pulls].count(6) == 1  # in both lists, held once
    assert next(p for p in facts.pulls if p["number"] == 5)["state"] == "open"


def test_a_closed_pull_in_the_list_is_not_added_twice_nor_an_old_closed_one():
    facts = read()
    assert 8 not in [p["number"] for p in facts.pulls]


def test_both_reviewers_read_their_shared_workflow_once():
    api = FakeApi(ANSWERS)
    gather(api, REPO, ROSTER, NOW, None, fetch=lambda url: DOWNLOADS)
    assert api.asked.count(runs_address(REPO, "agents-review.yml")) == 1


def test_only_scheduled_runs_of_the_watcher_count():
    assert read().runs["watcher"] == 7  # not the one started by hand


def test_a_workflow_that_cannot_be_read_gives_none_for_its_agents_only(capsys):
    facts = read(**failing(runs_address(REPO, "agents-review.yml")))
    assert facts.runs == {"claude": None, "luna": None, "watcher": 7, "release-prep": 0}
    assert facts.failed == {"claude": None, "luna": None, "watcher": 1, "release-prep": 0}
    assert "::warning::" in capsys.readouterr().out


CLASSIC = f"repos/{REPO}/branches/main"
RULES = f"repos/{REPO}/rules/branches/main"


def classic(*names):
    return {"name": "main", "protection": {"required_status_checks": {"contexts": list(names)}}}


def ruleset(*names):
    checks = [{"context": name, "integration_id": 1} for name in names]
    return [{"type": "pull_request"},
            {"type": "required_status_checks", "parameters": {"required_status_checks": checks}}]


def test_required_from_branch_protection_alone():
    facts = read(**{CLASSIC: classic("b", "a"), **failing(RULES)})
    assert facts.required == ["a", "b"] and facts.required_partial is True


def test_required_from_a_ruleset_alone():
    assert read(**{CLASSIC: classic(), RULES: ruleset("b (ubuntu)", "a")}).required == [
        "a", "b (ubuntu)"]
    assert read(**{CLASSIC: {"name": "main"}, RULES: ruleset("x")}).required == ["x"]


def test_required_read_whole_is_not_partial():
    assert read().required_partial is False
    assert read(**{CLASSIC: classic("a"), RULES: []}).required_partial is False


def test_required_is_the_union_of_both_in_a_stable_order():
    both = read(**{CLASSIC: classic("b", "a"), RULES: ruleset("c", "a")}).required
    assert both == ["a", "b", "c"]
    other = read(**{CLASSIC: classic("a", "c"), RULES: ruleset("b", "a")}).required
    assert other == both


def test_required_is_empty_when_both_read_and_none_is_required():
    # What GitHub gives for a branch without protection (kitden-sdlc's `numbers`, 2026-11-13).
    bare = {"protected": False, "protection": {"enabled": False, "required_status_checks": {
        "checks": [], "contexts": [], "enforcement_level": "off"}}}
    assert read(**{CLASSIC: {"name": "main"}, RULES: []}).required == []
    facts = read(**{CLASSIC: bare, RULES: [{"type": "deletion"}]})
    assert facts.required == [] and facts.required_partial is False
    for missing in ({"protection": {}}, {"protection": {"required_status_checks": {}}}):
        facts = read(**{CLASSIC: missing, RULES: []})
        assert facts.required == [] and facts.required_partial is False


@pytest.mark.parametrize("answer", [
    {"protection": None}, {"protection": []}, {"protection": 0}, {"protection": ""},
    {"protection": {"required_status_checks": None}},
    {"protection": {"required_status_checks": []}},
    {"protection": {"required_status_checks": {"contexts": None}}},
    {"protection": {"required_status_checks": {"contexts": ""}}},
    {"protection": {"required_status_checks": {"contexts": {}}}},
])
def test_branch_protection_of_a_wrong_shape_is_a_failed_read(answer, capsys):
    facts = read(**{CLASSIC: answer, RULES: ruleset("x")})
    assert facts.required == ["x"] and facts.required_partial is True
    assert "required (branch protection)" in capsys.readouterr().out


def test_required_uses_what_was_read_when_one_read_fails(capsys):
    facts = read(**{CLASSIC: classic("a"), **failing(RULES)})
    assert facts.required == ["a"] and facts.required_partial is True
    assert "::warning::" in capsys.readouterr().out
    facts = read(**{**failing(CLASSIC), RULES: ruleset("b")})
    assert facts.required == ["b"] and facts.required_partial is True
    assert "::warning::" in capsys.readouterr().out


def test_required_is_none_when_both_reads_fail(capsys):
    facts = read(**failing(CLASSIC), **failing(RULES))
    assert facts.required is None and facts.required_partial is False
    out = capsys.readouterr().out
    assert out.count("::warning::") >= 2 and "required" in out


def test_a_ruleset_of_an_odd_shape_is_a_failed_read():
    odd = [{"type": "required_status_checks", "parameters": {"required_status_checks": [{}]}}]
    facts = read(**{CLASSIC: classic("a"), RULES: odd})
    assert facts.required == ["a"] and facts.required_partial is True
    facts = read(**{CLASSIC: classic("a"), RULES: {"message": "x"}})
    assert facts.required == ["a"] and facts.required_partial is True


def test_one_failed_read_leaves_one_field_empty(capsys):
    api = FakeApi({**ANSWERS, f"repos/{REPO}/commits/main/check-runs?per_page=100":
                   CalledProcessError(1, "gh")})

    def down(url):
        raise OSError("no network")

    facts = gather(api, REPO, ROSTER, NOW, None, fetch=down)
    assert facts.checks is None and facts.downloads is None and facts.watch_log is None
    assert facts.issues is not None and "::warning::" in capsys.readouterr().out


def test_each_failed_read_names_its_field_and_nothing_else(capsys):
    secret = "ghp_" + "x" * 20
    broken = CalledProcessError(1, ["gh", secret], stderr=secret)
    api = FakeApi({**ANSWERS, f"repos/{REPO}": broken})
    facts = gather(api, REPO, ROSTER, NOW, None, fetch=lambda url: DOWNLOADS)
    out = capsys.readouterr().out
    assert facts.stars is None and secret not in out
    warnings = [line for line in out.splitlines() if line.startswith("::warning::")]
    assert any("stars" in line for line in warnings)
    assert all("\n" not in line for line in warnings)


@pytest.mark.parametrize("field, address", [
    ("issues", f"repos/{REPO}/issues?state=all&per_page=100"),
    ("stars", f"repos/{REPO}"),
])
def test_a_failed_read_leaves_the_others_running(field, address):
    facts = read(**failing(address))
    assert getattr(facts, field) is None
    others = {"issues", "checks", "required", "stars", "pulls", "reviews", "downloads"} - {field}
    assert all(getattr(facts, name) is not None for name in others)


def test_pulls_are_none_when_the_open_ones_cannot_be_read():
    facts = read(**failing(f"repos/{REPO}/pulls?state=open&per_page=100"))
    assert facts.pulls is None and facts.reviews is not None


def test_pulls_and_reviews_are_none_when_the_list_fails():
    api = FakeApi(ANSWERS)

    def broken(repo):
        raise CalledProcessError(1, "gh")
        yield  # pragma: no cover

    api.list_pulls = broken
    facts = gather(api, REPO, ROSTER, NOW, None, fetch=lambda url: DOWNLOADS)
    assert facts.pulls is None and facts.reviews is None and facts.issues is not None


def test_a_wrong_shape_is_a_failed_read_not_a_crash():
    facts = read(**{f"repos/{REPO}": [], CLASSIC: [], RULES: {}})
    assert facts.stars is None and facts.required is None


def test_a_missing_watch_log_file_is_none(tmp_path, capsys):
    assert read(log=tmp_path / "nope.jsonl").watch_log is None
    assert "::warning::" in capsys.readouterr().out


def test_an_empty_watch_log_is_read_and_has_no_lines(tmp_path):
    log = tmp_path / "log.jsonl"
    log.write_text("")
    assert read(log=log).watch_log == []


def test_no_watch_log_path_is_none_without_a_warning(capsys):
    assert read().watch_log is None
    assert "watch_log" not in capsys.readouterr().out


# --- gh ---


def test_pages_joins_the_pages_gh_prints_one_after_another(monkeypatch):
    api = desk_gather.GhDeskApi()
    asked = []

    def run(*args, token=None):
        asked.append(args)
        return '[{"a": 1}, {"a": 2}]\n[{"a": 3}]\n'

    monkeypatch.setattr(api, "_run", run)
    assert api.pages("repos/o/r/issues") == [{"a": 1}, {"a": 2}, {"a": 3}]
    assert asked == [("repos/o/r/issues", "--paginate")]

    pages = '{"check_runs": [{"a": 1}]}\n{"check_runs": [{"a": 2}]}'
    monkeypatch.setattr(api, "_run", lambda *args, token=None: pages)
    assert api.pages("repos/o/r/runs", "check_runs") == [{"a": 1}, {"a": 2}]
    monkeypatch.setattr(api, "_run", lambda *args, token=None: '{"stargazers_count": 4}')
    assert api.get("repos/o/r") == {"stargazers_count": 4}


@pytest.mark.parametrize("text, key", [
    ("{}", None), ('{"a": 1}', None), ("[]", "check_runs"), ("", None), ("  \n", "check_runs"),
    ('{"check_runs": {"a": 1}}', "check_runs"), ('{"other": []}', "check_runs"),
])
def test_pages_refuses_an_answer_of_the_wrong_shape_or_none(monkeypatch, text, key):
    api = desk_gather.GhDeskApi()
    monkeypatch.setattr(api, "_run", lambda *args, token=None: text)
    with pytest.raises((TypeError, ValueError, KeyError)):
        api.pages("repos/o/r/x", key)


def test_the_fake_refuses_the_same_shapes():
    for answer, key in [({}, None), ([], "check_runs"), ({"check_runs": {"a": 1}}, "check_runs")]:
        with pytest.raises((TypeError, KeyError)):
            FakeApi({"x": answer}).pages("x", key)


def test_a_wrong_shape_is_none_for_every_read_that_pages():
    facts = read(**{
        f"repos/{REPO}/issues?state=all&per_page=100": {},
        f"repos/{REPO}/pulls?state=open&per_page=100": {},
        f"repos/{REPO}/commits/main/check-runs?per_page=100": [],
        runs_address(REPO, "agents-review.yml"): [],
    })
    assert facts.issues is None and facts.pulls is None and facts.checks is None
    assert facts.runs["claude"] is None and facts.runs["watcher"] == 7


# --- a failed read of any kind leaves the others running ---


class Broken(FakeApi):
    """An api whose every call fails with `error`."""

    def __init__(self, error):
        super().__init__({})
        self.error = error

    def get(self, address):
        raise self.error

    def list_pulls(self, repo):
        raise self.error
        yield  # pragma: no cover


@pytest.mark.parametrize("error", [
    http.client.IncompleteRead(b"x"), http.client.BadStatusLine("x"),
    http.client.LineTooLong("x"), RecursionError(), OverflowError(), ZeroDivisionError(),
    UnicodeDecodeError("utf-8", b"", 0, 1, "x"),
])
def test_an_error_of_any_kind_is_a_failed_read_not_a_crash(error, tmp_path, capsys):
    def fetch(url):
        raise error

    (tmp_path / "log.jsonl").write_text("{}\n")
    facts = gather(Broken(error), REPO, ROSTER, NOW, tmp_path / "log.jsonl", fetch=fetch)
    assert facts.downloads is None and facts.issues is None and facts.pulls is None
    assert facts.reviews is None and facts.checks is None and facts.stars is None
    assert facts.required is None and set(facts.runs.values()) == {None}
    assert facts.watch_log == [{}]  # the one read that does not need the network still ran
    assert capsys.readouterr().out.count("::warning::") >= 9


def test_a_truncated_download_leaves_the_other_facts(capsys):
    def truncated(url):
        raise http.client.IncompleteRead(b"{")

    facts = read(fetch=truncated)
    assert facts.downloads is None and facts.stars == 12 and facts.issues is not None
    assert "downloads" in capsys.readouterr().out


# --- downloads ---


def test_downloads_come_from_the_fixed_address_with_a_short_timeout(monkeypatch):
    seen = {}

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return DOWNLOADS.encode()

    def urlopen(request, timeout):
        seen["url"], seen["timeout"] = request.full_url, timeout
        seen["headers"] = dict(request.header_items())
        return Response()

    monkeypatch.setattr(desk_gather.urllib.request, "urlopen", urlopen)
    monkeypatch.setenv("GITHUB_TOKEN", "secret-token")
    assert desk_gather.fetch_url("https://pypistats.org/api/packages/kitden/recent") == DOWNLOADS
    assert seen["timeout"] == 10 and "secret-token" not in str(seen["headers"])
    assert fetch_downloads(lambda url: seen.setdefault("asked", url) and DOWNLOADS) == 340
    assert seen["asked"] == "https://pypistats.org/api/packages/kitden/recent"


@pytest.mark.parametrize("text", [
    "", "not json", "[]", '{"data": {}}', '{"data": {"last_month": "340"}}',
    '{"data": {"last_month": true}}', '{"data": {"last_month": -1}}',
])
def test_downloads_that_do_not_read_as_a_number_are_none(text):
    assert read(fetch=lambda url: text).downloads is None


# --- the command ---


def test_gather_keeps_the_repository_it_read():
    assert read().repo == REPO


def test_main_writes_the_repository_it_was_given(tmp_path):
    other = "someone/else"
    answers = {k.replace(REPO, other): v for k, v in ANSWERS.items()}
    argv = ["--repo", other, "--roster", str(ROOT / "config/agents.json"), "--out", str(tmp_path)]
    api = FakeApi(answers, listed=[])
    assert main(argv, api=api, now=NOW) == 0
    desk = json.loads((tmp_path / "desk.json").read_text())
    assert desk["repo"] == other and desk["lights"][0]["state"] == "green"


def test_main_writes_desk_json(tmp_path):
    argv = ["--repo", REPO, "--roster", str(ROOT / "config/agents.json"), "--out", str(tmp_path)]
    assert main(argv, api=FakeApi(ANSWERS), now=NOW) == 0
    text = (tmp_path / "desk.json").read_text()
    desk = json.loads(text)
    assert desk["version"] == 1 and desk["lights"][1]["state"] == "grey"  # no watcher log given
    assert text.endswith("}\n") and text.startswith('{\n  "version"')  # two-space indent


def test_main_exits_zero_and_writes_grey_when_every_read_fails(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(desk_gather, "fetch_url", lambda url: (_ for _ in ()).throw(OSError()))
    argv = ["--roster", str(ROOT / "config/agents.json"), "--out", str(tmp_path / "new" / "out")]
    assert main(argv, api=FakeApi({}, listed=[]), now=NOW) == 0
    desk = json.loads((tmp_path / "new/out/desk.json").read_text())
    assert [light["state"] for light in desk["lights"]] == ["grey"] * 5
    assert desk["overall"] == "grey" and "::warning::" in capsys.readouterr().out


def test_main_exits_non_zero_when_it_cannot_write(tmp_path, capsys):
    blocker = tmp_path / "file"
    blocker.write_text("x")
    argv = ["--roster", str(ROOT / "config/agents.json"), "--out", str(blocker)]
    assert main(argv, api=FakeApi(ANSWERS), now=NOW) != 0
    assert "::error::" in capsys.readouterr().out


def test_main_reads_the_watch_log_it_is_given(tmp_path):
    log = tmp_path / "log.jsonl"
    log.write_text(json.dumps({"date": "2026-11-16", "pieces": 0}) + "\n")
    argv = ["--roster", str(ROOT / "config/agents.json"), "--watch-log", str(log),
            "--out", str(tmp_path)]
    assert main(argv, api=FakeApi(ANSWERS), now=NOW) == 0
    desk = json.loads((tmp_path / "desk.json").read_text())
    assert desk["lights"][1]["state"] == "green"


# --- each check run gets the event of its workflow run ---


def test_each_check_run_gets_the_event_of_its_workflow_run():
    facts = read()
    assert [(c["name"], c["event"]) for c in facts.checks] == [
        ("prepare / agent", "workflow_dispatch"), ("build (ubuntu-latest)", "push")]


def test_runs_of_the_commit_are_read_once():
    api = FakeApi(ANSWERS)
    gather(api, REPO, ROSTER, NOW, None, fetch=lambda url: DOWNLOADS)
    assert api.asked.count(HEAD_RUNS) == 1


def test_a_failed_run_started_by_hand_leaves_works_green(tmp_path):
    argv = ["--roster", str(ROOT / "config/agents.json"), "--out", str(tmp_path)]
    assert main(argv, api=FakeApi(ANSWERS), now=NOW) == 0
    works = json.loads((tmp_path / "desk.json").read_text())["lights"][0]
    assert works["state"] == "green", works


def test_when_the_runs_cannot_be_read_nothing_is_left_out(capsys):
    facts = read(**failing(HEAD_RUNS))
    assert [c["event"] for c in facts.checks] == [None, None]
    assert "::warning::" in capsys.readouterr().out
    facts = read(**{HEAD_RUNS: {"workflow_runs": [{"id": "x", "event": 1}]}})
    assert [c["event"] for c in facts.checks] == [None, None]


def test_a_check_not_from_actions_has_no_known_event():
    other = {**check_run("ci/external", 1), "details_url": "https://ci.example/build/1"}
    facts = read(**{CHECKS: {"check_runs": [other]}})
    assert facts.checks[0]["event"] is None


def test_no_check_run_reads_no_workflow_runs():
    api = FakeApi({**ANSWERS, CHECKS: {"check_runs": []}})
    facts = gather(api, REPO, ROSTER, NOW, None, fetch=lambda url: DOWNLOADS)
    assert facts.checks == [] and HEAD_RUNS not in api.asked


# --- the review numbers come from the same read ---


def test_main_writes_the_numbers_from_the_reviews_it_read_once(tmp_path):
    api = FakeApi(ANSWERS)
    argv = ["--roster", str(ROOT / "config/agents.json"), "--out", str(tmp_path / "desk")]
    assert main(argv, api=api, now=NOW) == 0
    assert api.asked.count("comments 7") == 1  # one read of the reviews
    alone = tmp_path / "alone"
    alone.mkdir()
    assert count_reviews.main(["--out", str(alone)], api=FakeApi(ANSWERS), now=NOW) == 0
    for name in ("numbers.md", "numbers.json"):
        assert (tmp_path / "desk" / name).read_text() == (alone / name).read_text(), name
    assert json.loads((tmp_path / "desk/numbers.json").read_text())["reviews"]["prs"] == 1


def test_numbers_are_left_as_they_were_when_the_reviews_cannot_be_read(tmp_path, capsys):
    (tmp_path / "numbers.md").write_text("before\n")
    (tmp_path / "numbers.json").write_text("{}\n")
    api = FakeApi(ANSWERS)

    def broken(repo):
        raise CalledProcessError(1, "gh")
        yield  # pragma: no cover

    api.list_pulls = broken
    argv = ["--roster", str(ROOT / "config/agents.json"), "--out", str(tmp_path)]
    assert main(argv, api=api, now=NOW) == 0
    assert (tmp_path / "numbers.md").read_text() == "before\n"
    assert (tmp_path / "numbers.json").read_text() == "{}\n"
    assert "::warning::desk: could not read reviews" in capsys.readouterr().out
    assert (tmp_path / "desk.json").exists()


def test_the_numbers_leave_out_a_comment_where_neither_answered(tmp_path):
    argv = ["--roster", str(ROOT / "config/agents.json"), "--out", str(tmp_path)]
    assert main(argv, api=FakeApi(ANSWERS), now=NOW) == 0
    assert json.loads((tmp_path / "numbers.json").read_text())["reviews"]["prs"] == 1
    week = json.loads((tmp_path / "desk.json").read_text())["week"]
    assert (week[0]["failed"], week[0]["no_answer"]) == (1, 1)


def test_silent_and_failed_are_none_when_not_read():
    api = FakeApi(ANSWERS)

    def broken(repo):
        raise CalledProcessError(1, "gh")
        yield  # pragma: no cover

    api.list_pulls = broken
    facts = gather(api, REPO, ROSTER, NOW, None, fetch=lambda url: DOWNLOADS)
    assert facts.reviews is None and facts.silent is None
