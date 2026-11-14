"""Put the AI reviewers' findings on a pull request as one comment, edited in place.

Each run reviews the whole pull request again, and the models do not say the same thing
every time. So the comment remembers its findings, and a finding the latest review does not
repeat stays in the comment: as fixed when the lines it points to changed since, or else as
not repeated.
"""

import argparse
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol
from urllib.parse import quote

from secret_filter import has_commit, in_git, in_text, random_runs, unknown_runs

SUMMARY_MAX = 300
TEXT_MAX = 300
FINDINGS_MAX = 5
KINDS = ("bug", "rule")
TOP_KEYS = {"summary", "findings"}
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
# the same finding. Also how far an earlier finding may have moved and still be the
# same as a new one.
NEAR_LINES = 5
# An earlier finding counts as fixed when a line this close to it changed.
TOUCH_LINES = 2
# The most findings the comment keeps. Past it the oldest fixed ones go first; the
# counts in the marker still keep them.
ITEMS_MAX = 30
# GitHub's compare lists at most this many files. With that many we cannot tell what
# changed, so no earlier finding is marked fixed.
COMPARE_FILES_MAX = 300
COMMIT = re.compile(r"[0-9a-f]{7,40}\Z")


@dataclass
class Finding:
    path: str
    line: int
    kind: str
    text: str


@dataclass
class Report:
    summary: str
    findings: list[Finding]


@dataclass
class Item:
    """One line of the review: a finding and the reviewers who found it.

    `at` is the commit its path and line refer to, `seen` the last reviewed commit that
    reported it, and `fixed` the commit that changed its lines after it was last reported
    (empty while it is not fixed). `now` is True when this run reported it; it is not kept
    for the next run."""

    finding: Finding
    by: list[str]
    seen: str = ""
    at: str = ""
    fixed: str = ""
    now: bool = False


@dataclass
class Earlier:
    """What the comment remembers from the runs before this one."""

    head: str  # the commit the last run reviewed
    answered: list[str]  # reviewers that gave a usable answer in any run
    items: list[Item]
    dropped: dict[str, int]  # findings left out of the comment, counted as in the marker


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
    findings = data["findings"]
    if not isinstance(findings, list):
        return "findings must be a list"
    for item in findings[:FINDINGS_MAX]:
        problem = _finding_problem(item, FINDING_KEYS)
        if problem:
            return problem
    return None


def _finding_problem(item, keys: set[str]) -> str | None:
    if not isinstance(item, dict) or set(item) != keys:
        return f"each finding needs exactly the keys {sorted(keys)}"
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
        findings=findings,
    )


# --- Keeping secrets out ---


def report_texts(report: Report) -> list[str]:
    """Every text of the report that would be posted."""
    texts = [report.summary]
    for f in report.findings:
        texts += [f.path, f.text]
    return texts


def refuse_secret_like(report: Report) -> None:
    """Raise SecretLikeError when any text that would be posted looks like a token."""
    if any(SECRET_LIKE.search(text) for text in report_texts(report)):
        raise SecretLikeError


def refuse_unknown_runs(
    api: "Api",
    repo: str,
    pr: int,
    reports: dict[str, Report | None],
    tree: Path | None,
    head_sha: str,
    base_sha: str | None = None,
    names: dict[str, str] | None = None,
) -> None:
    """Raise SecretLikeError when the reports hold a long random string (a key cut short)
    that the reviewers were not given: it is not in the pull request's title and body, nor
    in the files or file names of its head commit or of its base commit, which `tree`
    holds. Without `tree`, only the title and body count; with a `tree` that lacks the head
    commit, nothing does. The pull request is read only when there is such a string. The
    message counts the strings and never shows one: each may be a key."""
    texts = {name: report_texts(report) for name, report in reports.items() if report}
    if not any(random_runs(text) for each in texts.values() for text in each):
        return
    # The fetch of the pull request's commits failed: then nothing counts as known.
    unread = tree is not None and not has_commit(tree, head_sha)
    sources = []
    if not unread:
        pull = api.pull_text(repo, pr)
        if pull is None:
            print("::warning::Cannot read the pull request's title and body; nothing in them "
                  "counts as known.")
        else:
            sources.append(in_text(pull))
        if tree:
            sources += [in_git(tree, sha) for sha in (head_sha, base_sha) if sha]
    counts = {
        name: len(unknown_runs(each, lambda run: any(known(run) for known in sources)))
        for name, each in texts.items()
    }
    names = names or REVIEWERS
    held = [f"{n} in {names[name]}'s text" for name, n in counts.items() if n]
    if held:
        why = "long random strings that are not in what the reviewers were given: "
        why += ", ".join(held)
        if unread:
            why += "; the pull request's files could not be read, so every long random string"
            why += " is refused"
        raise SecretLikeError(why)


