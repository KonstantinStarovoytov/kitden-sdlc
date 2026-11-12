"""Read Kitden's list of client facts (docs/clients.md in the Kitden repo)."""

import re
from collections.abc import Iterator
from dataclasses import dataclass

CLIENTS = {"Claude Code": "claude-code", "Codex": "codex", "Cursor": "cursor"}
TICKS = re.compile(r"`([^`]+)`")
PREFIX = {"claude-code": "CC", "codex": "CX", "cursor": "CU"}


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
            if len(cells) == 6 and cells[0] != "What" and not re.fullmatch(r"[-:]+", cells[0]):
                yield client, cells


def parse_list(text: str) -> list[Row]:
    return [
        Row(client, what.replace("`", ""), kind, TICKS.findall(files),
            seen_in, systems, source)
        for client, (what, kind, files, seen_in, systems, source) in _table_rows(text)
    ]


def row_labels(text: str) -> dict[tuple[str, str], str]:
    """For each (client, what) the row's label as the list writes it, with its backticks."""
    return {(client, cells[0].replace("`", "")): cells[0] for client, cells in _table_rows(text)}


def row_ids(text: str) -> dict[str, tuple[str, str]]:
    """A short id for each row, by its place in its client's table: id -> (client, label)."""
    ids: dict[str, tuple[str, str]] = {}
    count: dict[str, int] = {}
    for client, cells in _table_rows(text):
        count[client] = count.get(client, 0) + 1
        ids[f"{PREFIX[client]}-{count[client]:02d}"] = (client, cells[0])
    return ids


def short_list(text: str) -> str:
    """The list as the model reads it: one line a row, with its id, and no file names."""
    kinds = {(client, cells[0]): (cells[1], cells[3]) for client, cells in _table_rows(text)}
    names = {slug: name for name, slug in CLIENTS.items()}
    out, last = [], None
    for row_id, (client, label) in row_ids(text).items():
        if client != last:
            out.append(f"\n## {names[client]} (client `{client}`)")
            last = client
        kind, seen_in = kinds[(client, label)]
        out.append(f"{row_id} | {label} | {kind} | seen in: {seen_in}")
    return "\n".join(out).strip() + "\n"


def doc_pages(rows: list[Row]) -> dict[str, str]:
    pages: dict[str, str] = {}
    for row in rows:
        if row.source.startswith("https://"):
            pages.setdefault(row.source, row.client)
    return pages


def terms(text: str) -> dict[tuple[str, str], list[str]]:
    result = {}
    for client, cells in _table_rows(text):
        words = [w for part in TICKS.findall(cells[0]) for w in part.split()]
        result[(client, cells[0].replace("`", ""))] = [
            w for w in words if len(w) >= 6 and not re.fullmatch(r"[a-z]+", w)
        ]
    return result
