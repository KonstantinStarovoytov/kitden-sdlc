import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KEPT = re.compile(r"Kept by: (.+?)\.?$", re.MULTILINE)


def test_every_log_entry_says_what_keeps_it_away():
    text = (ROOT / "LOG.md").read_text()
    entries = re.split(r"^- ", text, flags=re.MULTILINE)[1:]
    assert entries and all(KEPT.search(e) for e in entries)


def test_every_test_a_log_entry_names_exists():
    for file, name in re.findall(r"`(tests/[\w/]+\.py)::(\w+)`", (ROOT / "LOG.md").read_text()):
        assert f"def {name}(" in (ROOT / file).read_text(), (file, name)