# --- Keeping people out of it ---


def quiet_mentions(text: str) -> str:
    """Put a word joiner after each @ that starts a word, so GitHub pings nobody."""
    return MENTION.sub("@" + WORD_JOINER, text)


# --- Building the comment ---

REVIEWERS = {"claude": "Claude", "luna": "Luna"}
SHORT_NAMES = {"sonnet": "Sonn"}

TITLE = "**Agent review**"
MARKER = re.compile(r"<!-- kitden-sdlc:review claude=(\d+|x) luna=(\d+|x) both=(\d+) -->\s*\Z")
# The findings the comment remembers, as JSON in an HTML comment. These characters are
# escaped in it: < > & and - so the text cannot end the HTML comment, @ # and / so it
# holds no mention, issue reference or link GitHub could act on. Model text in the
# visible part is escaped too (one_line), so only this script writes a line that starts
# with "<!--".
STATE = re.compile(r"^<!-- kitden-sdlc:state (\{[^\n]*\}) -->$", re.MULTILINE)
STATE_ESCAPED = "<>&-@#/"
STATE_KEYS = {"head", "answered", "items", "dropped"}
ITEM_KEYS = FINDING_KEYS | {"by", "seen", "at", "fixed"}
COUNT_KEYS = {*REVIEWERS, "both"}
# The accounts that post for us: the review app, and the workflow's own token when the
# app is not set up. Only their comments are ours.
BOTS = ("kitden-lantern[bot]", "github-actions[bot]")
# A path we can safely put into a link. Anything else is shown as plain text.
SAFE_PATH = re.compile(r"[\w./+-]+\Z")
# Characters that mean something in Markdown or HTML.
SPECIAL = re.compile(r"[\\`*_{}\[\]()#!|~<>&]")


def model_label(model: str) -> str:
    """How the comment names the Claude reviewer: its model family, like Luna is named
    by its model. `claude-sonnet-5-5` gives Sonn (the owner's short name),
    `claude-opus-5-5` gives Opus; anything else gives Claude."""
    parts = model.split("-")
    if len(parts) > 1 and parts[0] == "claude" and parts[1].isalpha():
        return SHORT_NAMES.get(parts[1], parts[1].capitalize())
    return "Claude"


def marker(answered: list[str], items: list[Item], dropped: dict[str, int] | None = None) -> str:
    """The comment's last line. count_reviews.py reads it: findings only this reviewer
    made (x when it never gave an answer on this pull request), and findings both made.
    Earlier findings count too, also the ones left out of the comment."""
    dropped = dropped or {}
    counts = [
        f"{name}={sum(i.by == [name] for i in items) + dropped.get(name, 0)}"
        if name in answered
        else f"{name}=x"
        for name in REVIEWERS
    ]
    both = sum(len(i.by) > 1 for i in items) + dropped.get("both", 0)
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
    if (comment.get("user") or {}).get("login") not in BOTS:
        return None
    return read_marker(comment.get("body") or "")


def find_ours(comments: list[dict]) -> dict | None:
    """Our review comment on the pull request, or None."""
    return next((c for c in comments if our_marker(c)), None)


def state_line(earlier: Earlier) -> str:
    """The hidden line that lets the next run know this run's findings."""
    data = {
        "head": earlier.head,
        "answered": earlier.answered,
        "items": [
            {
                "path": i.finding.path,
                "line": i.finding.line,
                "kind": i.finding.kind,
                "text": i.finding.text,
                "by": i.by,
                "seen": i.seen,
                "at": i.at,
                "fixed": i.fixed,
            }
            for i in earlier.items
        ],
        "dropped": earlier.dropped,
    }
    text = json.dumps(data, ensure_ascii=True, separators=(",", ":"))
    # None of these is part of JSON's own syntax here (no number is negative), so each
    # can only stand inside a string, where \\uXXXX means the same.
    for char in STATE_ESCAPED:
        text = text.replace(char, f"\\u{ord(char):04x}")
    return f"<!-- kitden-sdlc:state {text} -->"


