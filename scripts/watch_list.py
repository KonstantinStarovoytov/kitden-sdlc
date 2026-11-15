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


def _numbered_rows(text: str) -> Iterator[tuple[int, str, list[str]]]:
    """Each row as (its line number in the file, client, cells).

    Lines are numbered from 1 as git counts them: only "\n" ends one. A row is still read
    from text.splitlines(), so a form feed or U+2028 cuts a row as before.
    """
    client = None
    number = 1
    for line, piece in zip(text.splitlines(), text.splitlines(keepends=True), strict=True):
        if line.startswith("## "):
            client = CLIENTS.get(line[3:].strip())
        elif client and line.startswith("|"):
            cells = [c.strip() for c in line.strip().strip("|").split(" | ")]
            if len(cells) == 6 and cells[0] != "What" and not re.fullmatch(r"[-:]+", cells[0]):
                yield number, client, cells
        number += piece.count("\n")


def _table_rows(text: str) -> Iterator[tuple[str, list[str]]]:
    for _, client, cells in _numbered_rows(text):
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


def _rows_with_ids(text: str) -> Iterator[tuple[str, int, str, list[str]]]:
    count: dict[str, int] = {}
    for number, client, cells in _numbered_rows(text):
        count[client] = count.get(client, 0) + 1
        yield f"{PREFIX[client]}-{count[client]:02d}", number, client, cells


def row_ids(text: str) -> dict[str, tuple[str, str]]:
    """A short id for each row, by its place in its client's table: id -> (client, label)."""
    return {row_id: (client, cells[0]) for row_id, _, client, cells in _rows_with_ids(text)}


def row_places(text: str) -> dict[str, tuple[int, str, tuple[str, ...]]]:
    """For each row id, the row's line number in the file (from 1, as git counts), its client
    and its cells."""
    return {row_id: (number, client, tuple(cells))
            for row_id, number, client, cells in _rows_with_ids(text)}


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


PROSE_MARKS = "(),;:"


def _bare_word(word: str) -> str:
    """`word` without the prose marks around it: `(file:` is `file`, `path).` is `path`."""
    before = None
    while word != before:
        before = word
        word = word.strip(PROSE_MARKS).removesuffix(".")
    return word


def row_words(text: str) -> dict[tuple[str, str], list[str]]:
    """Every word in backticks of each row's What, in order and without repeats.

    Keyed like terms(). A placeholder (a word with `<` or `>` in it) is left out.
    Quotes (' and ") around a word are taken off, then the marks of the list's prose: `(`,
    `)`, `,`, `;` and `:` at either end, and `.` at the end (a leading `.` stays, as in
    `.claude`). Then a word with `*` in it becomes its longest part without one, and is left
    out if that part is shorter than 3 characters. A word with no letter or digit in it, such
    as `=` or `-`, is left out: it would be found on any page.
    """
    result = {}
    for client, cells in _table_rows(text):
        words: list[str] = []
        for part in TICKS.findall(cells[0]):
            for word in part.split():
                if "<" in word or ">" in word:
                    continue
                word = _bare_word(word.strip("'\""))
                if not word:
                    continue
                if "*" in word:
                    word = max(word.split("*"), key=len)
                    if len(word) < 3:
                        continue
                if not any(c.isalnum() for c in word):
                    continue
                if word not in words:
                    words.append(word)
        result[(client, cells[0].replace("`", ""))] = words
    return result


# A word is found only where it stands alone: on a side where the word ends in one of these
# characters, the text's character next to it is not one of them either (or is the start or
# the end of the text).
WORD_CHARS = "A-Za-z0-9_-"
_WORD_CHAR = re.compile(f"[{WORD_CHARS}]")


def held(words: list[str], body: str) -> list[str]:
    """Return the missing words: those not found standing alone in body, in the order given.

    Where a word begins with a letter, a digit, `_` or `-`, the character before it in body
    must not be one of these (or must be the start of body); where it ends with one, the
    character after it likewise. A side that is a mark, such as `.`, `/` or `@`, is not
    checked. So `-s` is not found in `--scope`, `ws` not in `allows`, `enable` not in
    `enabledPlugins`; but `.mdc` is found in `my-rule.mdc`, `/sse` in
    `http://localhost:3000/sse` and `rules/` in `.claude/rules/code-style.md`. Each word is
    compared as written, case and all.
    """
    return [w for w in words if not re.search(_alone(w), body)]


def _alone(word: str) -> str:
    left = f"(?<![{WORD_CHARS}])" if word and _WORD_CHAR.fullmatch(word[0]) else ""
    right = f"(?![{WORD_CHARS}])" if word and _WORD_CHAR.fullmatch(word[-1]) else ""
    return left + re.escape(word) + right
