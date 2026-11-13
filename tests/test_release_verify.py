import json

import pytest

from release_verify import (
    DOCS_TESTS_DEFAULT,
    docs_tests,
    main,
    notes_problems,
    readme_problems,
    tool_problems,
    verdict,
)

CONTEXT = {"prs": [{"number": 70, "author": "kostya"}, {"number": 71, "author": "app/dependabot"}]}
DOCS = "Kitden's docs tests"
NOTES = "docs/releases/v0.9.0.md"


def test_docs_tests_takes_plain_test_paths_only():
    assert docs_tests(DOCS_TESTS_DEFAULT)[0] == "tests/unit/test_docs_words.py"
    for bad in ("", "   ", "tests/../x.py", "src/x.py", "tests/a.py;rm", "tests/a.py " * 13):
        with pytest.raises(ValueError):
            docs_tests(bad)


def test_every_pull_request_and_author_must_be_named(tmp_path):
    notes = "([#70](https://github.com/o/kitden/pull/70)) @kostya, see issue #12 and #70 again"
    problems = notes_problems(notes, CONTEXT, tmp_path, "0.9.0")
    assert problems == [
        "docs/releases/v0.9.0.md: pull request #71 is not named",
        "docs/releases/v0.9.0.md: author @dependabot is not named",
    ]


def test_bot_names_are_cut_down_to_the_login(tmp_path):
    context = {"prs": [{"number": 5, "author": "dependabot[bot]"}]}
    assert notes_problems("#5 by @dependabot", context, tmp_path, "0.9.0") == []


def test_a_linked_pull_request_outside_the_range_is_a_problem(tmp_path):
    notes = "#70 @kostya #71 @dependabot https://github.com/o/kitden/pull/99"
    assert notes_problems(notes, CONTEXT, tmp_path, "0.9.0") == [
        "docs/releases/v0.9.0.md: pull request #99 is not in this release"
    ]


def test_a_link_to_a_missing_file_is_a_problem(tmp_path):
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs/here.md").write_text("x")
    base = "https://github.com/o/kitden/blob/v0.9.0/"
    notes = f"#70 @kostya #71 @dependabot [a]({base}docs/here.md#top) [b]({base}docs/gone.md)"
    assert notes_problems(notes, CONTEXT, tmp_path, "0.9.0") == [
        "docs/releases/v0.9.0.md: link to docs/gone.md has no file"
    ]


def test_a_link_cannot_leave_the_checkout(tmp_path):
    root = tmp_path / "kitden"
    root.mkdir()
    (tmp_path / "secret.txt").write_text("x")
    notes = "https://github.com/o/kitden/blob/v0.9.0/../secret.txt "
    context = {"prs": []}
    assert notes_problems(notes, context, root, "0.9.0") == [
        "docs/releases/v0.9.0.md: link to ../secret.txt has no file"
    ]


def test_a_readme_picture_must_exist(tmp_path):
    (tmp_path / "docs/images/readme").mkdir(parents=True)
    (tmp_path / "docs/images/readme/ok.png").write_bytes(b"x")
    readme = (
        '<img src="docs/images/readme/ok.png">\n'
        '<source srcset="docs/images/readme/x.png" media="(prefers-color-scheme: dark)">\n'
    )
    assert readme_problems(readme, tmp_path) == [
        "README.md: picture docs/images/readme/x.png is missing"
    ]
    assert readme_problems("no pictures", tmp_path) == []


def test_failed_tests_become_one_problem_each():
    out = "FAILED tests/unit/test_docs_words.py::test_readme_is_short - assert 126 <= 125\n1 failed"
    assert tool_problems(DOCS, out, 1) == [
        "tests/unit/test_docs_words.py: Kitden's test test_readme_is_short fails: assert 126 <= 125"
    ]
    assert tool_problems(DOCS, out, 0) == []


def test_a_run_that_did_not_start_is_one_problem():
    out = "ERROR collecting tests/unit/test_hero.py\n\nImportError: no module x\n\n"
    assert tool_problems(DOCS, out, 2) == [
        "Kitden's docs tests did not run (status 2): ImportError: no module x"
    ]


def test_the_release_check_gives_one_problem_per_line():
    out = "version is 0.9.0 in pyproject but 0.8.0 in server.json\n\nROADMAP.md is stale\n"
    assert tool_problems("Kitden's release check", out, 1) == [
        "Kitden's release check: version is 0.9.0 in pyproject but 0.8.0 in server.json",
        "Kitden's release check: ROADMAP.md is stale",
    ]
    assert tool_problems("Kitden's release check", out, 0) == []


def test_an_empty_range_is_no_problem(tmp_path):
    (tmp_path / "docs/releases").mkdir(parents=True)
    (tmp_path / "docs/releases/v0.9.0.md").write_text("Nothing changed.\n")
    (tmp_path / "README.md").write_text("hello\n")
    problems, facts = verdict(tmp_path, {"prs": []}, "0.9.0", ("", 0), ("", 0))
    assert problems == []
    assert (facts["prs_named"], facts["prs_total"]) == (0, 0)
    assert (facts["authors_named"], facts["authors_total"]) == (0, 0)


