"""Helpers the tests share."""

import os
import subprocess
from pathlib import Path

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
