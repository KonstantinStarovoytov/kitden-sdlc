"""Find a key whose first characters were cut off: a long random-looking string that is
nowhere in the text the model was given.

A known token (a prefix plus a long tail) is caught by SECRET_LIKE in post_findings.py. A
tail alone has no prefix to match, so a long run of key characters in model text counts as
a leak unless the model could have copied it from its input. `clean` uses the same two
checks to leave out items of outside text before a script passes them on. Standard library
only: the scripts that use this run without the project's dependencies.
"""

import os
import re
import subprocess
import unicodedata
from collections.abc import Callable, Iterable
from pathlib import Path

RUN_MIN = 32
HEADING_MARKS = " -_.,:()/"
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


def clean(
    items: list[dict], fields: tuple[str, ...], secret_like: re.Pattern[str]
) -> tuple[list[dict], int]:
    """The items of outside text (a doc passage, a section) that are safe to pass on, and
    how many were left out.

    An item is left out when one of its `fields` holds a match of `secret_like` or a random
    run. Outside text was never ours, so no run in it counts as known. An item that is not a
    dict, or whose named field is missing or not a string, is left out too, never an error.
    Other fields are not looked at. The caller passes post_findings.SECRET_LIKE: that module
    imports this one.

    Each field is checked in three forms: as written, without its format characters
    (Unicode category Cf, such as zero-width spaces and joiners and the BOM), and as
    `kept_marks` leaves it. A token split by a character that cleaning drops is still
    caught, though doc_address.clean_heading would join it again.

    Raises ValueError when `fields` is empty: that would let every item through unchecked.
    """
    if not fields:
        raise ValueError("clean needs at least one field to check")
    kept = []
    for item in items:
        texts = [item.get(name) for name in fields] if isinstance(item, dict) else [None]
        if all(isinstance(text, str) and all(
                _safe(form, secret_like) for form in (text, _without_format(text),
                                                      kept_marks(text)))
               for text in texts):
            kept.append(item)
    return kept, len(items) - len(kept)


def kept_marks(text: str) -> str:
    """`text` with only letters, digits, whitespace and HEADING_MARKS: each whitespace
    character becomes a space, nothing is cut. doc_address.clean_heading starts from this,
    so `clean` checks the very characters a shown heading keeps."""
    return "".join(" " if c.isspace() else c for c in text
                   if c.isalnum() or c in HEADING_MARKS or c.isspace())


def _safe(text: str, secret_like: re.Pattern[str]) -> bool:
    return not secret_like.search(text) and not random_runs(text)


def _without_format(text: str) -> str:
    return "".join(c for c in text if unicodedata.category(c) != "Cf")


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
