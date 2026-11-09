import json
from pathlib import Path

import pytest

import post_findings
from post_findings import (
    ApiError,
    Finding,
    Report,
    finding_key,
    first_line,
    load_report,
    main,
    marker,
    plan_posts,
    post,
    summary_body,
)

FIXTURE = Path(__file__).parent / "fixtures" / "findings_ok.json"
SCHEMA = Path(__file__).parent.parent / "schemas" / "findings.schema.json"
FIRST = "Automated review by Kitden's claude reviewer (claude-opus-5). 👍 useful · 👎 wrong"


class FakeApi:
    """Records calls and keeps the comments it was given."""

    def __init__(self, outside_diff_paths=()):
        self.review_comments: list[dict] = []
        self.issue_comments: list[dict] = []
        self.outside_diff_paths = set(outside_diff_paths)
        self.calls: list[tuple] = []

    def list_review_comments(self, repo, pr):
        return list(self.review_comments)

    def list_issue_comments(self, repo, pr):
        return list(self.issue_comments)

    def create_review_comment(self, repo, pr, body, commit_id, path, line):
        self.calls.append(("review", path, line, body))
        if path in self.outside_diff_paths:
            raise ApiError(422)
        self.review_comments.append({"body": body})

    def create_issue_comment(self, repo, pr, body):
        self.calls.append(("issue-create", body))
        self.issue_comments.append({"id": len(self.issue_comments) + 1, "body": body})

    def update_issue_comment(self, repo, comment_id, body):
        self.calls.append(("issue-update", comment_id, body))
        for comment in self.issue_comments:
            if comment["id"] == comment_id:
                comment["body"] = body


def finding(path="a.py", line=1, kind="bug", text="Something is wrong."):
    return Finding(path=path, line=line, kind=kind, text=text)


def report(findings=(), new_surface=(), summary="All fine."):
    return Report(summary=summary, new_surface=list(new_surface), findings=list(findings))


def run_post(api, rep, limit=5):
    post(rep, api, "o/r", 7, "abc123", "claude", "claude-opus-5", limit)


def write(tmp_path, data):
    path = tmp_path / "findings.json"
    path.write_text(data if isinstance(data, str) else json.dumps(data))
    return path


def test_missing_report_returns_none(tmp_path, capsys):
    assert load_report(tmp_path / "nope.json") is None
    assert capsys.readouterr().err.count("\n") == 1


def test_invalid_json_returns_none(tmp_path):
    assert load_report(write(tmp_path, "{not json")) is None


def test_schema_violation_returns_none(tmp_path):
    data = json.loads(FIXTURE.read_text())
    data["findings"][0]["kind"] = "style"
    assert load_report(write(tmp_path, data)) is None


def test_valid_report_loads():
    rep = load_report(FIXTURE)
    assert rep is not None
    assert [f.path for f in rep.findings] == ["src/sync.py", "docs/setup.md"]
    assert len(rep.new_surface) == 1


@pytest.mark.parametrize(
    "change",
    [
        lambda d: d.pop("new_surface"),
        lambda d: d.update(extra=1),
        lambda d: d.update(summary="x" * 1201),
        lambda d: d.update(findings=[d["findings"][0]] * 11),
        lambda d: d["findings"][0].update(line=0),
        lambda d: d["findings"][0].update(line=True),
        lambda d: d["findings"][0].update(line=1.5),
        lambda d: d["findings"][0].update(text="x" * 601),
        lambda d: d["findings"][0].update(extra=1),
        lambda d: d["findings"][0].pop("path"),
        lambda d: d.update(new_surface=[1]),
    ],
)
def test_other_schema_violations_return_none(tmp_path, change):
    data = json.loads(FIXTURE.read_text())
    change(data)
    assert load_report(write(tmp_path, data)) is None


def test_non_object_returns_none(tmp_path):
    assert load_report(write(tmp_path, "[]")) is None


def test_schema_file_agrees_with_code():
    schema = json.loads(SCHEMA.read_text())
    item = schema["properties"]["findings"]["items"]
    assert schema["required"] == ["summary", "new_surface", "findings"]
    assert schema["additionalProperties"] is False and item["additionalProperties"] is False
    assert schema["properties"]["summary"]["maxLength"] == post_findings.SUMMARY_MAX
    assert schema["properties"]["findings"]["maxItems"] == post_findings.FINDINGS_MAX
    assert item["properties"]["text"]["maxLength"] == post_findings.TEXT_MAX
    assert item["properties"]["line"]["minimum"] == 1
    assert item["properties"]["kind"]["enum"] == ["bug", "rule"]
    assert set(item["required"]) == {"path", "line", "kind", "text"}


