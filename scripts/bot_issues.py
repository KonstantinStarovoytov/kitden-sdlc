"""The issues a bot opens in Kitden: known by their author, labelled by where they come from.

A bot never edits, labels or closes an issue a person opened, even one with the bot's title
and labels: `by_bot` keeps only the issues whose author is BOT.

`pause` stops an agent whose issues the owner mostly marks `false-alarm` (spec 1.5).

Standard library only: release_watch.py runs with `uv run --no-project`.
"""

import json
import subprocess  # noqa: S404
import urllib.parse

BOT = "kitden-lantern[bot]"  # the Lantern app; with your own app, put its bot name here

# The one label list (name, colour, description). A run creates the ones that are missing.
LABELS: tuple[tuple[str, str, str], ...] = (
    ("automated", "bfdadc",
     "Opened by an automated check; a maintainer confirms it before work starts"),
    ("client-change", "1d76db", "Opened by the watcher: a client changed"),
    ("release", "fef2c0", "Opened by the release watch"),
    ("desk", "006b75", "The owner's desk"),
    ("claude-code", "d97757", "Which client"),
    ("codex", "0e8a16", "Which client"),
    ("cursor", "5319e7", "Which client"),
    ("breaks", "b60205", "A Kitden action stops working"),
    ("wrong-data", "d93f0b", "Kitden shows something that is not true"),
    ("unknown", "c5def5", "Kitden cannot read the new value and says so"),
    ("outdated", "e4e669", "Kitden stays right; the list or a comment is out of date"),
    ("major", "5a0000", "A user acts on it and gets a result they did not expect"),
    ("medium", "f9d0c4", "A user does extra or useless steps"),
    ("minor", "ededed", "What a user does stays the same"),
    ("kitden-gap", "fbca04", "The client added something Kitden does not show yet"),
    ("unsure", "cccccc", "The watcher is not sure Kitden is touched"),
    ("summary", "0075ca", "The weekly summary"),
    ("confirmed", "2da44e", "Set by the owner: the bot was right; open until fixed"),
    ("false-alarm", "6e7781", "Set by the owner on closing: the bot was wrong"),
)

VERDICTS = ("confirmed", "false-alarm")  # set by the owner on an agent's issue
PAUSE_AFTER = 10  # the verdicts counted: with fewer there is no pause


