"""Read Kitden's list of client facts (docs/clients.md in the Kitden repo)."""

import re
from collections.abc import Iterator
from dataclasses import dataclass

CLIENTS = {"Claude Code": "claude-code", "Codex": "codex", "Cursor": "cursor"}


@dataclass
class Row:
    client: str
    what: str
    kind: str
    files: list[str]
    seen_in: str
    systems: str
    source: str


def _table_rows(text: str) -> Iterator[tuple[str, list[str]]]:
    client = None
    for line in text.splitlines():
        if line.startswith("## "):
            client = CLIENTS.get(line[3:].strip())
        elif client and line.startswith("|"):
            cells = [c.strip() for c in line.strip().strip("|").split(" | ")]
            if len(cells) == 6 and cells[0] != "What" and not cells[0].startswith("---"):
                yield client, cells


def parse_list(text: str) -> list[Row]:
    return [
        Row(client, what.replace("`", ""), kind, re.findall(r"`([^`]+)`", files),
            seen_in, systems, source)
        for client, (what, kind, files, seen_in, systems, source) in _table_rows(text)
    ]


def doc_pages(rows: list[Row]) -> dict[str, str]:
    pages: dict[str, str] = {}
    for row in rows:
        if row.source.startswith("https://"):
            pages.setdefault(row.source, row.client)
    return pages


def terms(text: str) -> dict[tuple[str, str], list[str]]:
    result = {}
    for client, cells in _table_rows(text):
        words = [w for part in re.findall(r"`([^`]+)`", cells[0]) for w in part.split()]
        result[(client, cells[0].replace("`", ""))] = [
            w for w in words if len(w) >= 6 and not re.fullmatch(r"[a-z]+", w)
        ]
    return result
