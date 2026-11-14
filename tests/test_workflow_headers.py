"""Every workflow says at its top what it does and why, and has a name that tells."""
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
FILES = sorted([*(ROOT / ".github/workflows").glob("*.yml"), *(ROOT / "examples").glob("*.yml")])


def test_there_are_workflows_to_check():
    assert len(FILES) >= 13


@pytest.mark.parametrize("path", FILES, ids=lambda p: f"{p.parent.name}/{p.name}")
def test_a_workflow_starts_with_what_and_why(path):
    lines = path.read_text().splitlines()
    head = []
    for line in lines:
        if not line.startswith("#"):
            break
        head.append(line)
    assert head and head[0].startswith("# What: "), path
    assert sum(line.startswith("# Why: ") for line in head) == 1, path
    assert lines[len(head)].startswith("name: "), path


@pytest.mark.parametrize("path", FILES, ids=lambda p: f"{p.parent.name}/{p.name}")
def test_a_workflow_name_starts_with_a_capital_and_is_not_one_bare_word(path):
    name = yaml.safe_load(path.read_text())["name"]
    assert name[0].isupper(), name
    assert " " in name or name == "Publish", name
