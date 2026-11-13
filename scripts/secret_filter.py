"""Find a key whose first characters were cut off: a long random-looking string that is
nowhere in the text the model was given.

A known token (a prefix plus a long tail) is caught by SECRET_LIKE in post_findings.py. A
tail alone has no prefix to match, so a long run of key characters in model text counts as
a leak unless the model could have copied it from its input. Standard library only: the
scripts that use this run without the project's dependencies.
"""

import os
import re
import subprocess
from collections.abc import Callable, Iterable
from pathlib import Path

RUN_MIN = 32
RUN = re.compile(rf"[A-Za-z0-9_-]{{{RUN_MIN},}}")


def _looks_random(run: str) -> bool:
    return (
        any(c.isdigit() for c in run)
        and any(c.islower() for c in run)
        and any(c.isupper() for c in run)
    )


def random_runs(text: str) -> list[str]:
    """Every run of RUN_MIN or more of A-Z a-z 0-9 _ - that has a digit, a lower-case and
    an upper-case letter."""
    return [run for run in RUN.findall(text) if _looks_random(run)]


def unknown_runs(texts: Iterable[str], known: Callable[[str], bool]) -> list[str]:
    """The random runs in `texts` that `known` does not know, each once."""
    found: list[str] = []
    for text in texts:
        for run in random_runs(text):
            if run not in found and not known(run):
                found.append(run)
    return found


def in_text(*sources: str) -> Callable[[str], bool]:
    """Knows a run that is part of any of `sources`."""
    return lambda run: any(run in source for source in sources)


def _git(folder: Path, *args: str) -> subprocess.CompletedProcess[str] | None:
    """Run git in `folder`, or None when git cannot start."""
    # Only `folder` itself: git must not find a repository above it, or take one from the
    # environment.
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env["GIT_CEILING_DIRECTORIES"] = str(Path(folder).resolve().parent)
    try:
        return subprocess.run(  # noqa: S603
            ["git", *args],  # noqa: S607
            cwd=folder,
            env=env,
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
    except OSError:
        return None


def has_commit(folder: Path, rev: str) -> bool:
    """Whether the repository `folder` holds the commit `rev`. Any git error counts as no."""
    if not rev or rev.startswith("-"):
        return False
    found = _git(folder, "rev-parse", "-q", "--verify", f"{rev}^{{commit}}")
    return found is not None and found.returncode == 0


def in_git(folder: Path, rev: str) -> Callable[[str], bool]:
    """Knows a run that a file's text or a file's name at `rev` in the repository `folder`
    holds. Any git error counts as not known. Git reads its objects, never the working
    files, so no link is followed."""
    names: str | None = None

    def known(run: str) -> bool:
        nonlocal names
        if not rev or rev.startswith("-"):
            return False
        found = _git(folder, "grep", "-q", "-F", "-e", run, rev, "--")
        if found is not None and found.returncode == 0:
            return True
        if names is None:
            listed = _git(folder, "ls-tree", "-r", "-z", "--name-only", rev)
            names = listed.stdout if listed is not None and listed.returncode == 0 else ""
        return run in names

    return known
