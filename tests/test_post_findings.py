import json
import subprocess
from pathlib import Path

import pytest

import post_findings
from post_findings import (
    Earlier,
    Finding,
    GhApi,
    Item,
    Report,
    SecretLikeError,
    earlier_review,
    file_changes,
    find_ours,
    load_report,
    main,
    marker,
    merge,
    model_label,
    one_line,
    parse_patch,
    post,
    quiet_mentions,
    read_marker,
    read_state,
    refuse_secret_like,
    review_body,
)
from tests.fakes import KEY_TAIL, repo, shows_key

FIXTURE = Path(__file__).parent / "fixtures" / "findings_ok.json"
ROOT = Path(__file__).parent.parent
SCHEMA = ROOT / "schemas" / "findings.schema.json"
SKILL = ROOT / "plugins" / "kitden-sdlc" / "skills" / "review-kitden" / "SKILL.md"
SHA = "abcdef1234567890"
WJ = "\u2060"


BOT_USER = {"login": "github-actions[bot]", "type": "Bot"}


class FakeApi:
    """Records calls and keeps the comments it was given."""

    def __init__(self):
        self.comments: list[dict] = []
        self.calls: list[tuple] = []
        self.compared: dict | None = {"status": "ahead", "files": []}

    def list_issue_comments(self, repo, pr):
        return list(self.comments)

    def create_issue_comment(self, repo, pr, body):
        self.calls.append(("create", body))
        self.comments.append({"id": len(self.comments) + 1, "body": body, "user": dict(BOT_USER)})

    def update_issue_comment(self, repo, comment_id, body):
        self.calls.append(("update", comment_id, body))
        for comment in self.comments:
            if comment["id"] == comment_id:
                comment["body"] = body

    def compare(self, repo, base, head):
        self.calls.append(("compare", base, head))
        return self.compared

    def pull_text(self, repo, pr):
        self.calls.append(("pull_text", pr))
        return "Title\n\nBody"


def finding(path="a.py", line=1, kind="bug", text="Something is wrong."):
    return Finding(path=path, line=line, kind=kind, text=text)


def report(findings=(), summary="All fine."):
    return Report(summary=summary, findings=list(findings))


def body_of(claude=None, luna=None, repo="o/r"):
    return review_body({"claude": claude, "luna": luna}, repo, SHA)


def visible(body):
    """The comment without the hidden line that holds the earlier findings."""
    return "\n".join(line for line in body.splitlines() if "kitden-sdlc:state" not in line)


def write(tmp_path, data, name="findings.json"):
    path = tmp_path / name
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


