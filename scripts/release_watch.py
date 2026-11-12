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
    HOMEBREW,
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
PREP_NAME = "Release prep"  # the `name:` of examples/release-prep.yml
PREP_BRANCH = "prepare-v"  # release prep's own PRs, which bump the version: not a reason
PER_PAGE = 100
LABEL = "automated"  # every issue opened by automation carries it (the owner's rule)
AI_POLICY = f"https://github.com/{REPO_SLUG}/blob/main/AI_POLICY.md"
HEADER = (
    "Opened by release-watch, a daily check in kitden-sdlc with no AI model. "
    f"A maintainer confirms it before work starts ([AI policy]({AI_POLICY}))."
)

# How to put each place right. Places not listed here are changed by hand. kitden-sdlc's
# publish workflow runs inside the tag's `Checks and release` run, as its `stores / ...` jobs.
RUN = "the tag's `Checks and release` run"
RERUN = {
    "PyPI": f"re-run the failed jobs of {RUN}",
    "GitHub release": f"re-run the failed jobs of {RUN}",
    "MCP Registry": f"re-run the `stores / registry` job of {RUN}",
    "release branch": f"re-run the `stores / release-branch` job of {RUN}",
    HOMEBREW: f"re-run the `stores / homebrew` job of {RUN}, or, when the dependencies "
    "changed, look at the tap's `bump-kitden-` PR from its daily autobump and its "
    "`auto-pull` run",
    "Marketplace entry": "by hand: `ref` in `.claude-plugin/marketplace.json` must be `release`",
    "GitHub description": "by hand: set the repository description to `short` in `listing.toml`",
}
# The version and the bottles are right but the desc is not: the homebrew job leaves a formula
# that already has the version alone, so re-running it changes nothing.
HOMEBREW_DESC = (
    "by hand: the version is right but the tap's `desc` is not `brew` in `listing.toml`; fix "
    "`desc` in the tap's `Formula/kitden.rb` with a small PR there, or let the next release "
    "fix it (re-running `stores / homebrew` changes nothing)"
)


def fix_for(row: Row) -> str:
    """How to put this row's place right."""
    if row.place == HOMEBREW and "desc differs" in row.seen:
        return HOMEBREW_DESC
    return RERUN.get(row.place, "by hand")


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
        f"{HEADER}\n\n"
        "## What happened\n\n"
        "These merged pull requests changed what users get since the last release:\n\n"
        f"{links}\n\n"
        "## What it means\n\n"
        "Users do not have these changes yet: they reach PyPI, Homebrew and the plugin only "
        "with a release.\n\n"
        "## What to do\n\n"
        f"Run [{PREP_NAME}]({PREP}). It picks the version, writes the notes and opens the "
        "release pull request for you to review and merge.\n\n"
        "This issue is updated every day and closes itself when a release is made."
    )


def drift_title(tag: str) -> str:
    return f"Release {tag} is not everywhere"


def drift_body(tag: str, rows: list[Row], late: list[Row]) -> str:
    fixes = "\n".join(f"- {row.place}: {fix_for(row)}" for row in late)
    return (
        f"{HEADER}\n\n"
        "## What happened\n\n"
        f"Kitden {tag} is behind or different in these places:\n\n"
        f"{summary(rows)}\n\n"
        "## What it means\n\n"
        f"People who install Kitden from these places do not get {tag}, or see an old "
        "description.\n\n"
        "## What to do\n\n"
        f"{fixes}\n\n"
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
        self._gh("issue", "create", "--title", title, "--body", body, "--label", LABEL)

    def edit(self, number: int, body: str) -> None:
        self._gh("issue", "edit", str(number), "--body", body, "--add-label", LABEL)

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


def _is_prep(number: int, fetch: Fetch) -> bool:
    """True for release prep's own PR (head branch prepare-vX.Y.Z)."""
    pull = json.loads(fetch(_api(f"pulls/{number}")))
    return pull["head"]["ref"].startswith(PREP_BRANCH)


def gather(fetch: Fetch, now: datetime) -> Data | None:
    """The newest vX.Y.Z tag, its age, and the PRs merged into main since, with files and labels.

    Release prep's own PRs are left out. None when there is no tag. A read that fails raises,
    so the job fails and shows it.
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
    items = [item for item in items if not _is_prep(item["number"], fetch)]
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
