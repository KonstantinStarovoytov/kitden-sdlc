"""Post an AI reviewer's findings.json to a pull request, once each."""

import argparse
import json
import re
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Protocol

SUMMARY_MAX = 1200
TEXT_MAX = 600
FINDINGS_MAX = 10
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
# How close (in lines) a new finding may be to a posted one of the same kind and file
# and still count as the same finding, since lines shift when the author pushes again.
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
class Plan:
    inline: list[Finding]
    overflow: list[Finding]


class SecretLikeError(Exception):
    """The report holds text that looks like a token, so nothing may be posted."""


class ApiError(Exception):
    def __init__(self, status: int):
        super().__init__(f"GitHub API error {status}")
        self.status = status


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


def without_mentions(report: Report) -> Report:
    return Report(
        summary=quiet_mentions(report.summary),
        new_surface=[quiet_mentions(line) for line in report.new_surface],
        findings=[Finding(f.path, f.line, f.kind, quiet_mentions(f.text)) for f in report.findings],
    )


# --- Building the comments ---


def marker(reviewer: str, key: str) -> str:
    return f"<!-- kitden-agents:{reviewer}:{key} -->"


def finding_key(f: Finding) -> str:
    return f"{f.path}:{f.line}:{f.kind}"


def first_line(reviewer: str, model: str) -> str:
    return f"Automated review by Kitden's {reviewer} reviewer ({model}). 👍 useful · 👎 wrong"


MARKER = re.compile(r"<!-- kitden-agents:([^:\s]+):(.+?) -->\s*\Z")


def read_marker(body: str) -> tuple[str, str] | None:
    """Return (reviewer, key) from the marker at the very end of a comment, or None."""
    found = MARKER.search(body)
    return (found.group(1), found.group(2)) if found else None


def posted_keys(review_comments: list[dict], reviewer: str) -> set[str]:
    """Keys of findings already posted. Only a marker at the very end of a comment counts."""
    keys = set()
    for comment in review_comments:
        found = read_marker(comment.get("body") or "")
        if found and found[0] == reviewer:
            keys.add(found[1])
    return keys


def _parse_key(key: str) -> tuple[str, int, str] | None:
    """Split a finding key "path:line:kind" (the path may hold colons)."""
    parts = key.rsplit(":", 2)
    if len(parts) != 3 or not parts[1].isdigit():
        return None
    return parts[0], int(parts[1]), parts[2]


def _already_posted(f: Finding, posted: list[tuple[str, int, str]]) -> bool:
    return any(
        path == f.path and kind == f.kind and abs(line - f.line) <= NEAR_LINES
        for path, line, kind in posted
    )


def plan_posts(report: Report, posted_keys: set[str], limit: int = 5) -> Plan:
    posted = [found for key in posted_keys if (found := _parse_key(key))]
    new = [f for f in report.findings if not _already_posted(f, posted)]
    return Plan(inline=new[:limit], overflow=new[limit:])


def _bullet(f: Finding) -> str:
    return f"- `{f.path}:{f.line}` ({f.kind}): {f.text}"


def inline_body(f: Finding, reviewer: str, model: str) -> str:
    key = finding_key(f)
    return f"{first_line(reviewer, model)}\n\n{f.text}\n\n{marker(reviewer, key)}"


def summary_body(
    report: Report,
    reviewer: str,
    model: str,
    overflow: list[Finding],
    outside_diff: list[Finding],
) -> str:
    parts = [first_line(reviewer, model), report.summary]
    if report.new_surface:
        items = "\n".join(f"- {line}" for line in report.new_surface)
        parts.append(f"Adds something a user can see or set:\n{items}")
    if overflow:
        parts.append("More findings, not posted inline:\n" + "\n".join(map(_bullet, overflow)))
    if outside_diff:
        parts.append("Outside the diff:\n" + "\n".join(map(_bullet, outside_diff)))
    parts.append(marker(reviewer, "summary"))
    return "\n\n".join(parts)


def no_answer_body(reviewer: str, model: str) -> str:
    return "\n\n".join(
        [
            first_line(reviewer, model),
            f"The {reviewer} reviewer gave no usable answer this time.",
            marker(reviewer, "summary"),
        ]
    )


# --- Talking to GitHub ---


class Api(Protocol):
    def list_review_comments(self, repo: str, pr: int) -> list[dict]: ...

    def list_issue_comments(self, repo: str, pr: int) -> list[dict]: ...

    def create_review_comment(
        self, repo: str, pr: int, body: str, commit_id: str, path: str, line: int
    ) -> None: ...

    def create_issue_comment(self, repo: str, pr: int, body: str) -> None: ...

    def update_issue_comment(self, repo: str, comment_id: int, body: str) -> None: ...


