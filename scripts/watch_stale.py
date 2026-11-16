"""Facts with a page and a checked day, and the pages that changed after their facts.

Two files hold such facts. Kitden's list of client facts (docs/clients.md in the Kitden
repo): a row whose `Source` is an address, with a date in brackets. And docs/platform-rules.md
here: a rule's `Source:` or `Sources:` line names its pages, and `Checked:` the day. Given the
last day each page changed, `stale` says which pages changed after their facts were checked.

Nothing here reads the network or a file: fetch (Task 7.2) passes the text in.
"""

import hashlib
import json
import re
from datetime import date
from typing import NamedTuple

from doc_address import SHOWABLE, clean_heading
from watch_list import row_places
from watch_pages import Section
from watch_route import TEXT_MAX, TITLE_MAX, _quiet

# The rules file writes an address as <https://...> and inside a markdown link
# [text](https://...): this takes neither bracket. `_address` then cuts the fragment and a
# last "." or ",".
ADDRESS = re.compile(r"https://[^\s<>()\[\]]+")
DAY = r"[0-9]{4}-[0-9]{2}-[0-9]{2}"
# In the list, a date in brackets is a check against the page when the bracket holds the
# date alone, "(2026-10-22)", or starts with "checked", "(checked 2026-10-22 ...)". A date
# with more after it in its bracket, "(2026-11-15, version 2.1.325, macOS)", is something
# seen on an install or in a client's own code: it says nothing about the page.
LIST_DATE = re.compile(rf"\((?:({DAY})\)|(?i:checked)\s+({DAY})\b)")
# A mark: after its indent and an optional "- ", a line starts with "Source:" or "Sources:".
MARK = re.compile(r"\s*(?:- )?Sources?:")
CHECKED = re.compile(rf"\bChecked: ?({DAY})\b")
# A date inside a sentence, such as "(checked 2026-11-12)". It is not read, only counted.
IN_SENTENCE = re.compile(rf"\bchecked\s+{DAY}\b", re.IGNORECASE)
# A mark's block is at most this many lines, the mark's own line included.
BLOCK_LINES = 6
RULES_CLIENT = "Store rules"
# An item names at most this many facts, then says how many more.
LABELS_SHOWN = 10
# A title stays under 80 characters, whatever the address.
TITLE_LONGEST = 79
TITLE_END = " changed after its facts were checked"
FIX = ("Read the page and check each fact named here against it. Change the fact if it no "
       "longer holds, and its date in either case: a row id is a row of docs/clients.md in "
       "Kitden, a heading and line are a rule of docs/platform-rules.md in kitden-sdlc.")
WHY = ("Each fact names the page it was checked against and the day. The page changed after "
       "that day, so the fact may no longer be true.")


class Fact(NamedTuple):
    """A fact's page (no fragment), the day it was checked (YYYY-MM-DD), its label (a row id,
    or a rule's heading and line) and its client (a client's slug, or "Store rules")."""

    address: str
    checked: str
    label: str
    client: str


def _day(text) -> str | None:
    """`text` when it is a real day written YYYY-MM-DD, else None. Never raises."""
    if not isinstance(text, str) or not re.fullmatch(DAY, text):
        return None
    try:
        date.fromisoformat(text)
    except ValueError:
        return None
    return text


def _address(found: str) -> str | None:
    """An ADDRESS match cut at "#", without a last "." or ","; None when nothing is left
    after "https://"."""
    address = found.split("#", 1)[0].rstrip(".,")
    return address if len(address) > len("https://") else None


def page_address(source: str) -> str | None:
    """The page a list `Source` starts with, as a Fact keeps it (no fragment), or None when
    it starts with no address. Fetch uses it to match a doc page of the list to its facts."""
    found = ADDRESS.match(source)
    return _address(found.group()) if found else None


def list_facts(text: str) -> tuple[list[Fact], int]:
    """The facts of Kitden's list, and the number of rows with an address and no date.

    A row is a fact when its `Source` starts with an address and its `What` or `Seen in`
    cell holds a check against the page: a date alone in its bracket, "(YYYY-MM-DD)", or a
    bracket that starts with "checked YYYY-MM-DD". The latest such date is its `checked`. A
    date with more after it in its bracket ("(YYYY-MM-DD, version 1.2, macOS)") was seen on
    an install or in a client's own code, so it does not count: a row with only such dates
    is counted with the rows with no date.
    """
    facts: list[Fact] = []
    undated = 0
    for row_id, (_, client, cells) in row_places(text).items():
        what, seen_in, source = cells[0], cells[3], cells[5]
        address = page_address(source)
        if not address:
            continue
        days = [d for cell in (what, seen_in) for pair in LIST_DATE.findall(cell)
                for d in pair if _day(d)]
        if days:
            facts.append(Fact(address, max(days), row_id, client))
        else:
            undated += 1
    return facts, undated


