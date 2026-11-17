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


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    """No test here reaches the network: main's own fetch_url finds it down."""
    def down(request, timeout):
        raise OSError("the tests are offline")

    monkeypatch.setattr(desk_gather.urllib.request, "urlopen", down)


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


def night_runs(workflow):
    query = "branch=main&event=schedule&status=completed&per_page=1"
    return f"repos/{REPO}/actions/workflows/{workflow}/runs?{query}"


def night_jobs(run_id):
    return f"repos/{REPO}/actions/runs/{run_id}/jobs?filter=latest&per_page=100"


def night_run(run_id, name):
    """A workflow run as GitHub gives it, with the fields the desk reads."""
    return {"id": run_id, "name": name, "event": "schedule", "head_branch": "main",
            "status": "completed", "conclusion": "success", "created_at": "2026-11-16T02:37:00Z",
            "html_url": f"https://github.com/{REPO}/actions/runs/{run_id}"}


def night_job(name, conclusion="success"):
    return {"name": name, "status": "completed", "conclusion": conclusion,
            "html_url": f"https://github.com/{REPO}/actions/runs/7/job/1",
            "steps": [{"name": "Run uv run pytest -q", "conclusion": conclusion}]}


# What tests/set-aside.txt holds on Kitden's main today (2026-11-16): only its two comments.
SET_ASIDE = ("# One test per line, as pytest names it, then two spaces, #, the date and the "
             "reason.\n# Blank lines and lines that start with # are comments. See "
             "docs/development.md.\n")


def fetched(url):
    return SET_ASIDE if "set-aside" in url else DOWNLOADS


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
    night_runs("nightly.yml"): {"total_count": 1, "workflow_runs": [night_run(7, "Nightly tests")]},
    night_jobs(7): {"total_count": 3, "jobs": [night_job("systems (ubuntu-latest, 3.13)"),
                                               night_job("clients"), night_job("browser")]},
    night_runs("latest-deps.yml"): {"total_count": 1,
                                    "workflow_runs": [night_run(8, "Latest dependencies")]},
    night_jobs(8): {"total_count": 1, "jobs": [night_job("test")]},
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

    def text(self, address):
        return json.dumps(self.get(address))

    def list_pulls(self, repo):
        self.asked.append(f"list_pulls {repo}")
        yield from self.listed

    def list_issue_comments(self, repo, pr):
        self.asked.append(f"comments {pr}")
        return COMMENTS.get(pr, [])

    def list_issue_comment_reactions(self, repo, comment_id):
        return []


def read(answers=ANSWERS, log=None, fetch=fetched, **changes):
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
    others = {"issues", "checks", "required", "stars", "pulls", "reviews", "downloads",
              "nightly", "set_aside"} - {field}
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


# --- the nightly runs ---


def test_nightly_holds_the_newest_finished_scheduled_run_and_its_jobs():
    night = read().nightly
    assert [entry["workflow"] for entry in night] == ["nightly.yml", "latest-deps.yml"]
    assert night[0]["name"] == "Nightly tests" and night[0]["run"]["id"] == 7
    assert [job["name"] for job in night[0]["jobs"]] == [
        "systems (ubuntu-latest, 3.13)", "clients", "browser"]
    assert night[1]["run"]["id"] == 8 and [job["name"] for job in night[1]["jobs"]] == ["test"]


def test_the_newest_run_is_one_call_not_every_page():
    class Paged(FakeApi):
        def pages(self, address, key=None):
            self.asked.append(f"paged {address}")
            return super().pages(address, key)

    api = Paged(ANSWERS)
    gather(api, REPO, ROSTER, NOW, None, fetch=fetched)
    assert f"paged {night_runs('nightly.yml')}" not in api.asked  # per_page=1 over every run
    assert f"paged {night_jobs(7)}" in api.asked  # a matrix can have more than 100 jobs


def test_a_workflow_with_no_scheduled_run_has_no_run_and_no_warning(capsys):
    night = read(**{night_runs("nightly.yml"): {"workflow_runs": []}}).nightly
    assert (night[0]["run"], night[0]["jobs"]) == (None, None)
    assert "nightly" not in capsys.readouterr().out


