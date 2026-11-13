"""Helpers the tests share."""

import os
import subprocess
from pathlib import Path

from bot_issues import BOT, names

# A key without its prefix: what is left when a model cuts off a token's first characters.
KEY_TAIL = "oat01-Zk3vQ9xLr7TnB2mWc8YpD4sHf6JgA1uE5N0aVbXe"


def shows_key(text: str, size: int = 8) -> bool:
    """Whether `text` holds any piece of KEY_TAIL `size` characters long."""
    return any(KEY_TAIL[i : i + size] in text for i in range(len(KEY_TAIL) - size + 1))


def _git(folder: Path, *args: str) -> None:
    # The developer's own git settings (signing, hooks) must not reach the test repository.
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env |= {"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}
    subprocess.run(["git", *args], cwd=folder, env=env, check=True, capture_output=True)


def repo(folder: Path, files: dict[str, str], links: dict[str, str] | None = None) -> Path:
    """A git repository in `folder` with one commit of `files` (name: text) and `links`
    (name: where the symbolic link points)."""
    folder.mkdir(parents=True, exist_ok=True)
    _git(folder, "init", "-q", "-b", "main")
    for name, text in files.items():
        path = folder / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    for name, target in (links or {}).items():
        (folder / name).symlink_to(target)
    _git(folder, "add", "-A")
    _git(folder, "-c", "user.name=Test", "-c", "user.email=test@example.com",
         "commit", "-q", "--no-verify", "-m", "Files")
    return folder


def issue(number: int, title: str = "t", labels: tuple[str, ...] = ("automated",),
          state: str = "open", created: str = "2026-11-01T00:00:00Z", closed: str | None = None,
          login: str = BOT, body: str = "") -> dict:
    """An issue as GitHub's REST API gives it, with the fields the scripts read."""
    return {"number": number, "title": title, "body": body, "state": state,
            "labels": [{"name": name} for name in labels], "user": {"login": login},
            "created_at": created, "closed_at": closed,
            "html_url": f"https://github.com/o/kitden/issues/{number}"}


class FakeIssues:
    """GhIssues without GitHub: the issues and labels it is given, and a record of each write."""

    repo = ""

    def __init__(self, issues=(), labels=()):
        self.issues = [dict(item) for item in issues]
        self.have = set(labels)
        self.created: list[tuple[str, str, list[str]]] = []
        self.edited: list[tuple[int, str, list[str]]] = []
        self.closed: list[int] = []
        self.commented: list[tuple[int, str]] = []
        self.created_labels: list[tuple[str, str, str]] = []
        self._comments: dict[int, list[dict]] = {}

    def _issue(self, number: int) -> dict:
        return next(item for item in self.issues if item["number"] == number)

    def by_bot(self, state="open", label="automated"):
        return [item for item in self.issues
                if state in ("all", item["state"]) and label in names(item)
                and "pull_request" not in item and item["user"]["login"] == BOT]

    def create(self, title, body, labels):
        self.created.append((title, body, list(labels)))
        number = max((item["number"] for item in self.issues), default=0) + 1
        self.issues.append(issue(number, title, tuple(labels), body=body))
        return self.issues[-1]["html_url"]

    def edit(self, number, body, labels):
        self.edited.append((number, body, list(labels)))
        item = self._issue(number)
        item["body"] = body
        item["labels"] += [{"name": name} for name in labels if name not in names(item)]

    def close(self, number):
        self.closed.append(number)
        self._issue(number)["state"] = "closed"

    def comment(self, number, body):
        self.commented.append((number, body))
        self._comments.setdefault(number, []).append({"user": {"login": BOT}, "body": body})

    def comments(self, number):
        return list(self._comments.get(number, []))

    def label_names(self):
        return set(self.have)

    def create_label(self, name, color, description):
        self.created_labels.append((name, color, description))
        self.have.add(name)
