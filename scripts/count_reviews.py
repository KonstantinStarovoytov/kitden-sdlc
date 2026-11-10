"""Count what the AI reviewers did on Kitden's pull requests and write numbers.md and numbers.json.

Only the maintainer's 👍 and 👎 count, so nobody else can move the numbers.
(Not named numbers.py: that would hide Python's own `numbers` module.)
"""

import argparse
import json
import sys
from collections.abc import Iterator
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Protocol

from post_findings import GhApi, our_marker

REPO = "KonstantinStarovoytov/kitden"
MAINTAINER = "KonstantinStarovoytov"
SINCE_DAYS = 90
PAGE_SIZE = 100


@dataclass
class Review:
    """One review comment: what its marker says and the maintainer's votes on it."""

    pr: int
    counts: dict[str, int | None]
    up: int
    down: int


@dataclass
class Stats:
    prs: int  # pull requests this reviewer answered on
    findings: int  # its findings, shared ones included
    shared: int  # findings the other reviewer made too


# --- Talking to GitHub ---


class Api(Protocol):
    def list_pulls(self, repo: str) -> Iterator[dict]: ...

    def list_issue_comments(self, repo: str, pr: int) -> list[dict]: ...

    def list_issue_comment_reactions(self, repo: str, comment_id: int) -> list[dict]: ...


class GhNumbersApi(GhApi):
    """The Api on top of the gh command line tool. Only reads."""

    def list_pulls(self, repo: str) -> Iterator[dict]:
        # Newest update first, one page at a time, so the caller can stop early.
        page = 1
        while True:
            query = f"state=all&sort=updated&direction=desc&per_page={PAGE_SIZE}&page={page}"
            items = json.loads(self._run(f"repos/{repo}/pulls?{query}"))
            yield from items
            if len(items) < PAGE_SIZE:
                return
            page += 1

    def list_issue_comment_reactions(self, repo: str, comment_id: int) -> list[dict]:
        return self._list(f"repos/{repo}/issues/comments/{comment_id}/reactions")


# --- Counting ---


def _votes(reactions: list[dict], maintainer: str) -> tuple[int, int]:
    """Count the maintainer's 👍 and 👎. Logins are not case sensitive."""
    mine = [
        r["content"]
        for r in reactions
        if (r.get("user") or {}).get("login", "").lower() == maintainer.lower()
    ]
    return mine.count("+1"), mine.count("-1")


def collect(
    api: Api,
    repo: str,
    since_days: int = SINCE_DAYS,
    maintainer: str = MAINTAINER,
    now: datetime | None = None,
) -> list[Review]:
    """Read the review comments on pull requests updated in the last `since_days`.
    Only our own comment that ends with the marker counts. A person's paste does not."""
    cutoff = (now or datetime.now(UTC)) - timedelta(days=since_days)
    found: list[Review] = []
    for pull in api.list_pulls(repo):
        if datetime.fromisoformat(pull["updated_at"]) < cutoff:
            break  # the list is newest first, so everything after is older
        number = pull["number"]
        for item in api.list_issue_comments(repo, number):
            counts = our_marker(item)
            if counts:
                up, down = _votes(api.list_issue_comment_reactions(repo, item["id"]), maintainer)
                found.append(Review(number, counts, up, down))
    return found


def aggregate(reviews: list[Review]) -> dict[str, Stats]:
    """Per reviewer: pull requests it answered on, its findings, and how many were shared."""
    stats: dict[str, Stats] = {}
    for review in reviews:
        shared = review.counts["both"] or 0
        for reviewer in ("claude", "luna"):
            own = review.counts[reviewer]
            if own is None:
                continue  # it gave no answer on this pull request
            entry = stats.setdefault(reviewer, Stats(0, 0, 0))
            entry.prs += 1
            entry.findings += own + shared
            entry.shared += shared
    return dict(sorted(stats.items()))


# --- Writing ---


def _share(up: int, down: int) -> str:
    votes = up + down
    return f"{round(100 * up / votes)}%" if votes else "-"


def render(stats: dict[str, Stats], reviews: dict[str, int], on: date) -> str:
    lines = [
        "# Reviewer numbers",
        "",
        f"What the AI reviewers did on Kitden's pull requests in the last {SINCE_DAYS} days.",
        "Each pull request gets one review comment from both reviewers.",
        "Only the maintainer's 👍 (useful) and 👎 (wrong) on it count.",
        "",
    ]
    if reviews["prs"]:
        up, down = reviews["up"], reviews["down"]
        lines += [
            f"Reviews: {reviews['prs']}. 👍 {up}, 👎 {down}, useful share {_share(up, down)}.",
            "",
            "| Reviewer | Pull requests | Findings | Also found by the other |",
            "| --- | --- | --- | --- |",
        ]
        for reviewer, s in stats.items():
            lines.append(f"| {reviewer} | {s.prs} | {s.findings} | {s.shared} |")
    else:
        lines.append("No reviews yet.")
    lines += ["", f"Updated on {on.isoformat()}.", ""]
    return "\n".join(lines)


def _same_counts(saved: Path, data: dict) -> bool:
    """True when the saved numbers.json holds the same counts. A broken file counts as no file."""
    try:
        before = json.loads(saved.read_text())
    except (OSError, ValueError):
        return False
    if not isinstance(before, dict):
        return False
    return all(before.get(key) == data[key] for key in ("reviews", "reviewers", "days"))


def main(argv: list[str], api: Api | None = None, now: datetime | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=REPO)
    parser.add_argument("--maintainer", default=MAINTAINER)
    parser.add_argument("--out", type=Path, default=Path())
    args = parser.parse_args(argv)

    now = now or datetime.now(UTC)
    found = collect(api or GhNumbersApi(), args.repo, maintainer=args.maintainer, now=now)
    stats = aggregate(found)
    reviews = {
        "prs": len({r.pr for r in found}),
        "up": sum(r.up for r in found),
        "down": sum(r.down for r in found),
    }
    data = {
        "updated": now.date().isoformat(),
        "days": SINCE_DAYS,
        "reviews": reviews,
        "reviewers": {name: asdict(s) for name, s in stats.items()},
    }
    saved = args.out / "numbers.json"
    if _same_counts(saved, data) and (args.out / "numbers.md").exists():
        return 0  # only the date would differ: leave both files so the job commits nothing
    saved.write_text(json.dumps(data, indent=2) + "\n")
    (args.out / "numbers.md").write_text(render(stats, reviews, now.date()))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