def _item_from(data) -> Item | None:
    if _finding_problem(data, ITEM_KEYS):
        return None
    by = data["by"]
    if not isinstance(by, list) or not by or len(set(by)) != len(by) or set(by) - set(REVIEWERS):
        return None
    if not all(isinstance(data[k], str) and COMMIT.match(data[k]) for k in ("seen", "at")):
        return None
    fixed = data["fixed"]
    if not isinstance(fixed, str) or (fixed and not COMMIT.match(fixed)):
        return None
    finding = Finding(data["path"], data["line"], data["kind"], _cut(data["text"], TEXT_MAX))
    return Item(finding, [n for n in REVIEWERS if n in by], data["seen"], data["at"], fixed)


def read_state(body: str) -> Earlier | None:
    """The findings an earlier run left in our comment, or None when there are none or
    they do not read back cleanly."""
    found = STATE.findall(body)
    if not found:
        return None
    try:
        data = json.loads(found[-1])
    except ValueError:
        return None
    if not isinstance(data, dict) or set(data) != STATE_KEYS:
        return None
    head, answered, raw_items, dropped = (data[k] for k in ("head", "answered", "items", "dropped"))
    if not isinstance(head, str) or not COMMIT.match(head):
        return None
    if not isinstance(answered, list) or not set(answered) <= set(REVIEWERS):
        return None
    if not isinstance(raw_items, list) or len(raw_items) > ITEMS_MAX:
        return None
    if not isinstance(dropped, dict) or set(dropped) != COUNT_KEYS:
        return None
    if not all(isinstance(n, int) and not isinstance(n, bool) and n >= 0 for n in dropped.values()):
        return None
    items = [item for raw in raw_items if (item := _item_from(raw))]
    if len(items) != len(raw_items):
        return None
    return Earlier(head, [n for n in REVIEWERS if n in answered], items, dropped)


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


# --- What changed since the last review ---


