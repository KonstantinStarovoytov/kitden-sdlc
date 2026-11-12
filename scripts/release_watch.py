"""The daily release watch: two issues in Kitden, from facts only. No model.

    release_watch.py

- "Time for a release?" is open while merged PRs change what users get and the last tag is old
  enough (or one of those PRs fixes a bug). It names no version.
- "Release vX.Y.Z is not everywhere" is open while a store is behind, and closes when all is well.

Reads are public GitHub and store URLs. Issues are written with the `gh` CLI, whose token
(GH_TOKEN) is the one the workflow gives: issues write on Kitden, nothing else.
"""

import json
import re
import subprocess
import sys
import urllib.parse
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from release_stores import (
    COMMIT,
    OWNER,
    REPO,
    TAG,
    Fetch,
    Row,
    behind,
    fetch_url,
    read_all,
    summary,
)

WAIT_DAYS = 7  # a user-facing change waits this long for a release, unless it fixes a bug
BUG_LABEL = "bug"
USER_FACING = ("src/", "plugins/")  # and install.* in the repository root
# Homebrew's 48 hours are in release_stores.HOMEBREW_WAIT_HOURS.

REPO_SLUG = f"{OWNER}/kitden"
PROPOSAL_TITLE = "Time for a release?"
PULL = f"https://github.com/{REPO_SLUG}/pull/{{number}}"
PREP = f"https://github.com/{REPO_SLUG}/actions/workflows/release-prep.yml"
PER_PAGE = 100

# How to put each place right. Places not listed here are changed by hand.
RERUN = {
    "PyPI": "re-run the failed jobs of the tag's `Checks and release` run",
    "GitHub release": "re-run the failed jobs of the tag's `Checks and release` run",
    "MCP Registry": "re-run the `registry` job of the tag's `Publish` run",
    "release branch": "re-run the `release-branch` job of the tag's `Publish` run",
    "Homebrew formula": "re-run the `homebrew` job of the tag's `Publish` run, or merge the "
    "tap's bump PR",
    "Marketplace entry": "by hand: `ref` in `.claude-plugin/marketplace.json` must be `release`",
    "GitHub description": "by hand: set the repository description to `short` in `listing.toml`",
}


def _user_facing(path: str) -> bool:
    return path.startswith(USER_FACING) or re.fullmatch(r"install\.[^/]*", path) is not None


def propose(
    changed_paths_by_pr: dict[int, list[str]],
    labels_by_pr: dict[int, list[str]],
    last_tag_age_days: float,
) -> list[int] | None:
    """The PR numbers to list in "Time for a release?", or None when no release is due.

    Only PRs that changed src/, plugins/ or install.* count. A release is due when the last tag
    is at least WAIT_DAYS old, or when one of those PRs is labelled `bug`.
    """
    prs = sorted(
        number
        for number, paths in changed_paths_by_pr.items()
        if any(_user_facing(path) for path in paths)
    )
    if not prs:
        return None
    has_bug = any(BUG_LABEL in labels_by_pr.get(number, []) for number in prs)
    if last_tag_age_days >= WAIT_DAYS or has_bug:
        return prs
    return None


def proposal_body(prs: list[int]) -> str:
    links = "\n".join(f"- {PULL.format(number=number)}" for number in sorted(prs))
    return (
        "These merged pull requests changed what users get since the last release:\n\n"
        f"{links}\n\n"
        f"To prepare the release, run [Prepare release]({PREP}). "
        "It picks the version and writes the notes.\n\n"
        "This issue is updated every day and closes itself when a release is made."
    )


def drift_title(tag: str) -> str:
    return f"Release {tag} is not everywhere"


def drift_body(tag: str, rows: list[Row], late: list[Row]) -> str:
    fixes = "\n".join(f"- {row.place}: {RERUN.get(row.place, 'by hand')}" for row in late)
    return (
        f"Kitden {tag} is behind or different in these places:\n\n"
        f"{summary(rows)}\n\n"
        f"Re-run or fix:\n\n{fixes}\n\n"
        "This issue is updated every day and closes itself when every store is right."
    )