def test_marker_and_key():
    assert marker("claude", "a.py:3:bug") == "<!-- kitden-agents:claude:a.py:3:bug -->"
    assert finding_key(finding("a.py", 3, "bug")) == "a.py:3:bug"


def test_first_line_names_reviewer_and_model():
    assert first_line("claude", "claude-opus-5") == FIRST


def test_plan_skips_already_posted():
    f1, f2 = finding("a.py", 1), finding("b.py", 2)
    plan = plan_posts(report([f1, f2]), {finding_key(f1)})
    assert plan.inline == [f2]
    assert plan.overflow == []


def test_plan_limits_to_five_and_lists_overflow():
    findings = [finding(f"f{i}.py", i + 1) for i in range(7)]
    plan = plan_posts(report(findings), set())
    assert plan.inline == findings[:5]
    assert plan.overflow == findings[5:]


def test_summary_is_created_once_then_updated():
    api = FakeApi()
    rep = report([finding()])
    run_post(api, rep)
    run_post(api, rep)
    kinds = [call[0] for call in api.calls]
    assert kinds.count("issue-create") == 1
    assert kinds.count("issue-update") == 1
    assert len(api.issue_comments) == 1
    assert api.issue_comments[0]["body"].startswith(FIRST)
    assert marker("claude", "summary") in api.issue_comments[0]["body"]


def test_other_reviewers_summary_is_left_alone():
    api = FakeApi()
    api.issue_comments.append({"id": 9, "body": f"x\n\n{marker('gpt', 'summary')}"})
    run_post(api, report())
    assert [call[0] for call in api.calls] == ["issue-create"]


def test_422_moves_finding_to_summary():
    api = FakeApi(outside_diff_paths={"far.py"})
    run_post(api, report([finding("far.py", 9, text="Check the timeout."), finding("a.py")]))
    body = api.issue_comments[0]["body"]
    assert "Outside the diff" in body
    assert "Check the timeout." in body
    assert len(api.review_comments) == 1


def test_other_api_errors_are_raised():
    class Broken(FakeApi):
        def create_review_comment(self, *args):
            raise ApiError(500)

    with pytest.raises(ApiError):
        run_post(Broken(), report([finding()]))


def test_inline_comment_has_first_line_text_and_marker():
    api = FakeApi()
    run_post(api, report([finding("a.py", 3, "rule", "Add a test.")]))
    body = api.review_comments[0]["body"]
    assert body.startswith(FIRST)
    assert "Add a test." in body
    assert body.rstrip().endswith(marker("claude", "a.py:3:rule"))


def test_new_surface_is_listed():
    body = summary_body(report(new_surface=["New setting `x`"]), "claude", "claude-opus-5", [], [])
    assert "Adds something a user can see or set:" in body
    assert "- New setting `x`" in body


def test_overflow_is_listed_in_summary():
    extra = finding("z.py", 4, text="Last one.")
    body = summary_body(report(), "claude", "claude-opus-5", [extra], [])
    assert "z.py:4" in body and "Last one." in body


def test_rerun_same_head_posts_nothing_new():
    api = FakeApi()
    rep = report([finding("a.py", 1), finding("b.py", 2)])
    run_post(api, rep)
    first_run = [call for call in api.calls if call[0] == "review"]
    run_post(api, rep)
    second_run = [call for call in api.calls if call[0] == "review"]
    assert len(first_run) == 2
    assert second_run == first_run
    assert len(api.review_comments) == 2


def test_fake_marker_inside_text_does_not_hide_a_finding():
    api = FakeApi()
    api.review_comments.append(
        {"body": f"{FIRST}\n\nsee {marker('claude', 'a.py:1:bug')} here\n\nend"}
    )
    plan = plan_posts(
        report([finding("a.py", 1)]), post_findings.posted_keys(api.review_comments, "claude")
    )
    assert len(plan.inline) == 1