class GhApi:
    """The Api on top of the gh command line tool."""

    def _run(self, *args: str) -> str:
        done = subprocess.run(  # noqa: S603
            ["gh", "api", *args],  # noqa: S607
            check=False,
            capture_output=True,
            text=True,
        )
        if done.returncode != 0:
            found = re.search(r"HTTP (\d{3})", done.stderr)
            raise ApiError(int(found.group(1)) if found else 0)
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

    def list_review_comments(self, repo: str, pr: int) -> list[dict]:
        return self._list(f"repos/{repo}/pulls/{pr}/comments")

    def list_issue_comments(self, repo: str, pr: int) -> list[dict]:
        return self._list(f"repos/{repo}/issues/{pr}/comments")

    def create_review_comment(
        self, repo: str, pr: int, body: str, commit_id: str, path: str, line: int
    ) -> None:
        self._run(
            f"repos/{repo}/pulls/{pr}/comments",
            "--method", "POST",
            "-f", f"body={body}",
            "-f", f"commit_id={commit_id}",
            "-f", f"path={path}",
            "-F", f"line={line}",
            "-f", "side=RIGHT",
        )  # fmt: skip

    def create_issue_comment(self, repo: str, pr: int, body: str) -> None:
        self._run(f"repos/{repo}/issues/{pr}/comments", "--method", "POST", "-f", f"body={body}")

    def update_issue_comment(self, repo: str, comment_id: int, body: str) -> None:
        self._run(
            f"repos/{repo}/issues/comments/{comment_id}", "--method", "PATCH", "-f", f"body={body}"
        )


# --- Putting it together ---


def post(
    report: Report,
    api: Api,
    repo: str,
    pr: int,
    head_sha: str,
    reviewer: str,
    model: str,
    limit: int = 5,
) -> None:
    refuse_secret_like(report)  # before any call to GitHub
    report = without_mentions(report)
    done = posted_keys(api.list_review_comments(repo, pr), reviewer)
    plan = plan_posts(report, done, limit)
    outside_diff: list[Finding] = []
    for f in plan.inline:
        try:
            api.create_review_comment(
                repo, pr, inline_body(f, reviewer, model), head_sha, f.path, f.line
            )
        except ApiError as error:
            if error.status != 422:
                raise
            outside_diff.append(f)  # the line is not part of the diff
    body = summary_body(report, reviewer, model, plan.overflow, outside_diff)
    put_summary(api, repo, pr, reviewer, body)


def put_summary(api: Api, repo: str, pr: int, reviewer: str, body: str) -> None:
    """Update this reviewer's one summary comment, or create it.
    Only a bot's comment counts: a person's comment that ends in the marker cannot be
    edited with the job's token, and must not be."""
    if SECRET_LIKE.search(body):
        raise SecretLikeError
    tag = marker(reviewer, "summary")
    for comment in api.list_issue_comments(repo, pr):
        is_bot = (comment.get("user") or {}).get("type") == "Bot"
        if is_bot and (comment.get("body") or "").rstrip().endswith(tag):
            api.update_issue_comment(repo, comment["id"], body)
            return
    api.create_issue_comment(repo, pr, body)


def post_no_answer(api: Api, repo: str, pr: int, reviewer: str, model: str) -> None:
    print(f"::warning::The {reviewer} reviewer gave no usable answer this time.")
    put_summary(api, repo, pr, reviewer, no_answer_body(reviewer, model))


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--repo")
    parser.add_argument("--pr", type=int)
    parser.add_argument("--head-sha")
    parser.add_argument("--reviewer")
    parser.add_argument("--model")
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--dry-run", action="store_true", help="print the plan, call nothing")
    args = parser.parse_args(argv)

    if args.dry_run:
        args.reviewer = args.reviewer or "claude"
        args.model = args.model or "dry-run"
    else:
        for name in ("repo", "pr", "head_sha", "reviewer", "model"):
            if getattr(args, name) is None:
                parser.error(f"--{name.replace('_', '-')} is required without --dry-run")

    report = load_report(args.report)

    try:
        if report is None:
            # A missing or broken file must not fail the job, but it must not be silent.
            if not args.dry_run:
                post_no_answer(GhApi(), args.repo, args.pr, args.reviewer, args.model)
            return 0
        if args.dry_run:
            refuse_secret_like(report)
            report = without_mentions(report)
            plan = plan_posts(report, set(), args.limit)
            out = {
                "inline": [asdict(f) for f in plan.inline],
                "overflow": [asdict(f) for f in plan.overflow],
                "summary": summary_body(report, args.reviewer, args.model, plan.overflow, []),
            }
            print(json.dumps(out, indent=2, ensure_ascii=False))
        else:
            post(
                report, GhApi(), args.repo, args.pr, args.head_sha,
                args.reviewer, args.model, args.limit,
            )  # fmt: skip
    except SecretLikeError:
        # Not the missing-report case: fail loud so the job turns red.
        print(f"{args.reviewer} refused: output looked like a secret", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