class Gh(Protocol):
    def find_open(self, title: str) -> int | None: ...
    def create(self, title: str, body: str) -> None: ...
    def edit(self, number: int, body: str) -> None: ...
    def close(self, number: int) -> None: ...


class GhCli:
    """Issues in Kitden through the `gh` CLI. The title is matched exactly, never searched."""

    def _gh(self, *args: str) -> str:
        done = subprocess.run(  # noqa: S603
            ["gh", *args, "--repo", REPO_SLUG],  # noqa: S607
            check=True,
            capture_output=True,
            text=True,
        )
        return done.stdout

    def find_open(self, title: str) -> int | None:
        listing = self._gh(
            "issue", "list", "--state", "open", "--limit", "200", "--json", "number,title"
        )
        for issue in json.loads(listing):
            if issue["title"] == title:
                return issue["number"]
        return None

    def create(self, title: str, body: str) -> None:
        self._gh("issue", "create", "--title", title, "--body", body)

    def edit(self, number: int, body: str) -> None:
        self._gh("issue", "edit", str(number), "--body", body)

    def close(self, number: int) -> None:
        self._gh("issue", "close", str(number))


def upsert(title: str, body: str, gh: Gh) -> None:
    """Edit the open issue with this title, open one if none, close it when `body` is empty."""
    number = gh.find_open(title)
    if not body:
        if number is not None:
            gh.close(number)
    elif number is None:
        gh.create(title, body)
    else:
        gh.edit(number, body)


@dataclass
class Data:
    tag: str
    age_days: float
    changed: dict[int, list[str]]
    labels: dict[int, list[str]]


def _api(path: str) -> str:
    return f"{REPO}/{path}"


def _latest_tag(fetch: Fetch) -> str | None:
    refs = json.loads(fetch(_api(f"git/matching-refs/tags/v?per_page={PER_PAGE}")))
    tags = [ref["ref"].removeprefix("refs/tags/") for ref in refs]
    versions = [tag for tag in tags if TAG.match(tag)]
    return (
        max(versions, key=lambda tag: tuple(int(n) for n in tag[1:].split(".")))
        if versions
        else None
    )


def _files(number: int, fetch: Fetch) -> list[str]:
    names: list[str] = []
    page = 1
    while True:
        chunk = json.loads(fetch(_api(f"pulls/{number}/files?per_page={PER_PAGE}&page={page}")))
        names += [item["filename"] for item in chunk]
        if len(chunk) < PER_PAGE:
            return names
        page += 1


def gather(fetch: Fetch, now: datetime) -> Data | None:
    """The newest vX.Y.Z tag, its age, and the PRs merged into main since, with files and labels.

    None when there is no tag. A read that fails raises, so the job fails and shows it.
    """
    tag = _latest_tag(fetch)
    if tag is None:
        return None
    commit = json.loads(fetch(COMMIT.format(ref=tag)))
    date = commit["commit"]["committer"]["date"]
    made = datetime.fromisoformat(date.replace("Z", "+00:00"))
    query = f"repo:{REPO_SLUG} is:pr is:merged base:main merged:>{date}"
    search = urllib.parse.urlencode({"q": query, "per_page": PER_PAGE})
    items = json.loads(fetch(f"https://api.github.com/search/issues?{search}"))["items"]
    changed = {item["number"]: _files(item["number"], fetch) for item in items}
    labels = {item["number"]: [label["name"] for label in item["labels"]] for item in items}
    return Data(tag, (now - made).total_seconds() / 86400, changed, labels)


def run(fetch: Fetch, gh: Gh, now: datetime) -> None:
    data = gather(fetch, now)
    if data is None:
        return
    prs = propose(data.changed, data.labels, data.age_days)
    upsert(PROPOSAL_TITLE, proposal_body(prs) if prs else "", gh)
    rows = read_all(data.tag, fetch)
    late = behind(rows, data.age_days * 24)
    upsert(drift_title(data.tag), drift_body(data.tag, rows, late) if late else "", gh)


def main(
    argv: list[str], fetch: Fetch = fetch_url, clock: Callable[[], datetime] | None = None
) -> int:
    if argv:
        print("usage: release_watch.py", file=sys.stderr)
        return 2
    run(fetch, GhCli(), (clock or (lambda: datetime.now(UTC)))())
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
