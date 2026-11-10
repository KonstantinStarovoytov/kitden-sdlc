"""Put the AI reviewers' findings on a pull request as one comment, edited in place."""

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol
from urllib.parse import quote

SUMMARY_MAX = 300
TEXT_MAX = 300
FINDINGS_MAX = 5
KINDS = ("bug", "rule")
TOP_KEYS = {"summary", "new_surface", "findings"}
FINDING_KEYS = {"path", "line", "kind", "text"}
# Text that looks like a real token (a prefix plus a long tail), not just a token's name.
# The model must never be able to publish one.
SECRET_LIKE = re.compile(
    r"(?<!\w)gh[pousr]_[A-Za-z0-9]{16,}"
    r"|github_pat_[A-Za-z0-9_]{16,}"
    r"|sk-ant-[A-Za-z0-9_-]{16,}"
    r"|(?<!\w)sk-[A-Za-z0-9_-]{20,}"
    r"|x-access-token:[^@\s]+@"
    r"|eyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}"  # a JWT
)
# An @ at the start of a word would ping a real GitHub user (think `@pytest.fixture`).
MENTION = re.compile(r"(?<!\w)@(?=\w)")
WORD_JOINER = "\u2060"
# How close (in lines) two reviewers' findings in one file may be and still count as
# the same finding.
NEAR_LINES = 5


@dataclass
class Finding:
    path: str
    line: int
    kind: str
    text: str


@dataclass
class Report:
    summary: str
    new_surface: list[str]
    findings: list[Finding]


@dataclass
class Item:
    """One line of the review: a finding and the reviewers who found it."""

    finding: Finding
    by: list[str]


class SecretLikeError(Exception):
    """The report holds text that looks like a token, so nothing may be posted."""


# --- Reading the report ---


def _problem(data) -> str | None:
    """Return why the data has the wrong keys or types, or None when it fits.
    Lengths are not checked here: load_report cuts what is too long."""
    if not isinstance(data, dict) or set(data) != TOP_KEYS:
        return f"needs exactly the keys {sorted(TOP_KEYS)}"
    if not isinstance(data["summary"], str):
        return "summary must be a string"
    surface = data["new_surface"]
    if not isinstance(surface, list) or not all(isinstance(s, str) for s in surface):
        return "new_surface must be a list of strings"
    findings = data["findings"]
    if not isinstance(findings, list):
        return "findings must be a list"
    for item in findings[:FINDINGS_MAX]:
        if not isinstance(item, dict) or set(item) != FINDING_KEYS:
            return f"each finding needs exactly the keys {sorted(FINDING_KEYS)}"
        if not isinstance(item["path"], str):
            return "finding path must be a string"
        line = item["line"]
        if isinstance(line, bool) or not isinstance(line, int) or line < 1:
            return "finding line must be an integer of 1 or more"
        if item["kind"] not in KINDS:
            return f"finding kind must be one of {list(KINDS)}"
        if not isinstance(item["text"], str):
            return "finding text must be a string"
    return None


