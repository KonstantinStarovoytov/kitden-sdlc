import json
import subprocess
from pathlib import Path

import pytest

from release_context import (
    check_version,
    collect,
    guard,
    last_tag,
    main,
    pr_numbers,
)


def git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(root), *args], check=True, capture_output=True, text=True
    ).stdout


def commit(root: Path, name: str, text: str, message: str) -> None:
    (root / name).write_text(text)
    git(root, "add", name)
    git(root, "commit", "-q", "-m", message)


def make_repo(tmp_path: Path) -> Path:
    root = tmp_path / "kitden"
    root.mkdir()
    git(root, "init", "-q", "-b", "main")
    git(root, "config", "user.name", "Test")
    git(root, "config", "user.email", "test@example.com")
    (root / "pyproject.toml").write_text('[project]\nname = "kitden"\nversion = "0.8.0"\n')
    commit(root, "a.txt", "a\n", "An old change (#1)")
    git(root, "tag", "v0.8.0")
    commit(root, "b.txt", "b\n", "Add a thing (#2)")
    commit(root, "c.txt", "c\n", "Merge pull request #3 from someone/branch")
    commit(root, "d.txt", "d\n", "A push with no pull request")
    commit(root, "e.txt", "e\n", "fix(dock): name the client (#4) (#5)")
    return root


def fake_gh(calls: list[list[str]]):
    def gh(args: list[str]) -> str:
        calls.append(args)
        number = int(args[2])
        return json.dumps(
            {
                "number": number,
                "title": f"Title {number}",
                "body": f"Body {number}",
                "labels": [{"name": "bug", "color": "red"}],
                "author": {"login": f"user{number}", "is_bot": False},
                "additions": 3,
                "deletions": 1,
                "files": [{"path": f"src/f{number}.py", "additions": 3, "deletions": 1}],
            }
        )

    return gh


def test_collect_lists_prs_since_tag(tmp_path):
    root = make_repo(tmp_path)
    calls: list[list[str]] = []
    context = collect(root, "v0.8.0", fake_gh(calls), version="0.9.0")

    assert set(context) == {"version", "since_tag", "log", "prs", "diffstat"}
    assert context["version"] == "0.9.0"
    assert context["since_tag"] == "v0.8.0"
    # Oldest first; #1 is before the tag; the last (#N) of a subject is the pull request.
    assert [pr["number"] for pr in context["prs"]] == [2, 3, 5]
    assert all(call[:2] == ["pr", "view"] for call in calls)
    assert context["prs"][0] == {
        "number": 2,
        "title": "Title 2",
        "body": "Body 2",
        "labels": ["bug"],
        "author": "user2",
        "additions": 3,
        "deletions": 1,
        "files": ["src/f2.py"],
    }
    assert "Add a thing (#2)" in context["log"]
    assert "A push with no pull request" in context["log"]
    assert "An old change" not in context["log"]
    assert "b.txt" in context["diffstat"] and "a.txt" not in context["diffstat"]


def test_collect_cuts_a_long_body(tmp_path):
    root = make_repo(tmp_path)

    def gh(args: list[str]) -> str:
        return json.dumps(
            {
                "number": int(args[2]),
                "title": "t",
                "body": "x" * 50_000,
                "labels": [],
                "author": {"login": "u"},
                "additions": 0,
                "deletions": 0,
                "files": [],
            }
        )

    context = collect(root, "v0.8.0", gh)
    assert context["version"] == ""
    assert len(context["prs"][0]["body"]) < 11_000
    assert context["prs"][0]["body"].endswith("[cut]")


def test_pr_numbers_are_unique_and_in_order():
    subjects = ["Merge pull request #7 from a/b", "Thing (#3)", "Again (#3)", "No number"]
    assert pr_numbers(subjects) == [7, 3]


def test_last_tag(tmp_path):
    root = make_repo(tmp_path)
    assert last_tag(root) == "v0.8.0"


@pytest.mark.parametrize("version", ["", "0.9.0", "0.8.1"])
def test_check_version_allows_empty_or_next(version):
    assert check_version(version, "0.8.0") is None


@pytest.mark.parametrize("version", ["1.0.0", "0.10.0", "v0.9.0", "0.9.0\n", "0.9", "0.8.0"])
def test_check_version_refuses_others(version):
    assert check_version(version, "0.8.0")


def pr(head: str, login: str, bot: bool) -> dict:
    return {"headRefName": head, "author": {"login": login, "is_bot": bot}}


def test_guard_stops_when_switch_off():
    assert "switch" in guard([], enabled=False)


def test_guard_stops_on_an_open_release_pr():
    reason = guard([pr("prepare-v0.9.0", "app/kitden-beacon", True)], enabled=True)
    assert "prepare-v0.9.0" in reason


def test_guard_ignores_a_fork_branch_named_like_a_release():
    fork = pr("prepare-v0.9.0", "stranger", False) | {"isCrossRepository": True}
    assert guard([fork], enabled=True) is None


def test_guard_stops_at_three_bot_prs():
    prs = [pr(f"b{n}", "app/lantern", True) for n in range(3)]
    assert "3" in guard(prs, enabled=True)


def test_guard_goes_with_two_bot_prs_and_people():
    prs = [pr("b1", "app/lantern", True), pr("b2", "dependabot", True)]
    prs += [pr(f"h{n}", "someone", False) for n in range(5)]
    assert guard(prs, enabled=True) is None


def test_guard_counts_bot_logins_without_the_flag():
    prs = [pr(f"b{n}", f"x{n}[bot]", False) for n in range(3)]
    assert guard(prs, enabled=True)


def test_guard_cli(tmp_path, capsys):
    path = tmp_path / "prs.json"
    path.write_text(json.dumps([pr("prepare-v1.0.0", "x", False)]))
    assert main(["guard", str(path), "--enabled", "true"]) == 0
    assert "prepare-v1.0.0" in capsys.readouterr().out
    path.write_text("[]")
    assert main(["guard", str(path), "--enabled", "true"]) == 0
    assert capsys.readouterr().out == ""
    assert main(["guard", str(path), "--enabled", "false"]) == 0
    assert "switch" in capsys.readouterr().out


def test_collect_cli_refuses_a_bad_version(tmp_path, capsys):
    root = make_repo(tmp_path)
    out = tmp_path / "context.json"
    assert main(["collect", str(root), "--version", "2.0.0", "--out", str(out)]) == 1
    assert "0.9.0" in capsys.readouterr().out
    assert not out.exists()
