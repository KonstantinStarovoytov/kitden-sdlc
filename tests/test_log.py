import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
KEPT = "  Kept by: "
NOT_A_CONTINUATION = re.compile(r"\s*(?:[-*+]|\d+[.)]) ")


def log_problems(text: str, step_names: set[str]) -> list[str]:
    """What is wrong with the shape of LOG.md. After the intro the file is dated headings
    and entries: a `- ` line followed by indented lines, the last of which start with
    `Kept by: ` and say what keeps the failure away."""
    lines = text.splitlines()
    start = next((i for i, line in enumerate(lines) if line.startswith("## ")), len(lines))
    problems: list[str] = []
    entries: list[list[str]] = []
    inside = False
    for number, line in enumerate(lines[start:], start + 1):
        if not line.strip() or line.startswith("## "):
            inside = False
        elif line.startswith("- "):
            entries.append([line])
            inside = True
        elif line.startswith("  ") and inside and not NOT_A_CONTINUATION.match(line):
            entries[-1].append(line)
        else:
            problems.append(f"line {number} is not an entry, a heading or its continuation")
    for entry in entries:
        kept = [i for i, line in enumerate(entry) if line.startswith(KEPT)]
        if len(kept) != 1 or not entry[kept[0]][len(KEPT) :].strip(" .") or kept[0] == 0:
            problems.append(f"no Kept by line: {entry[0][:50]}")
            continue
        said = " ".join(" ".join(entry[kept[0] :]).split())
        for name in re.findall(r'"([^"]+)"', said):
            if name not in step_names:
                problems.append(f"no workflow step is named {name!r}")
    return problems


def workflow_step_names() -> set[str]:
    names: set[str] = set()
    for file in (ROOT / ".github/workflows").glob("*.yml"):
        for job in yaml.safe_load(file.read_text())["jobs"].values():
            names |= {s["name"] for s in job.get("steps") or [] if "name" in s}
    return names


GOOD = """# What went wrong

Intro.

## 2026-11-09

- **One.** Text.
  Kept by: `tests/test_log.py::test_a`.
- Two.
  more text
  Kept by: nothing to keep, a one-time rename.

## 2026-11-10

- Three.
  Kept by: the step "Build it" of ci.yml.
"""


def test_every_log_entry_says_what_keeps_it_away():
    problems = log_problems((ROOT / "LOG.md").read_text(), workflow_step_names())
    assert problems == []


def test_the_shape_check_accepts_a_good_log_and_refuses_every_other_way_in():
    names = {"Build it"}
    assert log_problems(GOOD, names) == []
    bad = {
        "an entry with no line": GOOD + "- Four.\n",
        "a star item": GOOD + "\n* Four.\n  Kept by: x.\n",
        "a numbered item": GOOD + "\n1. Four.\n  Kept by: x.\n",
        "an indented item": GOOD + "  - Four.\n  Kept by: x.\n",
        "an indented item in an entry": GOOD.replace("  more text", "  - more text"),
        "a paragraph under a heading": GOOD + "\n## 2026-11-11\n\nA paragraph.\n",
        "a paragraph after an entry": GOOD + "\nA paragraph.\n  Kept by: x.\n",
        "a line in the middle": GOOD.replace("  Kept by: `tests", "  See also Kept by: `tests"),
        "an empty line": GOOD.replace("Kept by: nothing to keep, a one-time rename.", "Kept by: ."),
        "an empty text": GOOD.replace("Kept by: nothing to keep, a one-time rename.", "Kept by: "),
        "the line on the first line": GOOD.replace(
            "- Two.\n  more text\n  Kept by: nothing to keep, a one-time rename.\n",
            "- Kept by: x\n",
        ),
        "a step that does not exist": GOOD.replace('"Build it"', '"Build that"'),
        "two lines": GOOD.replace("  more text", "  Kept by: x\n  more text"),
        "a continuation after a blank": GOOD.replace("  more text", "\n  more text"),
    }
    for what, text in bad.items():
        assert log_problems(text, names) != [], what


def test_every_test_a_log_entry_names_exists():
    named = re.findall(r"`(tests/[\w/]+\.py)::(\w+)`", (ROOT / "LOG.md").read_text())
    assert named
    for file, name in named:
        assert f"def {name}(" in (ROOT / file).read_text(), (file, name)