def test_a_workflow_that_cannot_be_read_warns_and_leaves_the_other(capsys):
    night = read(**failing(night_runs("nightly.yml"))).nightly
    assert night[0]["run"] is None and night[1]["run"] is not None
    assert "::warning::desk: could not read nightly (nightly.yml)" in capsys.readouterr().out


@pytest.mark.parametrize("changes", [
    failing(night_jobs(7)),
    {night_jobs(7): {"jobs": {}}},
    {night_jobs(7): {"jobs": ["x"]}},
    {night_runs("nightly.yml"): {"workflow_runs": {}}},
    {night_runs("nightly.yml"): {"workflow_runs": [{"id": "7"}]}},
    {night_runs("nightly.yml"): []},
])
def test_a_run_or_jobs_of_another_shape_is_a_failed_read(changes, capsys):
    night = read(**changes).nightly
    assert night[0] == {"workflow": "nightly.yml", "name": None, "run": None, "jobs": None}
    assert night[1]["run"]["id"] == 8
    assert "::warning::desk: could not read nightly (nightly.yml)" in capsys.readouterr().out


def test_set_aside_counts_the_tests_not_the_comments():
    text = "# why\n\ntests/unit/test_a.py::test_x  # 2026-11-20 gave up waiting\n"
    assert read(fetch=lambda url: text if "set-aside" in url else DOWNLOADS).set_aside == 1


def test_set_aside_of_today_holds_no_test(capsys):
    asked = []
    assert read(fetch=lambda url: asked.append(url) or fetched(url)).set_aside == 0
    assert f"https://raw.githubusercontent.com/{REPO}/main/tests/set-aside.txt" in asked
    assert "set_aside" not in capsys.readouterr().out


def test_a_set_aside_file_of_another_shape_is_a_failed_read(capsys):
    assert read(fetch=lambda url: "<html>" if "set-aside" in url else DOWNLOADS).set_aside is None
    assert "::warning::desk: could not read set_aside" in capsys.readouterr().out


def test_a_set_aside_file_that_cannot_be_fetched_is_a_failed_read(capsys):
    def fetch(url):
        if "set-aside" in url:
            raise OSError("404")
        return DOWNLOADS

    facts = read(fetch=fetch)
    assert facts.set_aside is None and facts.downloads == 340
    assert "::warning::desk: could not read set_aside" in capsys.readouterr().out


def test_yesterdays_rows_come_from_the_desk_file_already_in_out(tmp_path):
    (tmp_path / "desk.json").write_text(json.dumps({"nightly": [{"part": "systems"}]}))
    assert desk_gather.before(tmp_path) == [{"part": "systems"}]
    assert desk_gather.before(tmp_path / "none") is None


def test_a_desk_file_without_rows_has_none_and_a_broken_one_warns(tmp_path, capsys):
    (tmp_path / "desk.json").write_text(json.dumps({"version": 1, "lights": []}))
    assert desk_gather.before(tmp_path) is None  # yesterday's desk did not read the nights yet
    (tmp_path / "desk.json").write_text(json.dumps({"nightly": None}))
    assert desk_gather.before(tmp_path) is None
    assert capsys.readouterr().out == ""
    for broken in ("{", json.dumps({"nightly": {}}), json.dumps({"nightly": ["x"]}), "[]"):
        (tmp_path / "desk.json").write_text(broken)
        assert desk_gather.before(tmp_path) is None
        assert "::warning::desk: could not read before" in capsys.readouterr().out


def test_main_reads_yesterdays_rows_before_it_writes_the_new_desk(tmp_path, monkeypatch):
    (tmp_path / "desk.json").write_text(json.dumps({"nightly": [{"part": "browser"}]}))
    seen = []
    real = desk_gather.build
    monkeypatch.setattr(desk_gather, "build",
                        lambda facts, *args: seen.append(facts.before) or real(facts, *args))
    argv = ["--roster", str(ROOT / "config/agents.json"), "--out", str(tmp_path)]
    assert main(argv, api=FakeApi(ANSWERS), now=NOW) == 0
    assert seen == [[{"part": "browser"}]]
    assert json.loads((tmp_path / "desk.json").read_text())["nightly"][2]["part"] == "browser"


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