HUNK = re.compile(r"@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


@dataclass
class FileChange:
    """How one file changed between the last reviewed commit and this one. Line numbers
    on the left are the old file's."""

    path: str  # its name now
    removed: bool = False
    known: bool = True  # False when GitHub sent no diff for it
    touched: frozenset[int] = frozenset()  # lines removed, or next to added ones
    moved: dict[int, int] | None = None  # old line -> new line, inside the hunks
    shifts: tuple[tuple[int, int], ...] = ()  # (first old line after a hunk, lines it adds)

    def touches(self, line: int) -> bool:
        return self.removed or any(abs(t - line) <= TOUCH_LINES for t in self.touched)

    def new_line(self, line: int) -> int:
        if self.moved and line in self.moved:
            return self.moved[line]
        return max(1, line + sum(delta for after, delta in self.shifts if after <= line))


def parse_patch(path: str, patch: str) -> FileChange:
    """Read the hunks of one file's diff: which old lines changed, and where the rest went."""
    touched: set[int] = set()
    moved: dict[int, int] = {}
    shifts: list[tuple[int, int]] = []
    old = new = 0
    for text in patch.splitlines():
        hunk = HUNK.match(text)
        if hunk:
            old_start, new_start = int(hunk[1]), int(hunk[3])
            old_len, new_len = int(hunk[2] or 1), int(hunk[4] or 1)
            # A length of 0 means the hunk sits after that line, not on it.
            old = old_start if old_len else old_start + 1
            new = new_start if new_len else new_start + 1
            shifts.append((old + old_len, new_len - old_len))
        elif not old:
            continue  # before the first hunk
        elif text.startswith(" "):
            moved[old] = new
            old, new = old + 1, new + 1
        elif text.startswith("-"):
            touched.add(old)
            moved[old] = new
            old += 1
        elif text.startswith("+"):
            touched.update((old - 1, old))
            new += 1
    return FileChange(path, touched=frozenset(touched), moved=moved, shifts=tuple(shifts))


def file_changes(compare) -> dict[str, FileChange] | None:
    """The files GitHub's compare says changed, by their old name, or None when the
    answer does not tell us enough (no answer, a force push, too many files)."""
    if not isinstance(compare, dict) or compare.get("status") not in ("ahead", "identical"):
        return None
    files = compare.get("files") or []
    if not isinstance(files, list) or len(files) >= COMPARE_FILES_MAX:
        return None
    changes: dict[str, FileChange] = {}
    for f in files:
        if not isinstance(f, dict) or not isinstance(f.get("filename"), str):
            return None
        name: str = f["filename"]
        before = f.get("previous_filename")
        old = before if isinstance(before, str) else name
        patch = f.get("patch")
        if f.get("status") == "removed":
            changes[old] = FileChange(name, removed=True)
        elif isinstance(patch, str):
            changes[old] = parse_patch(name, patch)
        else:
            # Only a rename with no other change is known to need no diff.
            changes[old] = FileChange(name, known=f.get("changes") == 0)
    return changes


def carry(
    now: list[Item], earlier: Earlier | None, head: str, changes: dict[str, FileChange] | None
) -> list[Item]:
    """This run's items, then the earlier ones it did not repeat: first those still open,
    then the fixed ones. `changes` is what changed since `earlier.head`; None when unknown.

    An earlier finding that this run reports again (same file, within NEAR_LINES after
    following the diff) is one item, found by everyone who found it."""
    for item in now:
        item.seen = item.at = head
        item.now = True
    if not earlier:
        return now
    if earlier.head == head:
        changes = {}
    matched: set[int] = set()
    open_: list[Item] = []
    fixed: list[Item] = []
    for old in earlier.items:
        f = old.finding
        # Only a finding whose line refers to the last reviewed commit can follow its diff.
        known = changes is not None and old.at == earlier.head
        change = changes.get(f.path) if changes is not None and known else None
        follows = known and (change is None or (change.known and not change.removed))
        path, line = f.path, f.line
        if change and follows:
            path, line = change.path, change.new_line(f.line)
        same = next(
            (
                i
                for i in now
                if id(i) not in matched
                and i.finding.path == path
                and abs(i.finding.line - line) <= NEAR_LINES
            ),
            None,
        )
        if same:
            matched.add(id(same))
            same.by = [n for n in REVIEWERS if n in same.by or n in old.by]
        elif old.fixed:
            fixed.append(old)
        elif change and (change.removed or (change.known and change.touches(f.line))):
            fixed.append(Item(f, old.by, old.seen, old.at, head))
        elif follows:
            open_.append(Item(Finding(path, line, f.kind, f.text), old.by, old.seen, head))
        else:
            open_.append(old)
    now = sorted(now, key=lambda i: -len(i.by))
    return now + open_ + fixed


def trim(items: list[Item], dropped: dict[str, int]) -> tuple[list[Item], dict[str, int]]:
    """Keep at most ITEMS_MAX items, in carry's order. The first to go is the oldest fixed
    one (fixed ones are listed oldest first), then the last earlier open one (each run
    puts its own first, so the last has been carried longest). This run's findings stay.
    What is left out is added to `dropped`."""
    items, dropped = list(items), dict(dropped)
    while len(items) > ITEMS_MAX:
        earlier = [i for i in items if not i.now]
        gone = next((i for i in items if i.fixed), None) or (earlier[-1] if earlier else items[-1])
        items.remove(gone)
        key = "both" if len(gone.by) > 1 else gone.by[0]
        dropped[key] = dropped.get(key, 0) + 1
    return items, dropped


def one_line(text: str) -> str:
    """Model text as plain text on one line: it cannot start a heading or a list, add a
    link, a picture or HTML, or ping anybody."""
    plain = SPECIAL.sub(lambda m: f"&#{ord(m.group())};", " ".join(text.split()))
    return quiet_mentions(plain)


def _bullet(item: Item, repo: str, names: dict[str, str] = REVIEWERS, note: str = "") -> str:
    f = item.finding
    place = f"{f.path}:{f.line}"
    # A ".." part would lead the link out of the repository.
    if SAFE_PATH.match(f.path) and not f.path.startswith("/") and ".." not in f.path.split("/"):
        url = f"https://github.com/{repo}/blob/{item.at}/{quote(f.path)}#L{f.line}"
        place = f"[`{place}`]({url})"
    else:
        place = one_line(place)
    who = "both" if len(item.by) > 1 else names[item.by[0]]
    return f"- {place} — {one_line(f.text)} *({who}{note})*"


def review_body(
    reports: dict[str, Report | None],
    repo: str,
    head_sha: str,
    earlier: Earlier | None = None,
    changes: dict[str, FileChange] | None = None,
    names: dict[str, str] = REVIEWERS,
) -> str:
    """The whole comment. `reports` has None for a reviewer that gave no usable answer.
    `earlier` is what the comment held before, and `changes` what changed since. `names`
    are the reviewers' names as the comment shows them.

    With no answer at all this commit was not reviewed: the earlier findings stay as they
    were, none is marked fixed, and the hidden line keeps the last reviewed commit, so the
    next review compares from there."""
    parts = [TITLE]
    answered_now = [name for name in REVIEWERS if reports.get(name)]
    answered = [n for n in REVIEWERS if n in answered_now or (earlier and n in earlier.answered)]
    reviewed = head_sha
    if not answered_now:
        reviewed, changes = (earlier.head if earlier else head_sha), {}
    items, dropped = trim(
        carry(merge(reports), earlier, reviewed, changes),
        earlier.dropped if earlier else {name: 0 for name in [*REVIEWERS, "both"]},
    )
    # Earlier text was checked when it was first posted; check it again all the same.
    refuse_secret_like(Report("", [i.finding for i in items]))
    current = [i for i in items if i.now]
    still = [i for i in items if not i.now and not i.fixed]
    fixed = [i for i in items if not i.now and i.fixed]
    latest = next((r for name in REVIEWERS if (r := reports.get(name))), None)
    if not latest:
        commit = one_line(head_sha[:7])
        parts.append(f"Neither reviewer gave a usable answer for {commit}. This is not a review.")
    else:
        parts.append(one_line(latest.summary))
        if current:
            bullets = "\n".join(_bullet(item, repo, names) for item in current)
            parts.append(f"**To check ({len(current)})**\n{bullets}")
        elif still:
            parts.append("No new problems found. The earlier findings below stay until fixed.")
        else:
            parts.append("No problems found.")
    if still:
        bullets = "\n".join(_bullet(i, repo, names, f", found in {i.seen[:7]}") for i in still)
        parts.append(
            f"**Not repeated by the latest review ({len(still)})**\n"
            "Found on an earlier push. Nothing shows that their lines changed since, "
            f"so they may still be there.\n{bullets}"
        )
    if fixed:
        bullets = "\n".join(_bullet(i, repo, names, f", fixed in {i.fixed[:7]}") for i in fixed)
        parts.append(
            f"**Fixed ({len(fixed)})**\n"
            f"The lines these point to changed after they were found.\n{bullets}"
        )
    left_out = sum(dropped.values())
    if left_out:
        parts.append(f"{left_out} older findings are left out to keep this comment short.")
    silent = [names[name] for name in REVIEWERS if not reports.get(name)]
    if latest and silent:
        parts.append(" and ".join(silent) + " gave no usable answer this time.")
    parts.append("<sub>👍 useful · 👎 wrong</sub>")
    parts.append(state_line(Earlier(reviewed, answered, items, dropped)))
    parts.append(marker(answered, items, dropped))
    return "\n\n".join(parts)


# --- Talking to GitHub ---


class Api(Protocol):
    def list_issue_comments(self, repo: str, pr: int) -> list[dict]: ...

    def create_issue_comment(self, repo: str, pr: int, body: str) -> None: ...

    def update_issue_comment(self, repo: str, comment_id: int, body: str) -> None: ...

    def compare(self, repo: str, base: str, head: str) -> dict | None: ...

    def pull_text(self, repo: str, pr: int) -> str | None: ...


class GhApi:
    """The Api on top of the gh command line tool. `read_token`, when given, is used to
    compare commits: the review app's token may only write to pull requests."""

    def __init__(self, read_token: str | None = None):
        self.read_token = read_token

    def _run(self, *args: str, token: str | None = None) -> str:
        done = subprocess.run(  # noqa: S603
            ["gh", "api", *args],  # noqa: S607
            check=True,
            capture_output=True,
            text=True,
            env={**os.environ, "GH_TOKEN": token} if token else None,
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

    def compare(self, repo: str, base: str, head: str) -> dict | None:
        """GitHub's compare of two commits, or None when it fails (say, after a force push)."""
        try:
            data = json.loads(
                self._run(f"repos/{repo}/compare/{base}...{head}", token=self.read_token)
            )
        except (subprocess.CalledProcessError, ValueError):
            return None
        return data if isinstance(data, dict) else None

    def pull_text(self, repo: str, pr: int) -> str | None:
        """The pull request's title, a new line, and its body, or None when gh fails."""
        try:
            data = json.loads(self._run(f"repos/{repo}/pulls/{pr}", token=self.read_token))
        except (subprocess.CalledProcessError, ValueError):
            return None
        if not isinstance(data, dict):
            return None
        return f"{data.get('title') or ''}\n{data.get('body') or ''}"


# --- Putting it together ---


def post(api: Api, repo: str, pr: int, body: str, comments: list[dict] | None = None) -> None:
    """Update the one review comment, or create it.
    Only our own comment counts: anyone else's that ends in the marker must not be edited."""
    if SECRET_LIKE.search(body):
        raise SecretLikeError
    ours = find_ours(api.list_issue_comments(repo, pr) if comments is None else comments)
    if ours:
        api.update_issue_comment(repo, ours["id"], body)
    else:
        api.create_issue_comment(repo, pr, body)


def earlier_review(
    api: Api, repo: str, head_sha: str, ours: dict | None
) -> tuple[Earlier | None, dict[str, FileChange] | None]:
    """What our comment held, and what changed since the commit it reviewed."""
    if not ours:
        return None, None
    earlier = read_state(ours.get("body") or "")
    if earlier is None:
        print("::notice::The review comment holds no earlier findings this script can read.")
        return None, None
    if earlier.head == head_sha or not COMMIT.match(head_sha):
        return earlier, None
    changes = file_changes(api.compare(repo, earlier.head, head_sha))
    if changes is None:
        since = earlier.head[:7]
        print(f"::notice::Cannot tell what changed since {since}; no finding is marked fixed.")
    return earlier, changes


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--claude", type=Path, required=True, help="Claude's findings.json")
    parser.add_argument("--luna", type=Path, required=True, help="Luna's findings.json")
    parser.add_argument("--claude-model", default="", help="Claude's model, for its name")
    parser.add_argument("--repo", default="owner/repo")
    parser.add_argument("--pr", type=int)
    parser.add_argument("--head-sha", default="0000000")
    parser.add_argument(
        "--tree", type=Path, help="a git repository holding --head-sha, to look up quoted strings"
    )
    parser.add_argument("--base-sha", help="the base commit in --tree, also known to the reviewers")
    parser.add_argument("--dry-run", action="store_true", help="print the comment, call nothing")
    args = parser.parse_args(argv)
    if not args.dry_run and args.pr is None:
        parser.error("--pr is required without --dry-run")

    # A missing or broken file must not fail the job. The comment says who is missing;
    # with no answer at all it says this commit was not reviewed.
    reports = {"claude": load_report(args.claude), "luna": load_report(args.luna)}
    for name, report in reports.items():
        if report is None:
            print(f"::warning::The {name} reviewer gave no usable answer this time.")
    try:
        for report in reports.values():
            if report:
                refuse_secret_like(report)
        names = {**REVIEWERS, "claude": model_label(args.claude_model)}
        if args.dry_run:
            print(review_body(reports, args.repo, args.head_sha, names=names))
            return 0
        api = GhApi(read_token=os.environ.get("GH_READ_TOKEN") or None)
        refuse_unknown_runs(
            api, args.repo, args.pr, reports, args.tree, args.head_sha, args.base_sha, names
        )
        comments = api.list_issue_comments(args.repo, args.pr)
        earlier, changes = earlier_review(api, args.repo, args.head_sha, find_ours(comments))
        body = review_body(reports, args.repo, args.head_sha, earlier, changes, names)
        post(api, args.repo, args.pr, body, comments)
    except SecretLikeError as error:
        # Not the missing-report case: fail loud so the job turns red.
        why = str(error) or "a reviewer's output looked like a secret"
        print(f"Refused: {why}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
