"""Gather what the release-prep agent reads, and decide whether release prep may start.

No model runs here. Two commands, both run by .github/workflows/release-prep.yml:

  release_context.py guard PRS_JSON --enabled true|false
      PRS_JSON is `gh pr list --state open --json headRefName,author,isCrossRepository`.
      Prints why release prep must stop, or nothing when it may go.
  release_context.py collect ROOT --version auto|minor|patch|X.Y.Z --out context.json
      Turns the owner's choice into a version (auto or empty: the agent picks it later), and
      writes the git log since the last tag, the pull requests merged since it and the diff
      stat. The design is docs/superpowers/specs/2026-11-12-release-flow-design.md (B1, B2).
"""

import argparse
import json
import re
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

from release_bump import current_version, next_versions

RELEASE_BRANCH = "prepare-v"
# The owner reviews at most 3 pull requests at a time. Counted conservatively: every open
# pull request by a bot (the release app, Lantern, Dependabot) waits for the owner.
MAX_WAITING = 3
BODY_MAX = 10_000
VERSION = re.compile(r"\d+\.\d+\.\d+\Z", re.ASCII)
MERGE = re.compile(r"^Merge pull request #(\d+)\b")
SQUASH = re.compile(r"\(#(\d+)\)\s*$")
PR_FIELDS = "number,title,body,labels,author,additions,deletions,files"

Gh = Callable[[list[str]], str]


def guard(prs: list[dict], enabled: bool) -> str | None:
    """Why release prep must not start, or None when it may."""
    if not enabled:
        return "The AGENTS_ENABLED switch is off."
    for pr in prs:
        head = str(pr.get("headRefName", ""))
        # Anyone can open a pull request from a fork's branch of that name; only Kitden's own count.
        if head.startswith(RELEASE_BRANCH) and not pr.get("isCrossRepository"):
            return f"A release pull request is open already, from {head}."
    bots = [pr for pr in prs if _is_bot(pr.get("author") or {})]
    # This run adds one more, so stop when the owner already has MAX_WAITING - 1 or more.
    if len(bots) >= MAX_WAITING:
        return (
            f"{len(bots)} pull requests by bots wait for the owner; "
            f"the limit is {MAX_WAITING} with this one."
        )
    return None


def _is_bot(author: dict) -> bool:
    login = str(author.get("login", ""))
    return bool(author.get("is_bot")) or login.endswith("[bot]") or login.startswith("app/")


def resolve_version(choice: str, current: str) -> str:
    """The version for the owner's `choice` after `current`: "" for auto (the agent picks),
    the next minor or patch for those words, or an X.Y.Z that is one of the two.
    Raises ValueError for anything else."""
    minor, patch = next_versions(current)
    words = {"": "", "auto": "", "minor": minor, "patch": patch}
    if choice in words:
        return words[choice]
    if VERSION.match(choice) and choice in (minor, patch):
        return choice
    raise ValueError(f"version {choice!r} must be auto, minor ({minor}) or patch ({patch})")


def _git(root: Path, *args: str) -> str:
    return subprocess.run(  # noqa: S603
        ["git", "-C", str(root), *args],  # noqa: S607
        check=True,
        capture_output=True,
        text=True,
    ).stdout


def last_tag(root: Path) -> str:
    return _git(root, "describe", "--tags", "--abbrev=0", "--match", "v[0-9]*", "HEAD").strip()


def pr_numbers(subjects: list[str]) -> list[int]:
    """Pull request numbers in the order of the subjects, each once."""
    numbers: list[int] = []
    for subject in subjects:
        found = MERGE.match(subject) or SQUASH.search(subject)
        if found and int(found.group(1)) not in numbers:
            numbers.append(int(found.group(1)))
    return numbers


def _cut(text: str) -> str:
    return text if len(text) <= BODY_MAX else text[:BODY_MAX] + "\n[cut]"


def _pr(gh: Gh, number: int) -> dict:
    data = json.loads(gh(["pr", "view", str(number), "--json", PR_FIELDS]))
    return {
        "number": int(data["number"]),
        "title": str(data.get("title") or ""),
        "body": _cut(str(data.get("body") or "")),
        "labels": [str(label.get("name", "")) for label in data.get("labels") or []],
        "author": str((data.get("author") or {}).get("login", "")),
        "additions": int(data.get("additions") or 0),
        "deletions": int(data.get("deletions") or 0),
        "files": [str(file.get("path", "")) for file in data.get("files") or []],
    }


def collect(root: Path, since_tag: str, gh: Gh, version: str = "") -> dict:
    """The context the agent reads: main's history since `since_tag`, oldest first."""
    span = f"{since_tag}..HEAD"
    subjects = _git(root, "log", "--first-parent", "--reverse", "--format=%s", span)
    return {
        "version": version,
        "since_tag": since_tag,
        "log": _git(root, "log", "--first-parent", "--reverse", "--format=%h %s (%an)", span),
        "prs": [_pr(gh, number) for number in pr_numbers(subjects.splitlines())],
        "diffstat": _git(root, "diff", "--stat", span),
    }


def _gh(args: list[str]) -> str:
    return subprocess.run(  # noqa: S603
        ["gh", *args],  # noqa: S607
        check=True,
        capture_output=True,
        text=True,
    ).stdout


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    guard_cmd = commands.add_parser("guard")
    guard_cmd.add_argument("prs", type=Path)
    guard_cmd.add_argument("--enabled", required=True)
    collect_cmd = commands.add_parser("collect")
    collect_cmd.add_argument("root", type=Path)
    collect_cmd.add_argument("--version", default="")
    collect_cmd.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)

    if args.command == "guard":
        prs = json.loads(args.prs.read_text())
        reason = guard(prs, enabled=args.enabled == "true")
        if reason:
            print(reason)
        return 0

    try:
        version = resolve_version(args.version, current_version(args.root))
    except ValueError as problem:
        print(problem)
        return 1
    context = collect(args.root, last_tag(args.root), _gh, version=version)
    args.out.write_text(json.dumps(context, indent=2, ensure_ascii=False) + "\n")
    print(f"{len(context['prs'])} pull requests since {context['since_tag']}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