def test_a_missing_notes_file_is_one_problem(tmp_path):
    (tmp_path / "README.md").write_text("hello\n")
    problems, _ = verdict(tmp_path, CONTEXT, "0.9.0", ("", 0), ("", 0))
    assert problems == [f"{NOTES}: missing"]


def test_verdict_writes_both_files(tmp_path):
    root = tmp_path / "kitden"
    (root / "docs/releases").mkdir(parents=True)
    (root / "docs/releases/v0.9.0.md").write_text("#70 by @kostya, #71\n")
    (root / "README.md").write_text("one\ntwo\nthree\n")
    files = {
        "context.json": json.dumps(CONTEXT),
        "tests.txt": "FAILED tests/unit/test_hero.py::test_hero - boom\n",
        "check.txt": "",
    }
    for name, text in files.items():
        (tmp_path / name).write_text(text)
    out = tmp_path / "out"

    code = main(
        [
            "verdict", str(root),
            "--context", str(tmp_path / "context.json"),
            "--version", "0.9.0",
            "--tests-output", str(tmp_path / "tests.txt"),
            "--tests-status", "1",
            "--check-output", str(tmp_path / "check.txt"),
            "--check-status", "0",
            "--out", str(out),
        ]
    )  # fmt: skip

    assert code == 0
    assert (out / "problems.md").read_text() == (
        f"- {NOTES}: author @dependabot is not named\n"
        "- tests/unit/test_hero.py: Kitden's test test_hero fails: boom\n"
    )
    assert json.loads((out / "facts.json").read_text()) == {
        "readme_lines": 3,
        "docs_tests": "fail",
        "release_check": "pass",
        "prs_named": 2,
        "prs_total": 2,
        "authors_named": 1,
        "authors_total": 2,
        "links": "ok",
    }


def test_problems_file_is_empty_when_all_is_well(tmp_path, capsys):
    (tmp_path / "docs/releases").mkdir(parents=True)
    (tmp_path / "docs/releases/v0.9.0.md").write_text("fine\n")
    (tmp_path / "README.md").write_text("fine\n")
    (tmp_path / "c.json").write_text('{"prs": []}')
    (tmp_path / "t.txt").write_text("")
    out = tmp_path / "out"
    args = ["--tests-output", str(tmp_path / "t.txt"), "--tests-status", "0"]
    args += ["--check-output", str(tmp_path / "t.txt"), "--check-status", "0"]
    code = main(["verdict", str(tmp_path), "--context", str(tmp_path / "c.json"),
                 "--version", "0.9.0", *args, "--out", str(out)])  # fmt: skip
    assert code == 0
    assert (out / "problems.md").read_text() == ""


def test_tests_command_prints_one_path_per_line(capsys):
    assert main(["tests", "tests/a.py tests/b/c.py"]) == 0
    assert capsys.readouterr().out == "tests/a.py\ntests/b/c.py\n"
    assert main(["tests", "../x.py"]) == 1
    assert "../x.py" in capsys.readouterr().out


def test_a_nul_in_a_link_path_does_not_stop_the_verdict(tmp_path):
    root = tmp_path / "kitden"
    (root / "docs/releases").mkdir(parents=True)
    (root / "docs/releases/v0.9.0.md").write_text("see blob/v0.9.0/docs/a\x00b.md here\n")
    (root / "README.md").write_text('<img src="docs/images/a\x00b.png">\n')
    (tmp_path / "c.json").write_text('{"prs": []}')
    (tmp_path / "t.txt").write_text("")
    out = tmp_path / "out"
    code = main(["verdict", str(root), "--context", str(tmp_path / "c.json"),
                 "--version", "0.9.0", "--tests-output", str(tmp_path / "t.txt"),
                 "--tests-status", "0", "--check-output", str(tmp_path / "t.txt"),
                 "--check-status", "0", "--out", str(out)])  # fmt: skip
    assert code == 0
    assert len((out / "problems.md").read_text().splitlines()) == 2
    assert json.loads((out / "facts.json").read_text())["links"] == "broken"


def test_link_problems_are_one_short_line(tmp_path):
    long_path = "docs/" + "x" * 1000 + ".md"
    notes = f"blob/v0.9.0/{long_path} and blob/v0.9.0/docs/odd name\x07.md"
    problems = notes_problems(notes, {"prs": []}, tmp_path, "0.9.0")
    picture = readme_problems(f'<img src="docs/images/{"y" * 1000}.png">', tmp_path)
    assert len(problems) == 2
    for problem in [*problems, *picture]:
        assert len(problem) <= 303
        assert "\n" not in problem
    assert problems[0].endswith("...")
    assert picture[0].endswith("...")
