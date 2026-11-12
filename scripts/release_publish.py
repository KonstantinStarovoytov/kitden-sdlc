"""The decisions behind Kitden's publish workflow and auto-tag. No model, no secrets.

Each command prints one answer or does one thing, so the workflows hold no logic of their own:

    release_publish.py check-version X.Y.Z
    release_publish.py needs-tag X.Y.Z --tags TAGS_FILE --notes docs/releases/vX.Y.Z.md
    release_publish.py wait-pypi X.Y.Z
    release_publish.py registry-has X.Y.Z
    release_publish.py deps-changed OLD_PYPROJECT NEW_PYPROJECT
    release_publish.py bump-formula FORMULA X.Y.Z [--listing listing.toml]
    release_publish.py summary vX.Y.Z --changed CHANGED_FILE --out SUMMARY_FILE

Answers are "true" or "false" on stdout. A bad version is refused before anything else.
"""

import argparse
import json
import re
import sys
import time
import tomllib
import urllib.error
import urllib.parse
from collections.abc import Callable
from pathlib import Path

from brew_bump import bump_formula, deps_changed
from release_stores import MCP_NAME, Fetch, Row, fetch_url, read_all, summary

VERSION = re.compile(r"\d+\.\d+\.\d+\Z")
PYPI_VERSION = "https://pypi.org/pypi/kitden/{version}/json"
REGISTRY_VERSION = "https://registry.modelcontextprotocol.io/v0/servers/{name}/versions/{version}"
POLL_S = 30
# Checked 2026-11-12 on claude.com/docs/plugins/submit: the developer portal, where the plugin's
# page (from Submissions) holds its listing and its data handling answers.
DIRECTORY = "https://claude.ai/directory/manage"
MUST_PASS = ("PyPI", "GitHub release", "MCP Registry", "release branch")
HAND_FILES = ("listing.toml", "PRIVACY.md")


def valid_version(version: str) -> str:
    """`version` if it is X.Y.Z with digits only; ValueError otherwise."""
    if not VERSION.fullmatch(version):
        raise ValueError(f'version {version!r} must look like "X.Y.Z"')
    return version


def needs_tag(version: str, tags: set[str], notes_exist: bool) -> bool:
    """True when vX.Y.Z has no tag yet and its release notes are in the tree."""
    return f"v{valid_version(version)}" not in tags and notes_exist


def wait_for_pypi(
    version: str, fetch: Fetch, sleep: Callable[[float], object], timeout_s: int = 900
) -> None:
    """Return once PyPI's JSON API serves kitden X.Y.Z. Give up after `timeout_s` seconds."""
    url = PYPI_VERSION.format(version=valid_version(version))
    waited = 0
    while True:
        try:
            if json.loads(fetch(url))["info"]["version"] == version:
                return
        except (OSError, ValueError, KeyError, TypeError):
            pass  # not there yet, or PyPI did not answer: try again
        if waited + POLL_S > timeout_s:
            raise SystemExit(f"PyPI does not serve kitden {version} yet; re-run this job")
        sleep(POLL_S)
        waited += POLL_S


def registry_has(version: str, fetch: Fetch) -> bool:
    """True when the MCP Registry already lists kitden X.Y.Z. Errors other than 404 raise."""
    url = REGISTRY_VERSION.format(
        name=urllib.parse.quote(MCP_NAME, safe=""), version=valid_version(version)
    )
    try:
        server = json.loads(fetch(url))["server"]
    except urllib.error.HTTPError as error:
        if error.code == 404:
            return False
        raise
    return server["name"] == MCP_NAME and server["version"] == version


def sdist(version: str, fetch: Fetch) -> tuple[str, str]:
    """The url and sha256 of kitden X.Y.Z's source archive on PyPI."""
    data = json.loads(fetch(PYPI_VERSION.format(version=valid_version(version))))
    for file in data["urls"]:
        if file["packagetype"] == "sdist":
            return file["url"], file["digests"]["sha256"]
    raise ValueError(f"PyPI has no sdist for kitden {version}")


def must_pass(rows: list[Row]) -> list[str]:
    """Problems with the places that must be right when publishing ends."""
    by_place = {row.place: row for row in rows}
    problems = []
    for place in MUST_PASS:
        row = by_place.get(place)
        if row is None:
            problems.append(f"{place}: not read")
        elif row.ok is not True:
            problems.append(f"{place}: expected {row.expected}, seen {row.seen}")
    return problems