# Task 17: the desk reads the workflow map against the workflow files.

TAP = "konstantinstarovoytov/homebrew-tap"
JOBS = "jobs:\n  a:\n    runs-on: ubuntu-latest\n"  # what makes a raw text a workflow file


def contents(slug):
    return f"repos/{slug}/contents/.github/workflows?ref=main"


def map_answers():
    """The lists of Kitden's and the tap's workflow files, as the contents API gives them."""
    from map_text import map_ids
    ids = map_ids((ROOT / "docs/map/index.html").read_text())
    return {contents(slug): [{"name": file, "type": "file"}
                             for repo, file in sorted(ids.values()) if repo == letter]
            for letter, slug in (("k", REPO), ("t", TAP))}


def map_fetch(changed=None):
    """Kitden's and the tap's raw workflow files, each saying what the map says; `changed`
    gives another text for some of them."""
    from tests.test_map_text import _good

    def fetch(url):
        if url.startswith("https://raw.githubusercontent.com/") and "/.github/workflows/" in url:
            repo = "k" if f"/{REPO}/" in url else "t"
            file = url.rsplit("/", 1)[1]
            return (changed or {}).get(file) or _good(repo, file) + JOBS
        return fetched(url)

    return fetch


def read_map(fetch=None, answers=None, root=ROOT):
    api = FakeApi({**ANSWERS, **map_answers(), **(answers or {})})
    return gather(api, REPO, ROSTER, NOW, None, fetch=fetch or map_fetch(), map_root=root), api


def test_the_map_that_says_what_the_files_say_is_up_to_date(capsys):
    facts, api = read_map()
    assert facts.map_stale == []
    assert contents(REPO) in api.asked and contents(TAP) in api.asked  # through gh, with a token
    assert "::warning::" not in capsys.readouterr().out


def test_each_place_the_map_differs_from_a_file_is_one_line():
    from map_text import read_block
    shown = read_block((ROOT / "docs/map/index.html").read_text())["k-release"]
    renamed = f"# What: {shown['what']}\n# Why: {shown['why']}\nname: Another name\n{JOBS}"
    facts, _ = read_map(map_fetch({"release.yml": renamed}))
    assert facts.map_stale == [
        f'k-release: name is "{shown["name"]}", the file says "Another name"']


def test_a_new_workflow_file_in_kitden_is_a_place_the_map_is_out_of_date():
    listed = map_answers()[contents(REPO)] + [{"name": "new.yml", "type": "file"}]
    facts, _ = read_map(answers={contents(REPO): listed})
    assert facts.map_stale == ["kitden: new.yml is not on the map"]


def test_a_raw_file_that_cannot_be_read_is_null_never_up_to_date(capsys):
    def fetch(url):
        if url.endswith("/release.yml"):
            raise OSError("offline")
        return map_fetch()(url)

    facts, _ = read_map(fetch)
    assert facts.map_stale is None
    out = capsys.readouterr().out
    assert out.count("::warning::") == 1 and "::warning::desk: could not read map" in out
    assert facts.downloads == 340  # the other reads still ran


def test_a_list_that_cannot_be_read_is_null_never_up_to_date(capsys):
    facts, _ = read_map(answers=failing(contents(TAP)))
    assert facts.map_stale is None
    assert "::warning::desk: could not read map" in capsys.readouterr().out


def test_a_list_of_another_shape_is_null_never_up_to_date(capsys):
    facts, _ = read_map(answers={contents(REPO): {"message": "Not Found"}})
    assert facts.map_stale is None
    assert "::warning::desk: could not read map" in capsys.readouterr().out


def test_a_map_file_that_is_not_there_is_null(tmp_path, capsys):
    facts, _ = read_map(root=tmp_path)
    assert facts.map_stale is None
    assert "::warning::desk: could not read map" in capsys.readouterr().out


def test_without_a_root_the_map_is_not_read():
    api = FakeApi({**ANSWERS, **map_answers()})
    facts = gather(api, REPO, ROSTER, NOW, None, fetch=fetched)
    assert facts.map_stale is None and not any("contents" in a for a in api.asked)