def _cut(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


def load_report(path: Path) -> Report | None:
    """Read findings.json. On any problem print one reason and return None."""
    try:
        data = json.loads(path.read_text())
    except OSError as error:
        print(f"No findings posted: cannot read {path}: {error.strerror}", file=sys.stderr)
        return None
    except ValueError as error:
        print(f"No findings posted: {path} is not JSON: {error}", file=sys.stderr)
        return None
    problem = _problem(data)
    if problem:
        print(f"No findings posted: {path} does not match the schema: {problem}", file=sys.stderr)
        return None
    # Too long is not a reason to lose the whole review: cut it and keep the rest.
    findings = [
        Finding(**{**item, "text": _cut(item["text"], TEXT_MAX)})
        for item in data["findings"][:FINDINGS_MAX]
    ]
    return Report(
        summary=_cut(data["summary"], SUMMARY_MAX),
        new_surface=data["new_surface"],
        findings=findings,
    )


# --- Keeping secrets out ---


def refuse_secret_like(report: Report) -> None:
    """Raise SecretLikeError when any text that would be posted looks like a token."""
    texts = [report.summary, *report.new_surface]
    for f in report.findings:
        texts += [f.path, f.text]
    if any(SECRET_LIKE.search(text) for text in texts):
        raise SecretLikeError


# --- Keeping people out of it ---


def quiet_mentions(text: str) -> str:
    """Put a word joiner after each @ that starts a word, so GitHub pings nobody."""
    return MENTION.sub("@" + WORD_JOINER, text)


# --- Building the comment ---

REVIEWERS = {"claude": "Claude", "luna": "Luna"}
TITLE = "**Agent review**"
MARKER = re.compile(r"<!-- kitden-sdlc:review claude=(\d+|x) luna=(\d+|x) both=(\d+) -->\s*\Z")
# The account that posts for a workflow's own token. Only its comments are ours.
BOT = "github-actions[bot]"
# A path we can safely put into a link. Anything else is shown as plain text.
SAFE_PATH = re.compile(r"[\w./+-]+\Z")
# Characters that mean something in Markdown or HTML.
SPECIAL = re.compile(r"[\\`*_{}\[\]()#!|~<>&]")


def marker(reports: dict[str, Report | None], items: list[Item]) -> str:
    """The comment's last line. count_reviews.py reads it: findings only this reviewer
    made (x when it gave no answer), and findings both made."""
    counts = [
        f"{name}={sum(i.by == [name] for i in items) if reports.get(name) else 'x'}"
        for name in REVIEWERS
    ]
    both = sum(len(i.by) > 1 for i in items)
    return f"<!-- kitden-sdlc:review {' '.join(counts)} both={both} -->"


def read_marker(body: str) -> dict[str, int | None] | None:
    """The counts in a review comment's marker (None for a reviewer that gave no answer),
    or None when the text does not end with the marker."""
    found = MARKER.search(body)
    if not found:
        return None
    claude, luna, both = (None if n == "x" else int(n) for n in found.groups())
    return {"claude": claude, "luna": luna, "both": both}


def our_marker(comment: dict) -> dict[str, int | None] | None:
    """The marker counts of a review comment we posted, or None for any other comment.
    A person's or another bot's comment that ends in the marker is not ours."""
    if (comment.get("user") or {}).get("login") != BOT:
        return None
    return read_marker(comment.get("body") or "")


def merge(reports: dict[str, Report | None]) -> list[Item]:
    """All findings as one list. Two reviewers' findings in the same file and within
    NEAR_LINES lines become one item, with the first reviewer's text. Shared ones go first."""
    items: list[Item] = []
    for name in REVIEWERS:
        report = reports.get(name)
        for f in report.findings if report else []:
            same = next(
                (
                    i
                    for i in items
                    if name not in i.by
                    and i.finding.path == f.path
                    and abs(i.finding.line - f.line) <= NEAR_LINES
                ),
                None,
            )
            if same:
                same.by.append(name)
            else:
                items.append(Item(f, [name]))
    return sorted(items, key=lambda i: -len(i.by))  # stable: the rest keep their order


def one_line(text: str) -> str:
    """Model text as plain text on one line: it cannot start a heading or a list, add a
    link, a picture or HTML, or ping anybody."""
    plain = SPECIAL.sub(lambda m: f"&#{ord(m.group())};", " ".join(text.split()))
    return quiet_mentions(plain)


def _bullet(item: Item, repo: str, head_sha: str) -> str:
    f = item.finding
    place = f"{f.path}:{f.line}"
    # A ".." part would lead the link out of the repository.
    if SAFE_PATH.match(f.path) and not f.path.startswith("/") and ".." not in f.path.split("/"):
        place = f"[`{place}`](https://github.com/{repo}/blob/{head_sha}/{quote(f.path)}#L{f.line})"
    else:
        place = one_line(place)
    who = "both" if len(item.by) > 1 else REVIEWERS[item.by[0]]
    return f"- {place} — {one_line(f.text)} *({who})*"


def review_body(
    reports: dict[str, Report | None], models: dict[str, str], repo: str, head_sha: str
) -> str:
    """The whole comment. `reports` has None for a reviewer that gave no usable answer."""
    names = " and ".join(f"{REVIEWERS[name]} ({models[name]})" for name in REVIEWERS)
    parts = [f"{TITLE} · automated, by {names} · commit {head_sha[:7]}"]
    answered = [report for name in REVIEWERS if (report := reports.get(name))]
    items = merge(reports)
    if answered:
        parts.append(one_line(answered[0].summary))
        if items:
            bullets = "\n".join(_bullet(item, repo, head_sha) for item in items)
            parts.append(f"**To check ({len(items)})**\n{bullets}")
        else:
            parts.append("No problems found.")
        if answered[0].new_surface:
            parts.append("**New for users:** " + "; ".join(map(one_line, answered[0].new_surface)))
    silent = [REVIEWERS[name] for name in REVIEWERS if not reports.get(name)]
    if silent:
        parts.append(" and ".join(silent) + " gave no usable answer this time.")
    parts.append("<sub>👍 useful · 👎 wrong</sub>")
    parts.append(marker(reports, items))
    return "\n\n".join(parts)


# --- Talking to GitHub ---


class Api(Protocol):
    def list_issue_comments(self, repo: str, pr: int) -> list[dict]: ...

    def create_issue_comment(self, repo: str, pr: int, body: str) -> None: ...

    def update_issue_comment(self, repo: str, comment_id: int, body: str) -> None: ...


class GhApi:
    """The Api on top of the gh command line tool."""

    def _run(self, *args: str) -> str:
        done = subprocess.run(  # noqa: S603
            ["gh", "api", *args],  # noqa: S607
            check=True,
            capture_output=True,
            text=True,
        )
        return done.stdout

    def _list(self, endpoint: str) -> list[dict]:
        # With --paginate, gh prints one JSON array per page, one after another.
        text = self._run(endpoint, "--paginate")
        decoder = json.JSONDecoder()
        items: list[dict] = []
        index = 0
        while index < len(text):
            if text[index].isspace():
                index += 1
                continue
            page, index = decoder.raw_decode(text, index)
            items += page
        return items

    def list_issue_comments(self, repo: str, pr: int) -> list[dict]:
        return self._list(f"repos/{repo}/issues/{pr}/comments")

    def create_issue_comment(self, repo: str, pr: int, body: str) -> None:
        self._run(f"repos/{repo}/issues/{pr}/comments", "--method", "POST", "-f", f"body={body}")

    def update_issue_comment(self, repo: str, comment_id: int, body: str) -> None:
        self._run(
            f"repos/{repo}/issues/comments/{comment_id}", "--method", "PATCH", "-f", f"body={body}"
        )


# --- Putting it together ---


def post(api: Api, repo: str, pr: int, body: str) -> None:
    """Update the one review comment, or create it.
    Only our own comment counts: anyone else's that ends in the marker cannot be edited
    with the job's token, and must not be."""
    if SECRET_LIKE.search(body):
        raise SecretLikeError
    for comment in api.list_issue_comments(repo, pr):
        if our_marker(comment):
            api.update_issue_comment(repo, comment["id"], body)
            return
    api.create_issue_comment(repo, pr, body)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--claude", type=Path, required=True, help="Claude's findings.json")
    parser.add_argument("--luna", type=Path, required=True, help="Luna's findings.json")
    parser.add_argument("--claude-model", default="dry-run")
    parser.add_argument("--luna-model", default="dry-run")
    parser.add_argument("--repo", default="owner/repo")
    parser.add_argument("--pr", type=int)
    parser.add_argument("--head-sha", default="0000000")
    parser.add_argument("--dry-run", action="store_true", help="print the comment, call nothing")
    args = parser.parse_args(argv)
    if not args.dry_run and args.pr is None:
        parser.error("--pr is required without --dry-run")

    # A missing or broken file must not fail the job. With one answer the comment says
    # who is missing; with none there is nothing to post.
    reports = {"claude": load_report(args.claude), "luna": load_report(args.luna)}
    for name, report in reports.items():
        if report is None:
            print(f"::warning::The {name} reviewer gave no usable answer this time.")
    if not any(reports.values()):
        return 0
    models = {"claude": args.claude_model, "luna": args.luna_model}
    try:
        for report in reports.values():
            if report:
                refuse_secret_like(report)
        body = review_body(reports, models, args.repo, args.head_sha)
        if args.dry_run:
            print(body)
        else:
            post(GhApi(), args.repo, args.pr, body)
    except SecretLikeError:
        # Not the missing-report case: fail loud so the job turns red.
        print("Refused: a reviewer's output looked like a secret", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
