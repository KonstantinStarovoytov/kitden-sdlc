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

from post_findings import GhApi
from post_findings import read_marker as parse_marker

REPO = "KonstantinStarovoytov/kitden"
MAINTAINER = "KonstantinStarovoytov"
SINCE_DAYS = 90
PAGE_SIZE = 100


@dataclass
class Comment:
    reviewer: str
    pr: int
    is_summary: bool
    up: int
    down: int


@dataclass
class Stats:
    prs: int
    findings: int
    up: int
    down: int


# --- Talking to GitHub ---


class Api(Protocol):
    def list_pulls(self, repo: str) -> Iterator[dict]: ...

    def list_review_comments(self, repo: str, pr: int) -> list[dict]: ...

    def list_issue_comments(self, repo: str, pr: int) -> list[dict]: ...

    def list_review_comment_reactions(self, repo: str, comment_id: int) -> list[dict]: ...

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

    def list_review_comment_reactions(self, repo: str, comment_id: int) -> list[dict]:
        return self._list(f"repos/{repo}/pulls/comments/{comment_id}/reactions")

    def list_issue_comment_reactions(self, repo: str, comment_id: int) -> list[dict]:
        return self._list(f"repos/{repo}/issues/comments/{comment_id}/reactions")


# --- Counting ---


def _votes(reactions: list[dict], maintainer: str) -> tuple[int, int]:
    """Count the maintainer's 👍 and 👎. Logins are not case sensitive."""
    mine = [r["content"] for r in reactions if r["user"]["login"].lower() == maintainer.lower()]
    return mine.count("+1"), mine.count("-1")


def _ours(comments: list[dict]) -> Iterator[tuple[dict, str, str]]:
    """Comments written by a bot that end with our marker. A person's paste does not count."""
    for item in comments:
        if (item.get("user") or {}).get("type") != "Bot":
            continue
        found = parse_marker(item.get("body") or "")
        if found:
            yield item, found[0], found[1]


def collect(
    api: Api,
    repo: str,
    since_days: int = SINCE_DAYS,
    maintainer: str = MAINTAINER,
    now: datetime | None = None,
) -> list[Comment]:
    """Read the reviewers' comments on pull requests updated in the last `since_days`."""
    cutoff = (now or datetime.now(UTC)) - timedelta(days=since_days)
    found: list[Comment] = []
    for pull in api.list_pulls(repo):
        if datetime.fromisoformat(pull["updated_at"]) < cutoff:
            break  # the list is newest first, so everything after is older
        number = pull["number"]
        kinds = (
            (api.list_review_comments, api.list_review_comment_reactions),
            (api.list_issue_comments, api.list_issue_comment_reactions),
        )
        for list_comments, list_reactions in kinds:
            for item, reviewer, key in _ours(list_comments(repo, number)):
                up, down = _votes(list_reactions(repo, item["id"]), maintainer)
                found.append(Comment(reviewer, number, key == "summary", up, down))
    return found


def aggregate(comments: list[Comment]) -> dict[str, Stats]:
    """Per reviewer: pull requests reviewed, findings (the summary is not one), votes."""
    stats: dict[str, Stats] = {}
    seen: dict[str, set[int]] = {}
    for c in comments:
        entry = stats.setdefault(c.reviewer, Stats(0, 0, 0, 0))
        seen.setdefault(c.reviewer, set()).add(c.pr)
        entry.findings += 0 if c.is_summary else 1
        entry.up += c.up
        entry.down += c.down
    for reviewer, prs in seen.items():
        stats[reviewer].prs = len(prs)
    return dict(sorted(stats.items()))


# --- Writing ---


def _share(s: Stats) -> str:
    votes = s.up + s.down
    return f"{round(100 * s.up / votes)}%" if votes else "-"


def render(stats: dict[str, Stats], on: date) -> str:
    lines = [
        "# Reviewer numbers",
        "",
        f"What the AI reviewers did on Kitden's pull requests in the last {SINCE_DAYS} days.",
        "Only the maintainer's 👍 (useful) and 👎 (wrong) count.",
        "",
    ]
    if stats:
        lines += [
            "| Reviewer | Pull requests | Findings | 👍 | 👎 | Useful share |",
            "| --- | --- | --- | --- | --- | --- |",
        ]
        for reviewer, s in stats.items():
            cells = [reviewer, s.prs, s.findings, s.up, s.down, _share(s)]
            lines.append("| " + " | ".join(map(str, cells)) + " |")
    else:
        lines.append("No reviews yet.")
    lines += ["", f"Updated on {on.isoformat()}.", ""]
    return "\n".join(lines)


def main(argv: list[str], api: Api | None = None, now: datetime | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=REPO)
    parser.add_argument("--maintainer", default=MAINTAINER)
    parser.add_argument("--out", type=Path, default=Path())
    args = parser.parse_args(argv)

    now = now or datetime.now(UTC)
    comments = collect(api or GhNumbersApi(), args.repo, maintainer=args.maintainer, now=now)
    stats = aggregate(comments)
    data = {
        "updated": now.date().isoformat(),
        "days": SINCE_DAYS,
        "reviewers": {name: asdict(s) for name, s in stats.items()},
    }
    (args.out / "numbers.json").write_text(json.dumps(data, indent=2) + "\n")
    (args.out / "numbers.md").write_text(render(stats, now.date()))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