def test_main_reads_the_map_of_this_checkout_and_writes_it_to_the_desk(tmp_path, monkeypatch):
    monkeypatch.setattr(desk_gather, "fetch_url", map_fetch())
    argv = ["--roster", str(ROOT / "config/agents.json"), "--out", str(tmp_path)]
    assert main(argv, api=FakeApi({**ANSWERS, **map_answers()}), now=NOW) == 0
    assert json.loads((tmp_path / "desk.json").read_text())["map"] == {"stale": []}


def test_the_desks_api_reads_a_text_through_gh(monkeypatch):
    seen = []
    monkeypatch.setattr(desk_gather.GhDeskApi, "_run",
                        lambda self, *args: seen.append(args) or "[]")
    assert desk_gather.GhDeskApi().text(contents(REPO)) == "[]"
    assert seen == [(contents(REPO),)]


def test_a_raw_answer_that_is_not_a_workflow_is_null_not_three_places(capsys):
    facts, _ = read_map(map_fetch({"release.yml": "<html>Something went wrong</html>"}))
    assert facts.map_stale is None
    assert "::warning::desk: could not read map" in capsys.readouterr().out


def test_the_map_read_stops_at_its_first_failure():
    asked = []

    def offline(url):
        if "/.github/workflows/" in url:
            asked.append(url)
            raise OSError("offline")
        return fetched(url)

    facts, _ = read_map(offline)
    assert facts.map_stale is None and len(asked) == 1


def test_a_list_that_fails_stops_the_map_read_before_the_next_list():
    facts, api = read_map(answers=failing(contents(REPO)))
    assert facts.map_stale is None
    assert contents(TAP) not in api.asked


# --- The bench: the history of the runs, main's checks, the stores ---


from tests.test_desk_bench import LOG  # noqa: E402

STEP = desk_gather.desk_bench.STARTUP_STEP
HISTORY = {
    "nightly.yml": f"repos/{REPO}/actions/workflows/nightly.yml/runs?branch=main&event=schedule"
                   "&status=completed&per_page=30",
    "latest-deps.yml": f"repos/{REPO}/actions/workflows/latest-deps.yml/runs?branch=main"
                       "&event=schedule&status=completed&per_page=30",
    "release.yml": f"repos/{REPO}/actions/workflows/release.yml/runs?event=push"
                   "&status=completed&per_page=100",
}
SHA_A = "a" * 40


def history_run(run_id, created, head_branch="main"):
    return {"id": run_id, "created_at": created, "head_sha": SHA_A, "head_branch": head_branch,
            "html_url": f"https://github.com/{REPO}/actions/runs/{run_id}"}


def measuring_job(name, job_id):
    return {"id": job_id, "name": name, "conclusion": "success",
            "html_url": f"https://github.com/{REPO}/actions/runs/1/job/{job_id}",
            "steps": [{"name": STEP, "conclusion": "success"}]}


BENCH = {
    HISTORY["nightly.yml"]: {"workflow_runs": [history_run(70, "2026-11-16T02:37:00Z")]},
    HISTORY["latest-deps.yml"]: {"workflow_runs": []},
    HISTORY["release.yml"]: {"workflow_runs": [
        history_run(80, "2026-11-14T17:00:00Z", "v0.9.2"),
        history_run(81, "2026-11-15T09:00:00Z")]},  # a push to main: no release
    night_jobs(70): {"jobs": [measuring_job("systems (macos-latest, 3.14)", 701),
                              {"id": 702, "name": "browser", "conclusion": "success",
                               "steps": []}]},
    night_jobs(80): {"jobs": [measuring_job("build (macos-latest)", 801)]},
}
LOGS = {f"repos/{REPO}/actions/jobs/701/logs": LOG, f"repos/{REPO}/actions/jobs/801/logs": LOG}


class LogApi(FakeApi):
    """FakeApi with the jobs' logs."""

    def __init__(self, answers, logs=LOGS):
        super().__init__(answers)
        self.logs = logs

    def log(self, address):
        self.asked.append(address)
        answer = self.logs.get(address, CalledProcessError(1, "gh"))
        if isinstance(answer, Exception):
            raise answer
        return answer


