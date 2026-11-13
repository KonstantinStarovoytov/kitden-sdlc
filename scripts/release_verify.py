"""Check the release-prep agent's work before the release pull request opens.

No model runs here. The notes and the README were written by one, and the test output comes
from running code the agent may have touched, so all of it is only data. Commands:

  release_verify.py tests VALUE
      Prints the Kitden docs test paths in VALUE, one per line. Exit 1 with the reason if
      VALUE is not a short list of plain test paths.
  release_verify.py verdict ROOT --context F --version X.Y.Z --tests-output F --tests-status N
                    --check-output F --check-status N --out DIR
      Checks the notes and the README in the Kitden checkout ROOT, and the output of Kitden's
      docs tests and of scripts/release_check.py. Writes DIR/problems.md (one "- " line per
      problem, empty when there is none) and DIR/facts.json. Exit 0 with or without problems.
"""

import argparse
import json
import re
import sys
from pathlib import Path

DOCS_TESTS_DEFAULT = (
    "tests/unit/test_docs_words.py tests/unit/test_hero.py "
    "tests/unit/test_plugin_package.py tests/unit/test_release_files.py"
)
DOCS_TESTS_NAME = "Kitden's docs tests"
RELEASE_CHECK_NAME = "Kitden's release check"
TEST_PATH = re.compile(r"tests/[A-Za-z0-9_/-]+\.py\Z", re.ASCII)
TESTS_MAX = 12
LINE_MAX = 300

# A pull request is named by its link or by "#N". A bare "#N" may be an issue, so only a link
# can show a pull request that is not in the release.
PR_LINK = re.compile(r"/pull/(\d+)")
PR_MENTION = re.compile(r"(?<![\w&])#(\d+)")
BLOB_LINK = re.compile(r"blob/v{version}/([^)#\s]+)")
PICTURE = re.compile(r'\b(?:src|srcset)="(docs/images/[^"\s,]+)')
FAILED = re.compile(r"FAILED (\S+?)::(\S+)(?: - (.*))?\Z")


def docs_tests(value: str) -> list[str]:
    """The test paths in `value`. Raises ValueError unless there are 1 to 12 plain paths."""
    words = value.split()
    if not words:
        raise ValueError("at least one test path is required")
    if len(words) > TESTS_MAX:
        raise ValueError(f"more than {TESTS_MAX} test paths")
    for word in words:
        if ".." in word or not TEST_PATH.match(word):
            raise ValueError(f"{word!r} is not a plain test path under tests/")
    return words


def _line(text: str) -> str:
    """One short line of data, safe to put in a list."""
    text = " ".join(text.split())
    return text if len(text) <= LINE_MAX else text[:LINE_MAX] + "..."


def _login(author: str) -> str:
    author = author.removeprefix("app/")
    return author.removesuffix("[bot]")


def _is_file(root: Path, path: str) -> bool:
    """True when `path` is a file under `root`; false for anything that leaves it."""
    target = (root / path).resolve()
    return target.is_relative_to(root.resolve()) and target.is_file()


def _broken_links(notes: str, root: Path, version: str, name: str) -> list[str]:
    pattern = re.compile(BLOB_LINK.pattern.format(version=re.escape(version)))
    paths = dict.fromkeys(pattern.findall(notes))
    return [f"{name}: link to {path} has no file" for path in paths if not _is_file(root, path)]


def _broken_pictures(readme: str, root: Path) -> list[str]:
    paths = dict.fromkeys(PICTURE.findall(readme))
    return [f"README.md: picture {path} is missing" for path in paths if not _is_file(root, path)]


def _pr_counts(notes: str, context: dict) -> tuple[list[int], set[int]]:
    """The numbers of the release's pull requests that the notes do not name, and the numbers
    the notes link as pull requests that are not in the release."""
    numbers = [pr["number"] for pr in context["prs"]]
    linked = {int(n) for n in PR_LINK.findall(notes)}
    named = linked | {int(n) for n in PR_MENTION.findall(notes)}
    return [n for n in numbers if n not in named], linked - set(numbers)


def _authors(context: dict) -> list[str]:
    return list(dict.fromkeys(_login(pr["author"]) for pr in context["prs"]))


def _unnamed_authors(notes: str, context: dict) -> list[str]:
    def named(login: str) -> bool:
        return (
            re.search(rf"(?<![\w-])@{re.escape(login)}(?![\w-])", notes, re.IGNORECASE) is not None
        )

    return [login for login in _authors(context) if not named(login)]


