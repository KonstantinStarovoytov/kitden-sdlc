"""Count what the AI reviewers did on Kitden's pull requests and write numbers.md and numbers.json.

Only the maintainer's 👍 and 👎 count, so nobody else can move the numbers.
(Not named numbers.py: that would hide Python's own `numbers` module.)
"""

import argparse
import json
import statistics
import sys
from collections.abc import Iterator
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Protocol

from post_findings import GhApi, our_marker, read_state

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
    fixed: int = 0  # findings of the comment that were fixed
    updated: str = ""  # when the comment last changed
    created: str = ""  # when the pull request was opened
    merged: str | None = None  # when it was merged; None while it is not

    @property
    def answered(self) -> bool:
        """At least one reviewer gave an answer."""
        return self.counts["claude"] is not None or self.counts["luna"] is not None

    @property
    def clean(self) -> bool:
        """The reviewers found nothing: every count is 0 or missing, and one of them answered."""
        return self.answered and not any(self.counts.values())


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
    include_silent: bool = False,
) -> list[Review]:
    """Read the review comments on pull requests updated in the last `since_days`.
    Only our own comment that ends with the marker counts. A person's paste does not,
    and neither does a comment in which neither reviewer gave an answer, unless
    `include_silent`: then it comes too, with no votes and nothing fixed read."""
    cutoff = (now or datetime.now(UTC)) - timedelta(days=since_days)
    found: list[Review] = []
    for pull in api.list_pulls(repo):
        if datetime.fromisoformat(pull["updated_at"]) < cutoff:
            break  # the list is newest first, so everything after is older
        number = pull["number"]
        for item in api.list_issue_comments(repo, number):
            counts = our_marker(item)
            if counts and include_silent and counts["claude"] is None and counts["luna"] is None:
                found.append(Review(number, counts, 0, 0, updated=item.get("updated_at") or "",
                                    created=pull["created_at"], merged=pull.get("merged_at")))
            elif counts and (counts["claude"] is not None or counts["luna"] is not None):
                up, down = _votes(api.list_issue_comment_reactions(repo, item["id"]), maintainer)
                # A long pull request can undercount: the comment drops its oldest fixed past 30.
                earlier = read_state(item.get("body") or "")
                fixed = sum(bool(i.fixed) for i in earlier.items) if earlier else 0
                found.append(
                    Review(
                        number,
                        counts,
                        up,
                        down,
                        fixed=fixed,
                        updated=item.get("updated_at") or "",
                        created=pull["created_at"],
                        merged=pull.get("merged_at"),
                    )
                )
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


def summary(reviews: list[Review]) -> dict:
    """Reviews that found nothing, findings fixed before the merge (merged pull requests only),
    and the median days from open to merge of the reviewed pull requests that merged
    (each counted once)."""
    merged = {r.pr: r for r in reviews if r.merged}
    days = [
        (datetime.fromisoformat(r.merged) - datetime.fromisoformat(r.created)).total_seconds()
        / 86400
        for r in merged.values()
    ]
    return {
        "clean": sum(r.clean for r in reviews),
        "fixed": sum(r.fixed for r in reviews if r.merged),
        "days_to_merge": round(statistics.median(days), 1) if days else None,
    }


# --- Writing ---


def _share(up: int, down: int) -> str:
    votes = up + down
    return f"{round(100 * up / votes)}%" if votes else "-"


def render(stats: dict[str, Stats], reviews: dict[str, int], overview: dict, on: date) -> str:
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
        days = overview["days_to_merge"]
        lines += [
            f"Reviews: {reviews['prs']}. 👍 {up}, 👎 {down}, useful share {_share(up, down)}.",
            f"No findings: {overview['clean']}. "
            f"Findings fixed before the merge: {overview['fixed']}. "
            f"Median days from open to merge: {'-' if days is None else days}.",
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
    return all(before.get(key) == data[key] for key in ("reviews", "reviewers", "days", "summary"))


def write_numbers(found: list[Review], out: Path, now: datetime) -> None:
    """Write numbers.json and numbers.md into `out` from the reviews `found`. When only the
    date would differ, both files are left as they are, so the job commits nothing."""
    stats = aggregate(found)
    reviews = {
        "prs": len({r.pr for r in found}),
        "up": sum(r.up for r in found),
        "down": sum(r.down for r in found),
    }
    numbers = summary(found)
    data = {
        "updated": now.date().isoformat(),
        "days": SINCE_DAYS,
        "reviews": reviews,
        "reviewers": {name: asdict(s) for name, s in stats.items()},
        "summary": numbers,
    }
    saved = out / "numbers.json"
    if _same_counts(saved, data) and (out / "numbers.md").exists():
        return
    saved.write_text(json.dumps(data, indent=2) + "\n")
    (out / "numbers.md").write_text(render(stats, reviews, numbers, now.date()))


def main(argv: list[str], api: Api | None = None, now: datetime | None = None) -> int:
    """By hand; the desk (desk_gather.py) writes the same two files every day."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=REPO)
    parser.add_argument("--maintainer", default=MAINTAINER)
    parser.add_argument("--out", type=Path, default=Path())
    args = parser.parse_args(argv)

    now = now or datetime.now(UTC)
    found = collect(api or GhNumbersApi(), args.repo, maintainer=args.maintainer, now=now)
    write_numbers(found, args.out, now)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