def pyproject(url):
    assert url == f"https://raw.githubusercontent.com/{REPO}/{SHA_A}/pyproject.toml"
    return '[project]\nname = "kitden"\nversion = "0.9.2"\n'


def test_the_history_gets_each_new_nightly_run_and_each_release_with_its_times():
    api = LogApi(BENCH)
    history = desk_gather.update_history(api, pyproject, REPO, [])
    assert [(line["id"], line["workflow"], line["version"]) for line in history] == [
        (80, "release.yml", "0.9.2"), (70, "nightly.yml", "0.9.2")]
    nightly = history[1]["jobs"]
    assert nightly[0]["times"] == {"first": 0.8, "complete": 0.9, "demo": 0.2}
    assert "times" not in nightly[1]  # the browser job measures nothing: its log is not read
    assert f"repos/{REPO}/actions/jobs/702/logs" not in api.asked
    assert night_jobs(81) not in api.asked  # a push to main is no release


def test_a_run_already_in_the_history_is_not_read_again():
    api = LogApi(BENCH)
    known = [{"id": 70, "workflow": "nightly.yml", "night": "2026-11-16", "jobs": []},
             {"id": 80, "workflow": "release.yml", "night": "2026-11-14", "jobs": []}]
    assert [line["id"] for line in desk_gather.update_history(api, pyproject, REPO, known)] == [
        80, 70]  # oldest night first
    assert night_jobs(70) not in api.asked and night_jobs(80) not in api.asked


def test_a_log_that_cannot_be_read_is_tried_again_then_left(capsys):
    history = desk_gather.update_history(LogApi(BENCH, logs={}), pyproject, REPO, [])
    assert all("times" not in job for line in history for job in line["jobs"])
    assert [(line["unread_logs"], line["tries"]) for line in history] == [(1, 1), (1, 1)]
    assert "::warning::desk: could not read log of" in capsys.readouterr().out
    again = desk_gather.update_history(LogApi(BENCH), pyproject, REPO, history)
    assert all(line["unread_logs"] == 0 for line in again)
    assert again[1]["jobs"][0]["times"]["first"] == 0.8
    for _ in range(4):  # a log refused for good is tried LOG_TRIES days, then left
        history = desk_gather.update_history(LogApi(BENCH, logs={}), pyproject, REPO, history)
    assert {line["tries"] for line in history} == {desk_gather.desk_bench.LOG_TRIES}
    api = LogApi(BENCH, logs={})
    desk_gather.update_history(api, pyproject, REPO, history)
    assert night_jobs(70) not in api.asked


def test_a_log_without_times_is_read_not_unread():
    logs = {address: "no times here" for address in LOGS}
    history = desk_gather.update_history(LogApi(BENCH, logs=logs), pyproject, REPO, [])
    assert [line["unread_logs"] for line in history] == [0, 0]


def test_a_run_that_was_run_again_is_read_again():
    first = desk_gather.update_history(LogApi(BENCH), pyproject, REPO, [])
    rerun = {**BENCH, HISTORY["nightly.yml"]: {"workflow_runs": [
        {**history_run(70, "2026-11-16T02:37:00Z"), "run_attempt": 2}]}}
    api = LogApi(rerun)
    again = desk_gather.update_history(api, pyproject, REPO, first)
    assert night_jobs(70) in api.asked and night_jobs(80) not in api.asked
    assert next(line for line in again if line["id"] == 70)["attempt"] == 2


def test_a_first_day_reads_the_oldest_runs_first_and_no_more_than_its_share(monkeypatch):
    monkeypatch.setattr(desk_gather, "NEW_RUNS", 1)
    history = desk_gather.update_history(LogApi(BENCH), pyproject, REPO, [])
    assert [line["id"] for line in history] == [80]  # the next day reads 70