def hand_steps(changed_files: list[str]) -> list[str]:
    """What the owner does by hand, given the files changed since the last tag."""
    changed = [name for name in HAND_FILES if name in changed_files]
    if not changed:
        return []
    return [
        f"{' and '.join(changed)} changed: open Kitden from Submissions in the Claude "
        f"directory's developer portal ({DIRECTORY}) and update its listing and its data "
        "handling answers to match."
    ]


def formula_has(text: str, version: str) -> bool:
    """True when the formula's top url is already kitden X.Y.Z's archive."""
    return re.search(rf'(?m)^  url "[^"]*/kitden-{re.escape(version)}\.tar\.gz"$', text) is not None


def _desc(text: str) -> str:
    found = re.search(r'(?m)^  desc "([^"]*)"$', text)
    if not found:
        raise ValueError("formula: no top desc line")
    return found.group(1)


def bump(formula: Path, version: str, listing: Path | None, fetch: Fetch) -> bool:
    """Write kitden X.Y.Z's url and sha256 (and listing.toml's brew desc) into the formula.

    Returns False, writing nothing, when the formula already has the version. Without a
    listing.toml the formula keeps its desc.
    """
    text = formula.read_text()
    if formula_has(text, version):
        return False
    desc = tomllib.loads(listing.read_text())["brew"] if listing else _desc(text)
    url, sha256 = sdist(version, fetch)
    new = bump_formula(text, url, sha256, desc)
    if new == text:
        return False
    formula.write_text(new)
    return True


def _say(answer: bool) -> int:
    print("true" if answer else "false")
    return 0


def _summary(tag: str, changed: Path, out: Path) -> int:
    rows = read_all(tag, fetch_url)
    problems = must_pass(rows)
    steps = hand_steps(changed.read_text().splitlines())
    parts = [f"## Kitden {tag} in every store", "", summary(rows)]
    if steps:
        parts += ["", "### By hand", "", *(f"- {step}" for step in steps)]
    if problems:
        parts += ["", "### Wrong", "", *(f"- {problem}" for problem in problems)]
    with out.open("a") as file:
        file.write("\n".join(parts) + "\n")
    for problem in problems:
        print(f"::error::{problem}")
    return 1 if problems else 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("check-version").add_argument("version")
    tag = commands.add_parser("needs-tag")
    tag.add_argument("version")
    tag.add_argument("--tags", type=Path, required=True, help="one tag per line")
    tag.add_argument("--notes", type=Path, required=True)
    commands.add_parser("wait-pypi").add_argument("version")
    commands.add_parser("registry-has").add_argument("version")
    deps = commands.add_parser("deps-changed")
    deps.add_argument("old", type=Path)
    deps.add_argument("new", type=Path)
    formula = commands.add_parser("bump-formula")
    formula.add_argument("formula", type=Path)
    formula.add_argument("version")
    formula.add_argument("--listing", type=Path)
    report = commands.add_parser("summary")
    report.add_argument("tag")
    report.add_argument("--changed", type=Path, required=True, help="one file per line")
    report.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)

    if args.command == "summary":
        if not re.fullmatch(r"v\d+\.\d+\.\d+", args.tag):
            print(f'tag {args.tag!r} must look like "vX.Y.Z"', file=sys.stderr)
            return 2
        return _summary(args.tag, args.changed, args.out)
    if hasattr(args, "version"):
        try:
            valid_version(args.version)
        except ValueError as error:
            print(error, file=sys.stderr)
            return 2

    match args.command:
        case "check-version":
            print(args.version)
            return 0
        case "needs-tag":
            tags = set(args.tags.read_text().split())
            notes = args.notes.is_file() and args.notes.stat().st_size > 0
            return _say(needs_tag(args.version, tags, notes))
        case "wait-pypi":
            wait_for_pypi(args.version, fetch_url, time.sleep)
            print(f"PyPI serves kitden {args.version}")
            return 0
        case "registry-has":
            return _say(registry_has(args.version, fetch_url))
        case "deps-changed":
            return _say(deps_changed(args.old.read_text(), args.new.read_text()))
        case "bump-formula":
            listing = args.listing if args.listing and args.listing.is_file() else None
            return _say(bump(args.formula, args.version, listing, fetch_url))
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