@pytest.mark.parametrize(
    "change",
    [
        lambda d: d.pop("summary"),
        lambda d: d.update(extra=1),
        lambda d: d.update(summary=5),
        lambda d: d.update(findings={}),
        lambda d: d["findings"][0].update(line=0),
        lambda d: d["findings"][0].update(line=True),
        lambda d: d["findings"][0].update(line=1.5),
        lambda d: d["findings"][0].update(text=None),
        lambda d: d["findings"][0].update(kind="style"),
        lambda d: d["findings"][0].update(extra=1),
        lambda d: d["findings"][0].pop("path"),
        lambda d: d.update(new_surface=[]),
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
    assert schema["required"] == ["summary", "findings"]
    assert schema["additionalProperties"] is False and item["additionalProperties"] is False
    assert schema["properties"]["summary"]["maxLength"] == post_findings.SUMMARY_MAX
    assert schema["properties"]["findings"]["maxItems"] == post_findings.FINDINGS_MAX
    assert item["properties"]["text"]["maxLength"] == post_findings.TEXT_MAX
    assert item["properties"]["line"]["minimum"] == 1
    assert item["properties"]["kind"]["enum"] == ["bug", "rule"]
    assert set(item["required"]) == {"path", "line", "kind", "text"}


# --- Merging the two reviewers ---


def test_same_path_within_five_lines_is_one_item_with_claudes_text():
    claude = report([finding("a.py", 10, text="Claude's words.")])
    luna = report([finding("a.py", 15, text="Luna's words.")])
    (item,) = merge({"claude": claude, "luna": luna})
    assert item.by == ["claude", "luna"]
    assert item.finding.text == "Claude's words."


def test_six_lines_apart_or_another_path_stays_two_items():
    claude = report([finding("a.py", 10)])
    assert len(merge({"claude": claude, "luna": report([finding("a.py", 16)])})) == 2
    assert len(merge({"claude": claude, "luna": report([finding("b.py", 10)])})) == 2


def test_one_reviewers_nearby_findings_stay_two():
    claude = report([finding("a.py", 10), finding("a.py", 11)])
    items = merge({"claude": claude, "luna": None})
    assert [i.by for i in items] == [["claude"], ["claude"]]


def test_shared_items_come_first_and_the_rest_keep_order():
    claude = report([finding("a.py", 1), finding("b.py", 1), finding("c.py", 1)])
    luna = report([finding("d.py", 1), finding("c.py", 2)])
    items = merge({"claude": claude, "luna": luna})
    assert [i.finding.path for i in items] == ["c.py", "a.py", "b.py", "d.py"]
    assert [len(i.by) for i in items] == [2, 1, 1, 1]


def test_merge_with_no_reports_is_empty():
    assert merge({"claude": None, "luna": None}) == []


# --- The comment ---


def test_first_line_is_only_the_title():
    assert body_of(report(), report()).splitlines()[0] == "**Agent review**"


def test_the_badges_say_who_answered_how_much_to_check_and_the_commit():
    """The bots' one look (bot_style.py): the badges come right under the title."""
    row = body_of(report([finding("a.py", 1)]), None).splitlines()[2]
    assert row.startswith("<picture>") and 'alt="Claude: answered"' in row
    assert 'alt="Luna: no answer"' in row and 'alt="to check: 1"' in row
    clean = body_of(report(), report()).splitlines()[2]
    assert 'alt="Luna: answered"' in clean and 'alt="new problems: none"' in clean
    silent = body_of(None, None)
    assert 'alt="to check' not in silent and 'alt="new problems' not in silent
    assert "> [!WARNING]\n> Neither reviewer gave a usable answer" in silent


def test_summary_comes_from_claude_else_luna():
    both = body_of(report(summary="From Claude."), report(summary="From Luna."))
    assert "From Claude." in both and "From Luna." not in both
    only_luna = body_of(None, report(summary="From Luna."))
    assert "From Luna." in only_luna


def test_no_findings_says_so():
    body = body_of(report(), report())
    assert "No problems found." in body
    assert "To check" not in body


def test_findings_are_counted_and_tagged_with_who_found_them():
    claude = report([finding("a.py", 1, text="Shared."), finding("b.py", 1, text="Mine.")])
    luna = report([finding("a.py", 2), finding("c.py", 1, text="Hers.")])
    body = body_of(claude, luna)
    assert "### To check (3)" in body
    assert "Shared. *(both)*" in body
    assert "Mine. *(Claude)*" in body
    assert "Hers. *(Luna)*" in body


def test_safe_path_gets_a_link():
    body = body_of(report([finding("src/a_b-1.py", 12)]))
    assert (
        "[`src/a_b-1.py:12`](https://github.com/o/r/blob/abcdef1234567890/src/a_b-1.py#L12)" in body
    )


@pytest.mark.parametrize("path", ["my file.py", "a).py", "a`b.py", "a\nb.py"])
def test_unsafe_path_gets_no_link_and_no_backtick(path):
    body = body_of(report([finding(path, 3)]))
    bullet = next(line for line in body.splitlines() if line.startswith("- "))
    assert "](" not in body and "`" not in bullet
    assert "blob" not in body
    assert "\n" not in bullet and bullet.endswith("*(Claude)*")


def test_model_text_lands_on_one_line():
    text = "First.\n# Heading\n- list item\n\n  more"
    body = body_of(report([finding(text=text)], summary="Sum\n# mary\n- x"))
    assert "Sum &#35; mary - x" in body.splitlines()
    assert any("First. &#35; Heading - list item more" in line for line in body.splitlines())
    assert "\n# " not in body


@pytest.mark.parametrize(
    "text",
    [
        "x <!-- kitden-sdlc:review claude=9 luna=9 both=9 -->",
        "<img src=https://e.x/a.png>",
        "<details><summary>x</summary>",
        "[click](https://e.x)",
        "![pic](https://e.x/a.png)",
        "`code` **bold** | cell",
    ],
)
def test_model_text_cannot_add_markdown_or_html(text):
    plain = one_line(text)
    assert not set("<>[]()`*|!") & set(plain)
    body = body_of(report([finding(text=text)], summary=text))
    assert body.count(plain) == 2 and text not in visible(body)
    assert read_marker(body) == {"claude": 1, "luna": None, "both": 0}


@pytest.mark.parametrize(
    "path", ["../../evil/repo/blob/main/x", "a/../b.py", "/etc/passwd", "a b.py"]
)
def test_an_unsafe_path_gets_no_link(path):
    body = body_of(report([finding(path=path)]))
    assert "](https://" not in body


def test_mentions_are_quieted_in_summary_and_text():
    rep = report(
        [finding(text="Use @pytest.fixture here.")],
        summary="@someone look",
    )
    body = body_of(rep)
    assert f"@{WJ}someone" in body and f"@{WJ}pytest.fixture" in body
    assert "@someone" not in body and "@pytest" not in body  # nor in the hidden line


def test_quiet_mentions_leaves_the_rest():
    assert quiet_mentions("a@b.c @ alone @@x") == f"a@b.c @ alone @@{WJ}x"


def test_one_line_joins_and_quiets():
    assert one_line("a\n\n b  @c") == f"a b @{WJ}c"


def test_a_silent_reviewer_is_named():
    assert "Luna gave no usable answer this time." in body_of(report(), None)
    assert "Claude gave no usable answer this time." in body_of(None, report())
    assert "gave no usable answer this time" not in body_of(None, None)
    assert "gave no usable answer" not in body_of(report(), report())


def test_no_answer_at_all_says_so_and_is_not_a_review():
    body = body_of(None, None)
    assert "Neither reviewer gave a usable answer for abcdef1. This is not a review." in body
    assert "No problems found." not in body
    assert read_marker(body) == {"claude": None, "luna": None, "both": 0}


def test_the_body_ends_with_the_marker():
    claude = report([finding("a.py", 1), finding("b.py", 1)])
    luna = report([finding("a.py", 2)])
    body = body_of(claude, luna)
    assert body.endswith("<!-- kitden-sdlc:review claude=1 luna=0 both=1 -->")
    assert read_marker(body) == {"claude": 1, "luna": 0, "both": 1}


# --- The marker ---


def test_marker_round_trip():
    claude = report([finding("a.py", 1), finding("b.py", 1)])
    luna = report([finding("a.py", 2), finding("c.py", 1)])
    items = merge({"claude": claude, "luna": luna})
    text = marker(["claude", "luna"], items)
    assert text == "<!-- kitden-sdlc:review claude=1 luna=1 both=1 -->"
    assert read_marker(f"Text.\n\n{text}\n") == {"claude": 1, "luna": 1, "both": 1}


def test_marker_has_x_for_a_silent_reviewer():
    text = marker(["claude"], [])
    assert text == "<!-- kitden-sdlc:review claude=0 luna=x both=0 -->"
    assert read_marker(text) == {"claude": 0, "luna": None, "both": 0}


def test_marker_not_at_the_end_is_not_read():
    text = marker(["claude", "luna"], [])
    assert read_marker(f"{text}\n\nand then more text") is None
    assert read_marker("No marker here.") is None


# --- Posting ---


def test_post_creates_when_there_is_no_comment():
    api = FakeApi()
    post(api, "o/r", 7, body_of(report(), report()))
    assert [call[0] for call in api.calls] == ["create"]


def test_post_edits_the_bots_comment_in_place():
    api = FakeApi()
    post(api, "o/r", 7, body_of(report(), report()))
    new = body_of(report([finding()]), report())
    post(api, "o/r", 7, new)
    assert [call[0] for call in api.calls] == ["create", "update"]
    assert len(api.comments) == 1 and api.comments[0]["body"] == new


def test_post_ignores_a_persons_comment_with_the_marker():
    api = FakeApi()
    old = body_of(report(), report())
    api.comments.append({"id": 9, "body": old, "user": {"type": "User"}})
    post(api, "o/r", 7, old)
    assert [call[0] for call in api.calls] == ["create"]
    assert api.comments[0]["body"] == old


def test_post_ignores_a_bot_comment_without_the_marker():
    api = FakeApi()
    api.comments.append({"id": 9, "body": "Other bot.", "user": dict(BOT_USER)})
    api.comments.append({"id": 10, "body": None, "user": None})
    post(api, "o/r", 7, body_of(report(), report()))
    assert [call[0] for call in api.calls] == ["create"]


def test_post_ignores_another_bots_comment_with_the_marker():
    api = FakeApi()
    old = body_of(report(), report())
    api.comments.append({"id": 9, "body": old, "user": {"login": "other[bot]", "type": "Bot"}})
    post(api, "o/r", 7, old)
    assert [call[0] for call in api.calls] == ["create"]


def test_post_updates_the_review_apps_comment():
    api = FakeApi()
    old = body_of(report(), report())
    api.comments.append({"id": 9, "body": old, "user": {"login": "kitden-lantern[bot]"}})
    post(api, "o/r", 7, old)
    assert [call[0] for call in api.calls] == ["update"]


def test_post_refuses_a_secret_and_calls_nothing():
    api = FakeApi()
    with pytest.raises(SecretLikeError):
        post(api, "o/r", 7, "token ghp_" + "a" * 36)
    assert api.calls == []


# --- main ---


def argv_for(claude, luna, *extra):
    return ["--claude", str(claude), "--luna", str(luna), *extra]


def test_main_with_both_files_missing_posts_that_neither_answered(tmp_path, capsys, monkeypatch):
    api = FakeApi()
    monkeypatch.setattr(post_findings, "GhApi", lambda **_: api)
    argv = argv_for(tmp_path / "a.json", tmp_path / "b.json", "--pr", "7", "--head-sha", SHA)
    assert main(argv) == 0
    assert capsys.readouterr().out.count("::warning::") == 2
    assert [call[0] for call in api.calls] == ["create"]
    body = api.comments[0]["body"]
    assert "Neither reviewer gave a usable answer for abcdef1. This is not a review." in body
    assert read_marker(body) == {"claude": None, "luna": None, "both": 0}


def test_dry_run_with_both_files_missing_prints_that_neither_answered(tmp_path, capsys):
    argv = argv_for(tmp_path / "a.json", tmp_path / "b.json", "--dry-run", "--head-sha", SHA)
    assert main(argv) == 0
    assert "Neither reviewer gave a usable answer for abcdef1." in capsys.readouterr().out


def test_main_with_one_file_missing_still_prints_a_body(tmp_path, capsys):
    argv = argv_for(FIXTURE, tmp_path / "nope.json", "--dry-run", "--head-sha", SHA)
    assert main(argv) == 0
    out = capsys.readouterr().out
    assert "src/sync.py:42" in out
    assert "Luna gave no usable answer this time." in out
    assert out.rstrip().endswith("luna=x both=0 -->")


def test_main_posts_with_the_api(tmp_path, monkeypatch):
    api = FakeApi()
    monkeypatch.setattr(post_findings, "GhApi", lambda **_: api)
    assert main(argv_for(FIXTURE, FIXTURE, "--pr", "7", "--repo", "o/r")) == 0
    assert [call[0] for call in api.calls] == ["create"]
    assert "### To check (2)" in api.comments[0]["body"]


def test_main_needs_pr_without_dry_run():
    with pytest.raises(SystemExit):
        main(argv_for(FIXTURE, FIXTURE))


def test_main_refuses_a_secret_and_exits_one(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(post_findings, "GhApi", lambda **_: pytest.fail("no GitHub"))
    bad = write(tmp_path, {"summary": "ok ghp_" + "a" * 36, "findings": []})
    assert main(argv_for(bad, FIXTURE, "--pr", "7")) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "looked like a secret" in captured.err


def quoting(tmp_path):
    text = f"The value {KEY_TAIL} is wrong."
    return write(tmp_path, {"summary": "One problem.", "findings": [
        {"path": "a.py", "line": 1, "kind": "bug", "text": text}]})


def run_main(tmp_path, monkeypatch, files, *extra):
    api = FakeApi()
    monkeypatch.setattr(post_findings, "GhApi", lambda **_: api)
    tree = repo(tmp_path / "tree", files)
    code = main(argv_for(quoting(tmp_path), FIXTURE, "--pr", "7", "--head-sha", "HEAD",
                         "--tree", str(tree), *extra))
    return code, api


def test_main_refuses_a_random_run_the_pull_request_lacks(tmp_path, capsys, monkeypatch):
    code, api = run_main(tmp_path, monkeypatch, {"a.py": "x = 1\n"})
    err = capsys.readouterr().err
    assert code == 1 and not [c for c in api.calls if c[0] in ("create", "update")]
    assert "not in what the reviewers were given: 1 in Claude's text" in err
    assert not shows_key(err)


def test_main_refuses_every_random_run_when_the_tree_lacks_the_head(tmp_path, capsys, monkeypatch):
    # The fetch of the pull request's commit failed: the tree holds another commit.
    api = FakeApi()
    api.pull_text = lambda repo, pr: f"Rotate {KEY_TAIL} please"
    monkeypatch.setattr(post_findings, "GhApi", lambda **_: api)
    tree = repo(tmp_path / "tree", {"a.py": f"X = '{KEY_TAIL}'\n"})
    argv = argv_for(quoting(tmp_path), FIXTURE, "--pr", "7", "--head-sha", "1" * 40,
                    "--tree", str(tree))
    assert main(argv) == 1
    assert not [c for c in api.calls if c[0] in ("create", "update")]
    err = capsys.readouterr().err
    assert "the pull request's files could not be read, so every long random string" in err
    assert not shows_key(err)


def test_main_knows_nothing_when_the_pull_request_text_cannot_be_read(
    tmp_path, capsys, monkeypatch
):
    api = FakeApi()
    api.pull_text = lambda repo, pr: None
    monkeypatch.setattr(post_findings, "GhApi", lambda **_: api)
    assert main(argv_for(quoting(tmp_path), FIXTURE, "--pr", "7")) == 1
    captured = capsys.readouterr()
    assert "Cannot read the pull request's title and body" in captured.out
    assert "Refused:" in captured.err and "Traceback" not in captured.err


def test_main_posts_a_random_run_the_pull_request_holds(tmp_path, monkeypatch):
    code, api = run_main(tmp_path, monkeypatch, {"a.py": f"X = '{KEY_TAIL}'\n"})
    assert code == 0 and api.calls[-1][0] == "create"


def test_main_posts_a_random_run_only_the_base_commit_holds(tmp_path, monkeypatch):
    api = FakeApi()
    monkeypatch.setattr(post_findings, "GhApi", lambda **_: api)
    tree = repo(tmp_path / "tree", {"a.py": f"X = '{KEY_TAIL}'\n"})
    base = subprocess.run(["git", "rev-parse", "HEAD"], cwd=tree, capture_output=True,
                          text=True, check=True).stdout.strip()
    repo(tree, {"a.py": "X = 1\n"})  # a second commit: the head no longer holds it
    argv = argv_for(quoting(tmp_path), FIXTURE, "--pr", "7", "--head-sha", "HEAD",
                    "--tree", str(tree))
    assert main(argv) == 1
    assert main([*argv, "--base-sha", base]) == 0
    assert api.calls[-1][0] == "create"


def test_main_posts_a_random_run_the_pull_request_text_holds(tmp_path, monkeypatch):
    api = FakeApi()
    api.pull_text = lambda repo, pr: f"Rotate {KEY_TAIL} please"
    monkeypatch.setattr(post_findings, "GhApi", lambda **_: api)
    assert main(argv_for(quoting(tmp_path), FIXTURE, "--pr", "7")) == 0
    assert api.calls[-1][0] == "create"


def test_main_without_a_tree_refuses_and_a_plain_report_reads_no_pull_request(
    tmp_path, monkeypatch
):
    api = FakeApi()
    monkeypatch.setattr(post_findings, "GhApi", lambda **_: api)
    assert main(argv_for(quoting(tmp_path), FIXTURE, "--pr", "7")) == 1
    assert main(argv_for(FIXTURE, FIXTURE, "--pr", "7")) == 0
    assert ("pull_text", 7) in api.calls and api.calls.count(("pull_text", 7)) == 1


def test_dry_run_skips_the_random_run_check(tmp_path, capsys):
    assert main(argv_for(quoting(tmp_path), FIXTURE, "--dry-run")) == 0
    assert "One problem." in capsys.readouterr().out


def test_dry_run_with_a_secret_exits_one(tmp_path, capsys):
    bad = write(tmp_path, {"summary": "sk-ant-oops-" + "x" * 20, "findings": []})
    assert main(argv_for(FIXTURE, bad, "--dry-run")) == 1
    assert capsys.readouterr().out == ""


# --- Talking to gh ---


class FakeRun:
    """Stands in for subprocess.run and records the gh command."""

    def __init__(self, stdout=""):
        self.result = type("Done", (), {"stdout": stdout})()
        self.commands: list[list[str]] = []

    def __call__(self, command, **kwargs):
        self.commands.append(command)
        return self.result


def test_gh_api_lists_join_all_pages(monkeypatch):
    run = FakeRun('[{"id": 1}]\n[{"id": 2}, {"id": 3}]')
    monkeypatch.setattr(post_findings.subprocess, "run", run)
    comments = GhApi().list_issue_comments("o/r", 7)
    assert [c["id"] for c in comments] == [1, 2, 3]
    assert run.commands[0][:3] == ["gh", "api", "repos/o/r/issues/7/comments"]
    assert "--paginate" in run.commands[0]


def test_gh_api_create_and_update(monkeypatch):
    run = FakeRun()
    monkeypatch.setattr(post_findings.subprocess, "run", run)
    GhApi().create_issue_comment("o/r", 7, "hi")
    GhApi().update_issue_comment("o/r", 5, "yo")
    assert run.commands[0][2:] == [
        "repos/o/r/issues/7/comments",
        "--method",
        "POST",
        "-f",
        "body=hi",
    ]
    assert run.commands[1][2:] == [
        "repos/o/r/issues/comments/5", "--method", "PATCH", "-f", "body=yo",
    ]  # fmt: skip


# --- Keeping secrets out ---

SECRET_TEXTS = [
    "sk-ant-api03-" + "a" * 16,
    "ghp_" + "a" * 36,
    "gho_" + "b" * 36,
    "ghu_" + "c" * 36,
    "ghs_" + "d" * 36,
    "ghr_" + "e" * 36,
    "github_pat_11AAA" + "b_" * 10,
    "sk-proj-" + "x" * 40,
    "https://x-access-token:abc123@github.com",
    "key sk-" + "a1" * 12,
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.sig",
]


@pytest.mark.parametrize("secret", SECRET_TEXTS)
def test_secret_like_text_is_refused(secret):
    for rep in (
        report(summary=f"Token {secret}"),
        report([finding(text=f"Leaks {secret}")]),
        report([finding(path=secret)]),
    ):
        with pytest.raises(SecretLikeError):
            refuse_secret_like(rep)


def test_ordinary_text_is_not_taken_for_a_secret():
    text = (
        "The task-runner and risk-score checks, rights_check, sk-short, high_ghs, "
        "the regex misses `ghs_`, `ghp_|gho_|ghu_|ghs_|github_pat_`, `sk-ant-`, "
        "and `x-access-token:` in a URL"
    )
    refuse_secret_like(report([finding(text=text)], summary=text))


# --- Too long is cut, not rejected ---


def test_long_summary_and_text_are_cut(tmp_path):
    data = json.loads(FIXTURE.read_text())
    data["summary"] = "s" * 400
    data["findings"][0]["text"] = "t" * 400
    rep = load_report(write(tmp_path, data))
    assert rep.summary == "s" * 299 + "…" and len(rep.summary) == post_findings.SUMMARY_MAX
    assert rep.findings[0].text == "t" * 299 + "…"
    assert rep.findings[1].text == data["findings"][1]["text"]


def test_text_at_the_limit_is_kept_whole(tmp_path):
    data = json.loads(FIXTURE.read_text())
    data["summary"] = "s" * 300
    data["findings"][0]["text"] = "t" * 300
    rep = load_report(write(tmp_path, data))
    assert rep.summary == "s" * 300 and rep.findings[0].text == "t" * 300


def test_only_the_first_five_findings_are_kept(tmp_path):
    data = json.loads(FIXTURE.read_text())
    data["findings"] = [dict(data["findings"][0], line=i + 1) for i in range(8)]
    rep = load_report(write(tmp_path, data))
    assert [f.line for f in rep.findings] == list(range(1, 6))


# --- The schema in the skill ---


def test_skill_schema_equals_the_schema_file():
    text = SKILL.read_text()
    block = text.split("```json\n", 1)[1].split("\n```", 1)[0]
    in_skill, in_file = json.loads(block), json.loads(SCHEMA.read_text())
    for key in ("$schema", "title"):
        in_skill.pop(key, None)
        in_file.pop(key, None)
    assert in_skill == in_file


def test_claude_is_named_by_its_model_family():
    assert model_label("claude-sonnet-5-5") == "Sonn"
    assert model_label("claude-opus-5-5") == "Opus"
    assert model_label("") == "Claude"
    assert model_label("some-other-model") == "Claude"


def test_the_comment_uses_the_names_it_is_given():
    names = {"claude": "Sonn", "luna": "Luna"}
    body = review_body(
        {"claude": report([finding("a.py", 1, text="Mine.")]), "luna": None},
        "o/r",
        SHA,
        names=names,
    )
    assert "Mine. *(Sonn)*" in body
    assert "Luna gave no usable answer this time." in body
    silent = review_body({"claude": None, "luna": report()}, "o/r", SHA, names=names)
    assert "Sonn gave no usable answer this time." in silent


def test_main_names_claude_by_the_model_it_is_given(tmp_path, capsys):
    claude = write(
        tmp_path,
        {
            "summary": "S.",
            "findings": [{"path": "a.py", "line": 1, "kind": "bug", "text": "Mine."}],
        },
        "claude.json",
    )
    luna = write(tmp_path, {"summary": "S.", "findings": []}, "luna.json")
    main(
        [
            "--claude",
            str(claude),
            "--luna",
            str(luna),
            "--claude-model",
            "claude-sonnet-5-5",
            "--dry-run",
        ]
    )
    assert "Mine. *(Sonn)*" in capsys.readouterr().out


# --- Earlier findings stay ---

NEXT = "1556615aaaaaaaaa"
LAST = "9999999bbbbbbbbb"


def run(api, claude=None, luna=None, head=SHA):
    """One review run as main does it, against the fake GitHub."""
    comments = api.list_issue_comments("o/r", 7)
    earlier, changes = earlier_review(api, "o/r", head, find_ours(comments))
    body = review_body({"claude": claude, "luna": luna}, "o/r", head, earlier, changes)
    post(api, "o/r", 7, body, comments)
    return body


def diff(path, patch=None, status="modified", **extra):
    entry = {"filename": path, "status": status, **extra}
    if patch is not None:
        entry["patch"] = patch
    return entry


def compared(*files, status="ahead"):
    return {"status": status, "files": list(files)}


ROADMAP = finding("AGENTS.md", 12, "rule", "AGENTS.md says to update ROADMAP.md; it has no entry.")


def test_a_finding_the_next_review_does_not_repeat_stays():
    # Kitden pull request 70: the second push only fixed a type error elsewhere.
    api = FakeApi()
    run(api, report([ROADMAP]), report())
    api.compared = compared(diff("src/x.py", "@@ -3,1 +3,1 @@\n-a: int = ''\n+a: int = 0"))
    body = run(api, report(), report(), head=NEXT)
    assert ("compare", SHA, NEXT) in api.calls
    assert "No new problems found." in body and "No problems found." not in body
    assert "### Not repeated by the latest review (1)" in body
    assert f"(https://github.com/o/r/blob/{NEXT}/AGENTS.md#L12)" in body
    assert "ROADMAP.md&#59;" not in body and "*(Claude, found in abcdef1)*" in body
    assert read_marker(body) == {"claude": 1, "luna": 0, "both": 0}
    assert len(api.comments) == 1


def test_a_finding_whose_lines_changed_is_fixed():
    api = FakeApi()
    run(api, report([finding("a.py", 11, text="Off by one.")]), report())
    api.compared = compared(diff("a.py", "@@ -10,3 +10,3 @@\n ctx\n-old\n+new\n ctx"))
    body = run(api, report(), report(), head=NEXT)
    assert "### Fixed (1)" in body and "Not repeated" not in body
    assert "Off by one. *(Claude, fixed in 1556615)*" in body
    # The link shows the line where it was found.
    assert f"(https://github.com/o/r/blob/{SHA}/a.py#L11)" in body
    assert "No problems found." in body
    assert read_marker(body) == {"claude": 1, "luna": 0, "both": 0}


def test_a_change_a_few_lines_away_does_not_fix_it():
    api = FakeApi()
    run(api, report([finding("a.py", 20)]), report())
    api.compared = compared(diff("a.py", "@@ -10,3 +10,3 @@\n ctx\n-old\n+new\n ctx"))
    body = run(api, report(), report(), head=NEXT)
    assert "Fixed" not in body and "### Not repeated by the latest review (1)" in body


def test_an_earlier_finding_follows_lines_added_above_it():
    api = FakeApi()
    run(api, report([finding("a.py", 20)]), report())
    api.compared = compared(diff("a.py", "@@ -1,0 +2,3 @@\n+x\n+y\n+z"))
    body = run(api, report(), report(), head=NEXT)
    assert f"(https://github.com/o/r/blob/{NEXT}/a.py#L23)" in body


def test_a_finding_made_again_is_one_item_by_everyone_who_made_it():
    api = FakeApi()
    run(api, report([finding("a.py", 20, text="Claude's words.")]), report())
    api.compared = compared(diff("a.py", "@@ -1,0 +2,3 @@\n+x\n+y\n+z"))
    body = run(api, report(), report([finding("a.py", 24, text="Luna's words.")]), head=NEXT)
    assert "### To check (1)" in body and "Not repeated" not in body
    assert "Luna's words. *(both)*" in body
    assert read_marker(body) == {"claude": 0, "luna": 0, "both": 1}


def test_without_a_compare_nothing_is_fixed_and_the_old_link_stays(capsys):
    api = FakeApi()
    run(api, report([finding("a.py", 11)]), report())
    api.compared = None  # say, the old head is gone after a force push
    body = run(api, report(), report(), head=NEXT)
    assert "Fixed" not in body and "### Not repeated by the latest review (1)" in body
    assert f"(https://github.com/o/r/blob/{SHA}/a.py#L11)" in body
    assert "Cannot tell what changed since abcdef1" in capsys.readouterr().out


@pytest.mark.parametrize(
    "answer",
    [
        compared(status="diverged"),
        compared(*[diff(f"f{n}.py", "@@ -1 +1 @@\n-a\n+b") for n in range(300)]),
        {"status": "ahead", "files": [{"status": "modified"}]},
        [],
    ],
)
def test_an_answer_that_tells_too_little_marks_nothing_fixed(answer):
    api = FakeApi()
    run(api, report([finding("f1.py", 1)]), report())
    api.compared = answer
    assert "Fixed" not in run(api, report(), report(), head=NEXT)


def test_a_file_without_a_diff_marks_nothing_fixed():
    api = FakeApi()
    run(api, report([finding("big.py", 1)]), report())
    api.compared = compared(diff("big.py", changes=9000))
    body = run(api, report(), report(), head=NEXT)
    assert "Fixed" not in body and f"/blob/{SHA}/big.py#L1)" in body


def test_a_removed_file_fixes_its_findings():
    api = FakeApi()
    run(api, report([finding("old.py", 3)]), report())
    api.compared = compared(diff("old.py", "@@ -1,5 +0,0 @@\n-a", status="removed"))
    assert "### Fixed (1)" in run(api, report(), report(), head=NEXT)


def test_a_renamed_file_takes_its_findings_along():
    api = FakeApi()
    run(api, report([finding("old.py", 3)]), report())
    api.compared = compared(diff("new.py", status="renamed", previous_filename="old.py", changes=0))
    body = run(api, report(), report(), head=NEXT)
    assert f"(https://github.com/o/r/blob/{NEXT}/new.py#L3)" in body and "Fixed" not in body


def test_a_rerun_on_the_same_commit_compares_nothing():
    api = FakeApi()
    run(api, report([finding("a.py", 11)]), report())
    body = run(api, report(), report())
    assert not [c for c in api.calls if c[0] == "compare"]
    assert "### Not repeated by the latest review (1)" in body
    assert f"/blob/{SHA}/a.py#L11)" in body


def test_fixed_stays_fixed_and_counted_on_later_runs():
    api = FakeApi()
    run(api, report([finding("a.py", 11)]), report())
    api.compared = compared(diff("a.py", "@@ -10,3 +10,3 @@\n ctx\n-old\n+new\n ctx"))
    run(api, report(), report(), head=NEXT)
    api.compared = compared()
    body = run(api, report([finding("b.py", 1)]), report(), head=LAST)
    assert "### Fixed (1)" in body and "fixed in 1556615" in body
    assert "### To check (1)" in body
    assert read_marker(body) == {"claude": 2, "luna": 0, "both": 0}


def test_a_fixed_finding_reported_again_is_open_again():
    api = FakeApi()
    run(api, report([finding("a.py", 11)]), report())
    api.compared = compared(diff("a.py", "@@ -10,3 +10,3 @@\n ctx\n-old\n+new\n ctx"))
    run(api, report(), report(), head=NEXT)
    api.compared = compared()
    body = run(api, report([finding("a.py", 12)]), report(), head=LAST)
    assert "### To check (1)" in body and "Fixed" not in body


def test_a_reviewer_silent_now_keeps_its_earlier_findings_and_counts():
    api = FakeApi()
    run(api, report(), report([finding("a.py", 1)]))
    body = run(api, report(), None, head=NEXT)
    assert "Luna gave no usable answer this time." in body
    assert "### Not repeated by the latest review (1)" in body
    assert read_marker(body) == {"claude": 0, "luna": 1, "both": 0}


def test_no_answer_keeps_the_earlier_findings_and_marks_none_fixed(tmp_path, monkeypatch):
    api = FakeApi()
    before = run(api, report([finding("a.py", 11, text="Off by one."), ROADMAP]), report())
    # The next push changes the lines of a.py:11, but nobody reviews it.
    api.compared = compared(diff("a.py", "@@ -10,3 +10,3 @@\n ctx\n-old\n+new\n ctx"))
    monkeypatch.setattr(post_findings, "GhApi", lambda **_: api)
    argv = argv_for(tmp_path / "a.json", tmp_path / "b.json", "--pr", "7", "--repo", "o/r",
                    "--head-sha", NEXT)
    assert main(argv) == 0
    body = api.comments[0]["body"]
    assert [call[0] for call in api.calls if call[0] != "compare"] == ["create", "update"]
    assert "Neither reviewer gave a usable answer for 1556615." in body
    assert "### Not repeated by the latest review (2)" in body and "Fixed" not in body
    assert read_marker(body) == read_marker(before) == {"claude": 2, "luna": 0, "both": 0}
    # The hidden line is the earlier one: the next review compares from the last reviewed
    # commit, so it can still mark a.py:11 fixed.
    assert read_state(body) == read_state(before)
    api.compared = compared(diff("a.py", "@@ -10,3 +10,3 @@\n ctx\n-old\n+new\n ctx"))
    after = run(api, report(), report(), head=LAST)
    assert ("compare", SHA, LAST) in api.calls
    assert "Off by one. *(Claude, fixed in 9999999)*" in after


def test_a_long_history_is_cut_but_still_counted():
    fixed = [Item(finding(f"f{n}.py", 1), ["claude"], SHA, SHA, SHA) for n in range(30)]
    earlier = Earlier(SHA, ["claude"], fixed, {"claude": 0, "luna": 0, "both": 0})
    claude = report([finding("x.py", 1), finding("y.py", 1)])
    body = review_body({"claude": claude, "luna": None}, "o/r", NEXT, earlier, {})
    assert "### To check (2)" in body and "### Fixed (28)" in body
    assert "2 older findings are left out" in body
    assert "f0.py" not in visible(body) and "f29.py" in body
    assert read_marker(body) == {"claude": 32, "luna": None, "both": 0}
    state = read_state(body)
    assert len(state.items) == 30 and state.dropped["claude"] == 2


# --- The hidden line ---


def test_the_hidden_line_reads_back():
    rep = report([finding("a-b.py", 4, "rule", "Text --> @bob #12 https://e.x/a <b>&")])
    body = body_of(rep, report())
    (line,) = [x for x in body.splitlines() if x.startswith("<!-- kitden-sdlc:state ")]
    inner = line.removeprefix("<!-- kitden-sdlc:state ").removesuffix(" -->")
    assert not set("<>&-@#/") & set(inner)
    state = read_state(body)
    assert state.head == SHA and state.answered == ["claude", "luna"]
    (item,) = state.items
    assert item.finding == rep.findings[0] and item.by == ["claude"]
    assert item.seen == item.at == SHA and item.fixed == ""
    assert body.endswith("both=0 -->")


def _state_data():
    body = body_of(report([finding()]), report())
    return json.loads(body.split("kitden-sdlc:state ", 1)[1].split(" -->", 1)[0])


def _body_with(data):
    return f"<!-- kitden-sdlc:state {json.dumps(data)} -->"


@pytest.mark.parametrize(
    "change",
    [
        lambda d: d.update(head="not-a-sha"),
        lambda d: d.update(answered=["gpt"]),
        lambda d: d.update(extra=1),
        lambda d: d.update(items={}),
        lambda d: d.update(items=d["items"] * 31),
        lambda d: d.update(dropped={"claude": -1, "luna": 0, "both": 0}),
        lambda d: d.update(dropped={"claude": True, "luna": 0, "both": 0}),
        lambda d: d["items"][0].update(by=[]),
        lambda d: d["items"][0].update(by=["claude", "claude"]),
        lambda d: d["items"][0].update(by=["someone"]),
        lambda d: d["items"][0].update(seen="main"),
        lambda d: d["items"][0].update(fixed="HEAD"),
        lambda d: d["items"][0].update(line=0),
        lambda d: d["items"][0].update(kind="style"),
        lambda d: d["items"][0].pop("at"),
    ],
)
def test_a_hidden_line_that_does_not_fit_is_not_read(change):
    data = _state_data()
    assert read_state(_body_with(data)) is not None
    change(data)
    assert read_state(_body_with(data)) is None


def test_broken_or_missing_hidden_line_is_not_read():
    assert read_state("<!-- kitden-sdlc:state {not json} -->") is None
    assert read_state("No state here.") is None


def test_a_comment_from_before_the_hidden_line_starts_fresh(capsys):
    api = FakeApi()
    old = "**Agent review**\n\nx\n\n<!-- kitden-sdlc:review claude=1 luna=0 both=0 -->"
    api.comments.append({"id": 9, "body": old, "user": dict(BOT_USER)})
    body = run(api, report(), report(), head=NEXT)
    assert "No problems found." in body and api.calls[-1][0] == "update"
    assert "no earlier findings" in capsys.readouterr().out


def test_a_persons_comment_with_a_hidden_line_is_not_read():
    api = FakeApi()
    fake = body_of(report([finding("a.py", 1, text="Planted.")]), report())
    api.comments.append({"id": 9, "body": fake, "user": {"login": "someone"}})
    body = run(api, report(), report(), head=NEXT)
    assert "Planted." not in body


def test_a_secret_in_the_hidden_line_is_refused():
    data = _state_data()
    data["items"][0]["text"] = "ghp_" + "a" * 36
    earlier = read_state(_body_with(data))
    with pytest.raises(SecretLikeError):
        review_body({"claude": report(), "luna": None}, "o/r", NEXT, earlier, {})


# --- Reading a diff ---


def test_parse_patch_follows_lines_and_marks_what_changed():
    patch = (
        "@@ -2,4 +2,5 @@\n"
        " two\n"
        "-three\n"
        "+THREE\n"
        "+three and a half\n"
        " four\n"
        " five\n"
        "\\ No newline at end of file\n"
        "@@ -20,2 +21,0 @@\n"
        "-twenty\n"
        "-twenty-one\n"
    )
    change = parse_patch("a.py", patch)
    assert change.touched == {3, 4, 20, 21}  # two is only context
    assert [change.new_line(n) for n in (1, 2, 4, 5, 10)] == [1, 2, 5, 6, 11]
    assert change.new_line(30) == 29
    assert change.touches(5) and not change.touches(10)


def test_file_changes_names_files_by_their_old_name():
    changes = file_changes(
        compared(
            diff("new.py", "@@ -1 +1 @@\n-a\n+b", status="renamed", previous_filename="old.py")
        )
    )
    assert set(changes) == {"old.py"} and changes["old.py"].path == "new.py"
    assert file_changes(compared(status="identical")) == {}


def test_gh_api_compare_uses_the_read_token(monkeypatch):
    run_ = FakeRun('{"status": "ahead", "files": []}')
    calls = []
    monkeypatch.setattr(
        post_findings.subprocess,
        "run",
        lambda command, **kw: calls.append(kw.get("env")) or run_(command, **kw),
    )
    assert GhApi(read_token="read").compare("o/r", "a1b2c3d", "d4e5f6a") == {
        "status": "ahead",
        "files": [],
    }
    assert run_.commands[0][2] == "repos/o/r/compare/a1b2c3d...d4e5f6a"
    assert calls[0]["GH_TOKEN"] == "read"
    GhApi().create_issue_comment("o/r", 7, "hi")
    assert calls[1] is None  # posting keeps the job's GH_TOKEN


def test_gh_api_pull_text_is_the_title_and_the_body(monkeypatch):
    run_ = FakeRun('{"title": "Fix it", "body": "Some words."}')
    envs = []
    monkeypatch.setattr(
        post_findings.subprocess,
        "run",
        lambda command, **kw: envs.append(kw.get("env")) or run_(command, **kw),
    )
    assert GhApi(read_token="read").pull_text("o/r", 7) == "Fix it\nSome words."
    assert run_.commands[0][2] == "repos/o/r/pulls/7"
    assert envs[0]["GH_TOKEN"] == "read"
    run_.result.stdout = '{"title": "Fix it", "body": null}'
    assert GhApi().pull_text("o/r", 7) == "Fix it\n"


def test_gh_api_pull_text_gives_none_when_gh_fails(monkeypatch):
    def fail(command, **kwargs):
        raise subprocess.CalledProcessError(1, command)

    monkeypatch.setattr(post_findings.subprocess, "run", fail)
    assert GhApi().pull_text("o/r", 7) is None
    monkeypatch.setattr(post_findings.subprocess, "run", FakeRun("not json"))
    assert GhApi().pull_text("o/r", 7) is None


def test_gh_api_compare_gives_none_when_gh_fails(monkeypatch):
    def fail(command, **kwargs):
        raise subprocess.CalledProcessError(1, command)

    monkeypatch.setattr(post_findings.subprocess, "run", fail)
    assert GhApi().compare("o/r", "a1b2c3d", "d4e5f6a") is None


def test_main_keeps_an_earlier_finding(tmp_path, monkeypatch):
    api = FakeApi()
    run(api, report([ROADMAP]), report())
    api.compared = compared()
    made = []
    monkeypatch.setattr(post_findings, "GhApi", lambda **kw: made.append(kw) or api)
    monkeypatch.setenv("GH_READ_TOKEN", "read")
    empty = write(tmp_path, {"summary": "Fine.", "findings": []})
    argv = argv_for(empty, empty, "--pr", "7", "--repo", "o/r", "--head-sha", NEXT)
    assert main(argv) == 0
    assert made == [{"read_token": "read"}]
    body = api.comments[0]["body"]
    assert "### Not repeated by the latest review (1)" in body
    assert read_marker(body) == {"claude": 1, "luna": 0, "both": 0}