def test_main_s_checks_come_from_the_run_of_its_push():
    checks = [{"name": "build (macos-latest)", "event": "push",
               "details_url": f"https://github.com/{REPO}/actions/runs/90/job/1"},
              {"name": "prepare / agent", "event": "workflow_dispatch",
               "details_url": f"https://github.com/{REPO}/actions/runs/91/job/1"}]
    answers = {f"repos/{REPO}/actions/runs/90": {"head_sha": SHA_A, "html_url": "u",
                                                 "updated_at": "2026-11-16T18:29:27Z"},
               night_jobs(90): {"jobs": [{"name": "build (macos-latest)", "html_url": "j",
                                          "steps": [{"name": "Run uv run pyright",
                                                     "conclusion": "success"}]}]}}
    found = desk_gather._gate(FakeApi(answers), REPO, checks)
    assert found["steps"] == [{"name": "Types", "state": "green", "url": "j"}]
    assert desk_gather._gate(FakeApi({}), REPO, checks[1:]) is None


FORMULA = ('class Kitden < Formula\n  desc "x"\n  url "https://files.pythonhosted.org/packages/'
           'a6/a2/ead9/kitden-0.9.2.tar.gz"\n')
REGISTRY = {"servers": [{"server": {"name": "io.github.KonstantinStarovoytov/kitden",
                                   "version": "0.9.1"},
                         "_meta": {"io.modelcontextprotocol.registry/official": {
                             "isLatest": False, "updatedAt": "2026-11-13T00:00:00Z"}}},
                        {"server": {"name": "io.github.KonstantinStarovoytov/kitden",
                                    "version": "0.9.2"},
                         "_meta": {"io.modelcontextprotocol.registry/official": {
                             "isLatest": True, "updatedAt": "2026-11-14T17:21:14Z"}}}]}
PYPI = {"info": {"version": "0.9.2"},
        "releases": {"0.9.2": [{"upload_time_iso_8601": "2026-11-14T17:20:42Z"}]}}


# The start of MCP Rush's badge as it was on 17 Nov 2026.
CARD = ('<svg xmlns="http://www.w3.org/2000/svg" width="380" height="200"><title>Kitden MCP on '
        'mcprush</title><desc>Kitden MCP by KonstantinStarovoytov on mcprush · security A, high '
        'access, no sign-in, 4 tools, works with 14 clients · 314/mo PyPI · Local · Free · '
        'v0.9.2 · updated 3d ago</desc>')


def store_fetch(url):
    if url == desk_gather.release_stores.FORMULA:
        return FORMULA
    if url == desk_gather.REGISTRY_LATEST:
        return json.dumps(REGISTRY)
    if url == desk_gather.release_stores.PYPI:
        return json.dumps(PYPI)
    if url == desk_gather.MCPRUSH_CARD:
        return CARD
    if url == desk_gather.GLAMA:
        return "<html>Kitden</html>"
    raise OSError("not listed")


def test_each_store_gives_the_version_it_serves():
    assert desk_gather._pypi(store_fetch) == {
        "version": "0.9.2", "at": "2026-11-14T17:20:42Z",
        "url": "https://pypi.org/project/kitden/0.9.2/"}
    assert desk_gather._homebrew(store_fetch)["version"] == "0.9.2"
    assert desk_gather._registry(store_fetch)["version"] == "0.9.2"  # the latest, not the first
    assert desk_gather.REGISTRY_LATEST.endswith("&version=latest")
    assert desk_gather._glama(store_fetch)["listed"] is True
    assert desk_gather._mcprush(store_fetch) == {"version": "0.9.2", "at": None,
                                                 "url": desk_gather.MCPRUSH}


def test_main_writes_the_history_and_the_bench(tmp_path):
    argv = ["--roster", str(ROOT / "config/agents.json"), "--out", str(tmp_path)]
    assert main(argv, api=LogApi({**ANSWERS, **BENCH}), now=NOW) == 0
    history = json.loads((tmp_path / "history.json").read_text())
    assert [line["id"] for line in history] == [80, 70]
    bench = json.loads((tmp_path / "desk.json").read_text())["bench"]
    assert bench["startup"]["versions"] == ["0.9.2"] and bench["rows"][0]["name"] == "macOS · arm64"
    # Offline and with no release faked: no store is read, nor the newest release, so grey.
    assert bench["stores"]["stores"][0]["state"] == "grey"
