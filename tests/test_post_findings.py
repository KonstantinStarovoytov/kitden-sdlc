import json
from pathlib import Path

import pytest

import post_findings
from post_findings import (
    Finding,
    GhApi,
    Report,
    SecretLikeError,
    load_report,
    main,
    marker,
    merge,
    one_line,
    post,
    quiet_mentions,
    read_marker,
    refuse_secret_like,
    review_body,
)

FIXTURE = Path(__file__).parent / "fixtures" / "findings_ok.json"
ROOT = Path(__file__).parent.parent
SCHEMA = ROOT / "schemas" / "findings.schema.json"
SKILL = ROOT / "plugins" / "kitden-sdlc" / "skills" / "review-kitden" / "SKILL.md"
SHA = "abcdef1234567890"
MODELS = {"claude": "claude-opus-5", "luna": "gpt-6-luna"}
WJ = "\u2060"


BOT_USER = {"login": "github-actions[bot]", "type": "Bot"}


class FakeApi:
    """Records calls and keeps the comments it was given."""

    def __init__(self):
        self.comments: list[dict] = []
        self.calls: list[tuple] = []

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


def finding(path="a.py", line=1, kind="bug", text="Something is wrong."):
    return Finding(path=path, line=line, kind=kind, text=text)


def report(findings=(), new_surface=(), summary="All fine."):
    return Report(summary=summary, new_surface=list(new_surface), findings=list(findings))


def body_of(claude=None, luna=None, repo="o/r"):
    return review_body({"claude": claude, "luna": luna}, MODELS, repo, SHA)


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
    assert len(rep.new_surface) == 1


@pytest.mark.parametrize(
    "change",
    [
        lambda d: d.pop("new_surface"),
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


def test_first_line_names_both_reviewers_models_and_commit():
    first = body_of(report(), report()).splitlines()[0]
    assert first == (
        "**Agent review** · automated, by Claude (claude-opus-5) and Luna (gpt-6-luna)"
        " · commit abcdef1"
    )


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
    assert "**To check (3)**" in body
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
    body = body_of(report([finding(text=text)], summary=text, new_surface=[text]))
    assert body.count(plain) == 3 and text not in body
    assert read_marker(body) == {"claude": 1, "luna": None, "both": 0}


@pytest.mark.parametrize(
    "path", ["../../evil/repo/blob/main/x", "a/../b.py", "/etc/passwd", "a b.py"]
)
def test_an_unsafe_path_gets_no_link(path):
    body = body_of(report([finding(path=path)]))
    assert "](https://" not in body


def test_mentions_are_quieted_in_summary_text_and_new_surface():
    rep = report(
        [finding(text="Use @pytest.fixture here.")],
        new_surface=["Asks @owner", "second"],
        summary="@someone look",
    )
    body = body_of(rep)
    assert f"@{WJ}someone" in body and f"@{WJ}pytest.fixture" in body and f"@{WJ}owner" in body
    assert "@someone" not in body and "@pytest" not in body and "@owner" not in body
    assert "**New for users:** " in body and "; second" in body


def test_quiet_mentions_leaves_the_rest():
    assert quiet_mentions("a@b.c @ alone @@x") == f"a@b.c @ alone @@{WJ}x"


def test_one_line_joins_and_quiets():
    assert one_line("a\n\n b  @c") == f"a b @{WJ}c"


def test_a_silent_reviewer_is_named():
    assert "Luna gave no usable answer this time." in body_of(report(), None)
    assert "Claude gave no usable answer this time." in body_of(None, report())
    assert "Claude and Luna gave no usable answer this time." in body_of(None, None)
    assert "gave no usable answer" not in body_of(report(), report())


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
    text = marker({"claude": claude, "luna": luna}, items)
    assert text == "<!-- kitden-sdlc:review claude=1 luna=1 both=1 -->"
    assert read_marker(f"Text.\n\n{text}\n") == {"claude": 1, "luna": 1, "both": 1}


def test_marker_has_x_for_a_silent_reviewer():
    text = marker({"claude": report(), "luna": None}, [])
    assert text == "<!-- kitden-sdlc:review claude=0 luna=x both=0 -->"
    assert read_marker(text) == {"claude": 0, "luna": None, "both": 0}


def test_marker_not_at_the_end_is_not_read():
    text = marker({"claude": report(), "luna": report()}, [])
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


def test_post_refuses_a_secret_and_calls_nothing():
    api = FakeApi()
    with pytest.raises(SecretLikeError):
        post(api, "o/r", 7, "token ghp_" + "a" * 36)
    assert api.calls == []


# --- main ---


def argv_for(claude, luna, *extra):
    return ["--claude", str(claude), "--luna", str(luna), *extra]


def test_main_with_both_files_missing_posts_and_prints_nothing(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(post_findings, "GhApi", lambda: pytest.fail("no GitHub"))
    argv = argv_for(tmp_path / "a.json", tmp_path / "b.json", "--pr", "7")
    assert main(argv) == 0
    assert capsys.readouterr().out.count("::warning::") == 2


def test_main_with_one_file_missing_still_prints_a_body(tmp_path, capsys):
    argv = argv_for(FIXTURE, tmp_path / "nope.json", "--dry-run", "--head-sha", SHA)
    assert main(argv) == 0
    out = capsys.readouterr().out
    assert "src/sync.py:42" in out
    assert "Luna gave no usable answer this time." in out
    assert out.rstrip().endswith("luna=x both=0 -->")


def test_main_posts_with_the_api(tmp_path, monkeypatch):
    api = FakeApi()
    monkeypatch.setattr(post_findings, "GhApi", lambda: api)
    assert main(argv_for(FIXTURE, FIXTURE, "--pr", "7", "--repo", "o/r")) == 0
    assert [call[0] for call in api.calls] == ["create"]
    assert "**To check (2)**" in api.comments[0]["body"]


def test_main_needs_pr_without_dry_run():
    with pytest.raises(SystemExit):
        main(argv_for(FIXTURE, FIXTURE))


def test_main_refuses_a_secret_and_exits_one(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(post_findings, "GhApi", lambda: pytest.fail("no GitHub"))
    bad = write(tmp_path, {"summary": "ok ghp_" + "a" * 36, "new_surface": [], "findings": []})
    assert main(argv_for(bad, FIXTURE, "--pr", "7")) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "looked like a secret" in captured.err


def test_dry_run_with_a_secret_exits_one(tmp_path, capsys):
    bad = write(tmp_path, {"summary": "sk-ant-oops-" + "x" * 20, "new_surface": [], "findings": []})
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
        report(new_surface=[secret]),
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