def test_dry_run_prints_plan_without_api(capsys, monkeypatch):
    def no_gh(*args, **kwargs):
        raise AssertionError("gh must not be called")

    monkeypatch.setattr(post_findings.subprocess, "run", no_gh)
    assert main(["--report", str(FIXTURE), "--dry-run"]) == 0
    plan = json.loads(capsys.readouterr().out)
    assert [f["path"] for f in plan["inline"]] == ["src/sync.py", "docs/setup.md"]
    assert plan["overflow"] == []
    assert plan["summary"].startswith("Automated review by Kitden's claude reviewer (dry-run).")


def test_main_with_missing_report_exits_zero(tmp_path):
    argv = ["--report", str(tmp_path / "nope.json"), "--dry-run"]
    assert main(argv) == 0


def test_main_needs_repo_without_dry_run(tmp_path):
    with pytest.raises(SystemExit):
        main(["--report", str(FIXTURE)])


class FakeRun:
    """Stands in for subprocess.run and records the gh command."""

    def __init__(self, returncode=0, stdout="", stderr=""):
        self.result = type("Done", (), {})()
        self.result.returncode, self.result.stdout, self.result.stderr = (
            returncode,
            stdout,
            stderr,
        )
        self.commands: list[list[str]] = []

    def __call__(self, command, **kwargs):
        self.commands.append(command)
        return self.result


def test_gh_api_422_becomes_api_error(monkeypatch):
    run = FakeRun(1, stderr="gh: Validation Failed (HTTP 422)")
    monkeypatch.setattr(post_findings.subprocess, "run", run)
    with pytest.raises(ApiError) as caught:
        post_findings.GhApi().create_review_comment("o/r", 7, "b", "sha", "a.py", 3)
    assert caught.value.status == 422
    command = run.commands[0]
    assert command[:3] == ["gh", "api", "repos/o/r/pulls/7/comments"]
    assert "line=3" in command and "side=RIGHT" in command


def test_gh_api_error_without_status_is_zero(monkeypatch):
    monkeypatch.setattr(post_findings.subprocess, "run", FakeRun(1, stderr="no network"))
    with pytest.raises(ApiError) as caught:
        post_findings.GhApi().create_issue_comment("o/r", 7, "b")
    assert caught.value.status == 0


def test_gh_api_lists_join_all_pages(monkeypatch):
    run = FakeRun(stdout='[{"id": 1}]\n[{"id": 2}, {"id": 3}]')
    monkeypatch.setattr(post_findings.subprocess, "run", run)
    comments = post_findings.GhApi().list_review_comments("o/r", 7)
    assert [c["id"] for c in comments] == [1, 2, 3]
    assert "--paginate" in run.commands[0]


SECRET_TEXTS = [
    "sk-ant-api03-abc",
    "ghp_" + "a" * 36,
    "gho_abc",
    "ghu_abc",
    "ghs_abc",
    "ghr_abc",
    "github_pat_11AAA",
    "https://x-access-token:abc@github.com",
    "key sk-" + "a1" * 12,
]


@pytest.mark.parametrize("secret", SECRET_TEXTS)
def test_secret_like_text_is_never_posted(secret):
    for rep in (
        report(summary=f"Token {secret}"),
        report(new_surface=[secret]),
        report([finding(text=f"Leaks {secret}")]),
        report([finding(path=secret)]),
    ):
        api = FakeApi()
        with pytest.raises(post_findings.SecretLikeError):
            run_post(api, rep)
        assert api.calls == []


def test_ordinary_text_is_not_taken_for_a_secret():
    text = "The task-runner and risk-score checks, rights_check, sk-short, high_ghs"
    api = FakeApi()
    run_post(api, report([finding(text=text)], summary=text))
    assert api.calls


def test_main_refuses_a_secret_and_exits_one(tmp_path, capsys, monkeypatch):
    def no_gh(*args, **kwargs):
        raise AssertionError("gh must not be called")

    monkeypatch.setattr(post_findings.subprocess, "run", no_gh)
    path = write(
        tmp_path,
        {"summary": "ok ghp_" + "a" * 36, "new_surface": [], "findings": []},
    )
    argv = ["--report", str(path), "--repo", "o/r", "--pr", "7", "--head-sha", "abc"]
    argv += ["--reviewer", "claude", "--model", "m"]
    assert main(argv) == 1
    assert capsys.readouterr().err.strip() == "claude refused: output looked like a secret"


def test_dry_run_reports_a_secret(tmp_path, capsys):
    path = write(tmp_path, {"summary": "sk-ant-oops", "new_surface": [], "findings": []})
    assert main(["--report", str(path), "--dry-run"]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.strip() == "claude refused: output looked like a secret"