def _block(lines: list[str], start: int) -> tuple[list[str], str | None]:
    """The lines of the mark at `start`, and its day (None when it has none).

    The block runs to the first line that holds "Checked: YYYY-MM-DD", for at most
    BLOCK_LINES lines. It ends before an empty line, a heading or the next mark: a date
    belongs to its own rule only.
    """
    block: list[str] = []
    for line in lines[start:start + BLOCK_LINES]:
        if block and (not line.strip() or line.startswith("#") or MARK.match(line)):
            break
        block.append(line)
        found = CHECKED.search(line)
        if found:
            return block, _day(found.group(1))
    return block, None


def rule_facts(text: str) -> tuple[list[Fact], int]:
    """The facts of docs/platform-rules.md, and the number of what was skipped: the marks
    that give no fact (no date, or no address) plus the dates written inside a sentence.

    Each address in a block with a date is a fact, once a block. Its label is the "## "
    heading above, through clean_heading, and the mark's line number, from 1 as git counts.
    """
    lines = text.split("\n")
    facts: list[Fact] = []
    skipped = 0
    heading = ""
    for number, line in enumerate(lines, start=1):
        if line.startswith("## "):
            heading = clean_heading(line[3:])
            continue
        if not MARK.match(line):
            continue
        block, day = _block(lines, number - 1)
        addresses = [a for one in block for found in ADDRESS.findall(one)
                     if (a := _address(found))]
        if not day or not addresses:
            skipped += 1
            continue
        label = f"{heading}, line {number}" if heading else f"line {number}"
        facts.extend(Fact(a, day, label, RULES_CLIENT) for a in dict.fromkeys(addresses))
    return facts, skipped + len(IN_SENTENCE.findall(text))


def page_hash(sections: list[Section]) -> str:
    """One sha256 over the sections' keys and hashes, in order. Written as JSON, so no key
    and hash run into the next."""
    pairs = [[s.key, s.hash] for s in sections]
    return hashlib.sha256(json.dumps(pairs).encode()).hexdigest()


def _title(address: str, end: str = TITLE_END) -> str:
    """"<address><end>", under 80 characters: by default "<address> changed after its facts
    were checked".

    When the whole address does not fit, or may not be shown, the longest tail of its path
    parts that fits stands for it ("plugins/install"), each part through clean_heading; when
    not even the last part fits, the last part is cut. An address with no path uses its host.
    """
    if SHOWABLE.fullmatch(address):
        title = _quiet(address + end, TITLE_MAX)
        if len(title) <= TITLE_LONGEST:
            return title
    room = TITLE_LONGEST - len(end)
    host, _, path = address.removeprefix("https://").partition("/")
    parts = ([c for p in path.split("/") if (c := clean_heading(p))]
             or [c for c in (clean_heading(host),) if c] or ["A page"])
    for start in range(len(parts)):
        tail = _quiet("/".join(parts[start:]), TITLE_MAX)
        if len(tail) <= room:
            return tail + end
    return _quiet(parts[-1], room) + end


def _item(address: str, day: str, old: list[Fact]) -> dict:
    labels = list(dict.fromkeys(f.label for f in old))
    named = "; ".join(labels[:LABELS_SHOWN])
    if len(labels) > LABELS_SHOWN:
        named += f" and {len(labels) - LABELS_SHOWN} more"
    which = ("after this fact was checked" if len(labels) == 1
             else f"after these {len(labels)} facts were checked")
    return {
        "effect": "outdated", "severity": "minor", "sure": True,
        "title": _title(address), "client": old[0].client,
        "changed": _quiet(f"The page changed on {day}, {which}: {named}.", TEXT_MAX),
        "fix": _quiet(FIX, TEXT_MAX), "why": _quiet(WHY, TEXT_MAX),
        "user_gets": "not checked", "systems": "", "row": "", "files": [],
        "version": "", "url": address if SHOWABLE.fullmatch(address) else "",
    }


def stale(facts: list[Fact], changed: dict[str, str]) -> list[dict]:
    """One item a page whose day in `changed` (address -> YYYY-MM-DD) is after the
    `checked` of at least one of its facts, in the order the facts first name the pages.

    The item names only the facts checked before that day; its client is the first such
    fact's. A page whose day is not a real YYYY-MM-DD ("" too) is skipped, for the caller
    to count: this never raises on it.
    """
    pages: dict[str, list[Fact]] = {}
    for fact in facts:
        pages.setdefault(fact.address, []).append(fact)
    items = []
    for address, group in pages.items():
        day = _day(changed.get(address))
        if day is None:
            continue
        old = [f for f in group if _day(f.checked) and f.checked < day]
        if old:
            items.append(_item(address, day, old))
    return items