class GhIssues:
    """Issues and labels of one repository through `gh api`, with the token in GH_TOKEN."""

    def __init__(self, repo: str):
        self.repo = repo

    def _run(self, *args: str) -> str:
        done = subprocess.run(  # noqa: S603
            ["gh", "api", *args],  # noqa: S607
            check=True, capture_output=True, text=True,
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

    def by_bot(self, state: str = "open", label: str = "automated") -> list[dict]:
        """The issues with this label whose author is BOT; pull requests are left out."""
        query = urllib.parse.urlencode({"state": state, "labels": label, "per_page": 100})
        return [
            item for item in self._list(f"repos/{self.repo}/issues?{query}")
            if "pull_request" not in item and (item.get("user") or {}).get("login") == BOT
        ]

    def create(self, title: str, body: str, labels: list[str]) -> str:
        """Open an issue; returns its address."""
        args = [f"repos/{self.repo}/issues", "--method", "POST", "-f", f"title={title}",
                "-f", f"body={body}", "--jq", ".html_url"]
        for name in labels:
            args += ["-f", f"labels[]={name}"]
        return self._run(*args).strip()

    def edit(self, number: int, body: str, labels: list[str]) -> None:
        """Set the body and add the labels; labels a person set stay."""
        self._run(f"repos/{self.repo}/issues/{number}", "--method", "PATCH", "-f", f"body={body}")
        args = [f"repos/{self.repo}/issues/{number}/labels", "--method", "POST"]
        for name in labels:
            args += ["-f", f"labels[]={name}"]
        self._run(*args)

    def close(self, number: int) -> None:
        self._run(f"repos/{self.repo}/issues/{number}", "--method", "PATCH", "-f", "state=closed")

    def comment(self, number: int, body: str) -> None:
        self._run(f"repos/{self.repo}/issues/{number}/comments", "--method", "POST",
                  "-f", f"body={body}")

    def comments(self, number: int) -> list[dict]:
        return self._list(f"repos/{self.repo}/issues/{number}/comments?per_page=100")

    def label_names(self) -> set[str]:
        return {label["name"] for label in self._list(f"repos/{self.repo}/labels?per_page=100")}

    def create_label(self, name: str, color: str, description: str) -> None:
        """Create a label. One that exists already, made by another run a moment ago, is no
        failure; any other failure raises."""
        try:
            self._run(f"repos/{self.repo}/labels", "--method", "POST", "-f", f"name={name}",
                      "-f", f"color={color}", "-f", f"description={description}")
        except subprocess.CalledProcessError as error:
            if not _label_exists(error):
                raise


def _label_exists(error: subprocess.CalledProcessError) -> bool:
    """Whether `gh api` failed because GitHub says the label exists. On an HTTP error gh exits
    1 and prints the response body on stdout; GitHub's 422 body lists the error code."""
    for text in (error.stdout, error.stderr):
        try:
            body = json.loads(text or "")
        except ValueError:
            continue
        errors = body.get("errors") if isinstance(body, dict) else None
        if isinstance(errors, list) and any(
            isinstance(item, dict) and item.get("resource") == "Label"
            and item.get("code") == "already_exists" for item in errors
        ):
            return True
    return False


def names(issue: dict) -> set[str]:
    """The names of an issue's labels; GitHub's schema allows a label as a bare name too."""
    return {label if isinstance(label, str) else label["name"]
            for label in issue.get("labels", [])}


def verdict(issue: dict) -> str | None:
    """The owner's verdict on an issue: `confirmed` or `false-alarm` when it carries exactly
    one of them, else None."""
    marks = names(issue) & set(VERDICTS)
    return marks.pop() if len(marks) == 1 else None


def ensure_labels(gh: GhIssues) -> None:
    """Create every label of LABELS that the repository does not have."""
    have = gh.label_names()
    for name, color, description in LABELS:
        if name not in have:
            gh.create_label(name, color, description)


def find_open(gh: GhIssues, title: str) -> int | None:
    """The number of the bot's open issue with exactly this title, or None."""
    for item in gh.by_bot("open"):
        if item["title"] == title:
            return item["number"]
    return None


def upsert(gh: GhIssues, title: str, body: str, labels: list[str]) -> None:
    """Edit the bot's open issue with this title, open one if none, close it when `body` is
    empty. An issue a person opened is never touched."""
    number = find_open(gh, title)
    if not body:
        if number is not None:
            gh.close(number)
    elif number is None:
        gh.create(title, body, labels)
    else:
        gh.edit(number, body, labels)


def paused_title(agent: str) -> str:
    return f"{agent} is paused"


def _pause_body(agent: str, wrong: list[dict], means: str) -> str:
    # Links only: the issues' titles were written by a model.
    links = "\n".join(f"- {item.get('html_url') or '#' + str(item['number'])}" for item in wrong)
    return (
        "Opened by a script in kitden-sdlc that counts the owner's verdicts; no AI model "
        "wrote it.\n\n"
        "## What happened\n\n"
        f"{agent} got `false-alarm` on {len(wrong)} of its last {PAUSE_AFTER} issues with a "
        f"verdict, more than half:\n\n{links}\n\n"
        "## What it means\n\n"
        f"{agent} opens no issue while this one is open. {means}\n\n"
        "## What to do\n\n"
        "Fix the prompt or the tasks, then close this issue. The count starts again from the "
        "issues opened after you close it.\n"
    )


def pause(gh: GhIssues, agent: str, origin: str, means: str) -> bool:
    """True when `agent` must open nothing now: the bot's "<agent> is paused" issue is open, or
    is opened here because more than half of the last PAUSE_AFTER verdicts on the bot's issues
    labelled `origin` are `false-alarm`. Only issues opened after the newest closed pause issue
    was closed count; summaries and issues with both verdicts do not. `means` is the caller's
    sentence on what the pause means for its work, put in the issue."""
    title = paused_title(agent)
    pauses = [item for item in gh.by_bot("all") if item["title"] == title]
    if any(item["state"] == "open" for item in pauses):
        return True
    # GitHub gives both times as ISO strings in UTC, so they compare as strings.
    since = max((item.get("closed_at") or "" for item in pauses), default="")
    judged = [
        item for item in gh.by_bot("all", origin)
        if "summary" not in names(item) and verdict(item) and item["created_at"] > since
    ]
    judged.sort(key=lambda item: (item["created_at"], item["number"]), reverse=True)
    last = judged[:PAUSE_AFTER]
    wrong = [item for item in last if verdict(item) == "false-alarm"]
    if len(last) < PAUSE_AFTER or 2 * len(wrong) <= len(last):
        return False
    gh.create(title, _pause_body(agent, wrong, means), ["automated", "desk"])
    return True