def notes_problems(notes: str, context: dict, root: Path, version: str) -> list[str]:
    """What is wrong with the release notes: a pull request or an author of the release that
    they do not name, a pull request link from outside the release, a link to a file that
    Kitden does not have at this version."""
    name = f"docs/releases/v{version}.md"
    unnamed, strangers = _pr_counts(notes, context)
    problems = [f"{name}: pull request #{n} is not named" for n in unnamed]
    problems += [
        f"{name}: author @{login} is not named" for login in _unnamed_authors(notes, context)
    ]
    problems += [f"{name}: pull request #{n} is not in this release" for n in sorted(strangers)]
    return problems + _broken_links(notes, root, version, name)


def readme_problems(readme: str, root: Path) -> list[str]:
    """What is wrong with the README: a picture it shows that is not in the checkout."""
    return _broken_pictures(readme, root)


def tool_problems(name: str, output: str, status: int) -> list[str]:
    """The problems in the output of a tool that ran with exit `status`. None when it passed."""
    if status == 0:
        return []
    lines = [line for line in output.splitlines() if line.strip()]
    if name == DOCS_TESTS_NAME:
        problems = []
        for line in lines:
            found = FAILED.match(line)
            if found:
                path, test, message = found.groups()
                problems.append(
                    _line(f"{path}: Kitden's test {test} fails: {message or 'no message'}")
                )
        if problems:
            return problems
        last = lines[-1] if lines else "no output"
        return [_line(f"{name} did not run (status {status}): {last}")]
    if not lines:
        return [f"{name} failed (status {status}) with no output"]
    return [_line(f"{name}: {line}") for line in lines]


def _read(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except FileNotFoundError:
        return None


def verdict(
    root: Path, context: dict, version: str, tests: tuple[str, int], check: tuple[str, int]
) -> tuple[list[str], dict]:
    """All the problems, and the facts for the pull request's body. `tests` and `check` are
    the output and exit status of Kitden's docs tests and of its release check."""
    notes_name = f"docs/releases/v{version}.md"
    notes = _read(root / notes_name)
    readme = _read(root / "README.md")
    problems: list[str] = []
    unnamed: list[int] = []
    unnamed_authors: list[str] = []
    links: list[str] = []
    if notes is None:
        problems.append(f"{notes_name}: missing")
    else:
        unnamed, _ = _pr_counts(notes, context)
        unnamed_authors = _unnamed_authors(notes, context)
        problems += notes_problems(notes, context, root, version)
        links += _broken_links(notes, root, version, notes_name)
    if readme is None:
        problems.append("README.md: missing")
    else:
        problems += readme_problems(readme, root)
        links += _broken_pictures(readme, root)
    problems += tool_problems(DOCS_TESTS_NAME, *tests)
    problems += tool_problems(RELEASE_CHECK_NAME, *check)

    prs_total = len(context["prs"])
    authors_total = len(_authors(context))
    facts = {
        "readme_lines": len((readme or "").splitlines()),
        "docs_tests": "pass" if tests[1] == 0 else "fail",
        "release_check": "pass" if check[1] == 0 else "fail",
        "prs_named": 0 if notes is None else prs_total - len(unnamed),
        "prs_total": prs_total,
        "authors_named": 0 if notes is None else authors_total - len(unnamed_authors),
        "authors_total": authors_total,
        "links": "broken" if links else "ok",
    }
    return problems, facts


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    tests_cmd = commands.add_parser("tests")
    tests_cmd.add_argument("value")
    verdict_cmd = commands.add_parser("verdict")
    verdict_cmd.add_argument("root", type=Path)
    verdict_cmd.add_argument("--context", type=Path, required=True)
    verdict_cmd.add_argument("--version", required=True)
    verdict_cmd.add_argument("--tests-output", type=Path, required=True)
    verdict_cmd.add_argument("--tests-status", type=int, required=True)
    verdict_cmd.add_argument("--check-output", type=Path, required=True)
    verdict_cmd.add_argument("--check-status", type=int, required=True)
    verdict_cmd.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)

    try:
        if args.command == "tests":
            print("\n".join(docs_tests(args.value)))
        else:
            context = json.loads(args.context.read_text())
            tests = (_read(args.tests_output) or "", args.tests_status)
            check = (_read(args.check_output) or "", args.check_status)
            problems, facts = verdict(args.root, context, args.version, tests, check)
            args.out.mkdir(parents=True, exist_ok=True)
            (args.out / "problems.md").write_text("".join(f"- {line}\n" for line in problems))
            (args.out / "facts.json").write_text(json.dumps(facts, indent=2) + "\n")
            print(f"{len(problems)} problems.")
    except (ValueError, OSError, KeyError, TypeError) as error:
        print(error)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
