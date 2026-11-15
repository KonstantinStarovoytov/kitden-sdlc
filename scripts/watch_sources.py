"""A table of doc pages for the rows of Kitden's list that have none. The owner runs it by hand.

For each row whose `Source` is `help`, `install` or `guess` (or every row, with --all) it asks
Agent Docs for the row's What, within the row's client, and says whether a passage states it:

- states it: one passage holds every exact word of the row (watch_list.row_words), each
  standing alone (watch_list.held). "(weak words only)" when every word is weak: 3
  characters or fewer, or plain lowercase letters (the rule of watch_list.terms).
- near: n of m: no passage holds them all; the one that holds the most holds n of the m,
  and n is at least 1.
- cannot check: no exact word: the row has no word in backticks; the top passage is shown.
- no page: the search answered with no passage, or with passages that hold none of the words.
- search failed: the search got no answer. Never counted as "no page".

The question is the row's What without its dates and versions in brackets. If the first three
searches of a run all fail, the run stops there (exit 5): the key, the limit or the server is
wrong, and the rest would fail too.

A row that has its own page and is stated by another page is flagged "other page". Under the
table come the list's doc pages that are not in Agent Docs (watch_moved).

The key is read from COHERE_API_KEY and goes only to agent_docs.Search. The table goes to
stdout; one progress line a row goes to stderr. No passage text is printed: only its address,
when it passes the address check, and its heading, cleaned.
"""

import argparse
import os
import re
import sys
import time
import urllib.parse
from dataclasses import dataclass, field
from pathlib import Path

from agent_docs import Search
from doc_address import allowed, load_hosts, location
from watch_fetch import MOVED_TEXT, read_manifest, read_or_none
from watch_list import CLIENTS, doc_pages, held, parse_list, row_ids, words_by_row
from watch_moved import moved
from watch_pages import load_sources

SOURCES = Path(__file__).resolve().parent.parent / "config" / "watch-sources.yml"
PAUSE = 7  # seconds between searches: it fits a trial key's limit; a paid key can take 2
HEADING_MAX = 80
HEADING_MARKS = " -_.,:()/"
# An address is shown only with these characters: none of them can break a table cell or a
# code span.
SHOWABLE = re.compile(r"https://[A-Za-z0-9._~:/%@!$&'()*+,;=-]+")

STATES = "states it"
NEAR = "near"
CANNOT = "cannot check: no exact word"
NO_PAGE = "no page"
FAILED = "search failed"
NONE_HELD = "the top passage holds none of its words"
CUT = 4000  # passage characters to search in; an Agent Docs chunk reaches 3000
SHORT = 3  # a word this long or shorter is weak
PLAIN = re.compile(r"[a-z]+")  # so is a word of plain lowercase letters, as terms() drops
LIMITS = ("Limits: rows whose words are long strings cannot reach "
          "\"states it\"; a word that starts or ends with a mark can match inside a longer "
          "name (`.mdc` in `my-rule.mdc`, `mcp.json` in `.mcp.json`); a word glued to a "
          "letter, digit, `_` or `-` reads as missing.")
STOP_AFTER = 3  # failed searches at the start of a run that stop it
# A group in brackets that starts with a date, such as "(2026-10-19, version 2.1.283)", or
# names a version, such as "(version 0.169.0)": the list's notes, not words of the docs.
DATED = re.compile(r"\(\d{4}-\d{2}-\d{2}[^()]*\)|\(version [^()]*\)")


@dataclass
class Item:
    """A row of the list to check."""

    id: str
    client: str
    label: str  # the row's What as the list writes it, with its backticks
    what: str  # the same without backticks: the question
    source: str
    words: list[str]

    @property
    def has_page(self) -> bool:
        return self.source.startswith("https://")


@dataclass
class Result:
    item: Item
    verdict: str
    page: str = ""  # the passage's page, ready to show, or ""
    heading: str = ""  # the passage's heading, cleaned
    found: int = 0
    missing: list[str] = field(default_factory=list)
    other_page: bool = False
    weak: bool = False  # "states it" on weak words only
    note: str = ""


def weak(word: str) -> bool:
    """Whether a word proves little when found: 3 characters or fewer, or plain lowercase."""
    return len(word) <= SHORT or bool(PLAIN.fullmatch(word))


def question(what: str) -> str:
    """The row's What as a question: without its dates and versions in brackets."""
    return " ".join(DATED.sub(" ", what).split())


def pick_rows(text: str, client: str | None = None, all_rows: bool = False,
              ids: list[str] | None = None) -> list[Item]:
    """The rows to check: those named by `ids`, whatever their source; else those of `client`
    (or every client) that have no page, or every row with `all_rows`.

    Raises ValueError for an id that is not in the list.
    """
    rows = parse_list(text)
    names = row_ids(text)
    words = words_by_row(text)
    if len(rows) != len(names):
        raise ValueError("the list's rows and their ids do not match")
    items = [Item(rid, row.client, label, row.what, row.source, words[rid])
             for (rid, (_, label)), row in zip(names.items(), rows, strict=True)]
    if ids is not None:
        unknown = [i for i in ids if i not in names]
        if unknown:
            raise ValueError(f"no row {', '.join(unknown)} in the list")
        return [item for item in items if item.id in ids]
    return [item for item in items
            if (client is None or item.client == client) and (all_rows or not item.has_page)]


def clean_heading(text: str) -> str:
    """Letters, digits, spaces and -_.,:()/ only, at most 80 characters."""
    kept = "".join(" " if c.isspace() else c for c in text
                   if c.isalnum() or c in HEADING_MARKS or c.isspace())
    return " ".join(kept.split())[:HEADING_MAX].strip()


def page_of(url, hosts) -> str:
    """The page of a passage's address, without its fragment and `.md`, when it may be
    shown; else ""."""
    if not isinstance(url, str) or not allowed(url, hosts):
        return ""
    page = urllib.parse.urldefrag(url).url.removesuffix(".md")
    if not SHOWABLE.fullmatch(page) or not allowed(page, hosts):
        return ""
    return page


def _same(page: str, source: str) -> bool:
    return page.rstrip("/") == source.removesuffix(".md").rstrip("/")


def judge(item: Item, passages, hosts) -> Result:
    """The verdict for a row from the passages of a search that answered."""
    usable = []
    for p in passages:
        if not isinstance(p, dict) or not all(
                isinstance(p.get(name), str) for name in ("url", "heading", "text")):
            continue
        page = page_of(p["url"], hosts)
        if page:
            usable.append((page, p["heading"], p["heading"] + "\n" + p["text"]))
    if not usable:
        return Result(item, NO_PAGE)
    if not item.words:
        page, heading, _ = usable[0]
        return Result(item, CANNOT, page, clean_heading(heading))
    missing = [held(item.words, body) for _, _, body in usable]
    stating = [i for i, m in enumerate(missing) if not m]
    if stating:
        own = [i for i in stating if item.has_page and _same(usable[i][0], item.source)]
        pick = own[0] if own else stating[0]
        page, heading, _ = usable[pick]
        return Result(item, STATES, page, clean_heading(heading), len(item.words),
                      other_page=item.has_page and not own,
                      weak=all(weak(w) for w in item.words))
    # The passage that holds the most words; on a tie, the higher one.
    pick = min(range(len(usable)), key=lambda i: len(missing[i]))
    if len(missing[pick]) == len(item.words):
        return Result(item, NO_PAGE, note=NONE_HELD)
    page, heading, _ = usable[pick]
    return Result(item, NEAR, page, clean_heading(heading),
                  len(item.words) - len(missing[pick]), missing[pick])


def check(items: list[Item], search, sleep, pause: float, hosts) -> tuple[list[Result], bool]:
    """One search a row, `pause` seconds apart. A search that raised `search.failed` is
    "search failed". Stops when the first three searches all failed: the results so far, and
    whether it stopped."""
    results = []
    for n, item in enumerate(items):
        if n:
            sleep(pause)
        before = search.failed
        passages = search.search(question(item.what), item.client, cut=CUT)
        failed = search.failed != before
        result = Result(item, FAILED) if failed else judge(item, passages, hosts)
        print(f"[{n + 1}/{len(items)}] {item.id}: {result.verdict}", file=sys.stderr)
        results.append(result)
        if len(results) == STOP_AFTER and all(r.verdict == FAILED for r in results):
            print(f"The first {STOP_AFTER} searches failed, so the searches fail: check the "
                  "key, the per-minute limit, or the server. Stopped.", file=sys.stderr)
            return results, True
    return results, False


def cell(text: str) -> str:
    """Text from the list, made safe for a table cell: `|` escaped, line breaks as spaces."""
    return text.replace("|", "\\|").replace("\r\n", " ").replace("\r", " ").replace("\n", " ")


def _verdict(result: Result) -> str:
    if result.verdict == STATES:
        return (STATES + (" (weak words only)" if result.weak else "")
                + (", other page" if result.other_page else ""))
    if result.verdict == NEAR:
        missing = ", ".join(f"`{cell(w)}`" for w in result.missing)
        return f"near: {result.found} of {len(result.item.words)}; missing {missing}"
    return result.verdict + (f": {result.note}" if result.note else "")


def _where(result: Result) -> str:
    if not result.page:
        return ""
    return f"`{result.page}`" + (f", `{result.heading}`" if result.heading else "")


def table(results: list[Result], left: int | None = None) -> str:
    """The first line, the table and what to do next. `left`: the rows not searched because
    the run stopped, or None when it did not stop."""
    count = {v: sum(r.verdict == v for r in results) for v in (STATES, NEAR, CANNOT, NO_PAGE,
                                                                 FAILED)}
    weak_only = sum(r.weak for r in results)
    first = (f"Rows checked: {len(results)}. States it: {count[STATES]} "
             f"(weak words only: {weak_only}). Near: {count[NEAR]}. "
             f"Cannot check: {count[CANNOT]}. No page: {count[NO_PAGE]}. "
             f"Search failed: {count[FAILED]}.")
    if any(r.item.has_page for r in results):
        first += f" Other page: {sum(r.other_page for r in results)}."
    if results and count[FAILED] == len(results):
        first = "Every search failed, so this table says nothing about the docs. " + first
    lines = [first, LIMITS, "",
             "| Row | Source | Page and section | Verdict |", "|---|---|---|---|"]
    for r in results:
        lines.append(f"| {r.item.id} {cell(r.item.label)} | {cell(r.item.source)} "
                     f"| {_where(r)} | {_verdict(r)} |")
    failed = [r.item.id for r in results if r.verdict == FAILED]
    if failed:
        lines += ["", f"The search failed for {', '.join(failed)}: run again with "
                      f"`--rows {','.join(failed)}`."]
    if left is not None:
        lines += ["", f"Stopped after {STOP_AFTER} failed searches: {left} rows were not "
                      "searched."]
    return "\n".join(lines) + "\n"


def moved_part(records, hosts) -> str:
    """The lines of watch_moved under the table, or one line when the manifest was not read."""
    if records is None:
        return "Agent Docs' manifest could not be read: pages that moved were not checked.\n"
    lines = []
    for record in records:
        shown = [record["address"]] + ([record["to"]] if record["to"] else [])
        if not all(SHOWABLE.fullmatch(a) and allowed(a, hosts) for a in shown):
            continue
        _, changed, fix = MOVED_TEXT[record["verdict"]]
        coded = {**record, "address": f"`{record['address']}`", "to": f"`{record['to']}`"}
        lines.append(f"- {changed.format(**coded)} {fix.format(**coded)}")
    if not lines:
        return "Every doc page of the list is in Agent Docs.\n"
    return "Doc pages of the list that are not in Agent Docs:\n\n" + "\n".join(lines) + "\n"


def moved_pages(pages: dict[str, str], hosts, sources=SOURCES, locate=None):
    """watch_moved.moved for `pages`, with the manifest read the way watch_fetch reads it.
    None when there is no manifest source or one cannot be read."""
    manifests = [read_or_none(src["id"], read_manifest, src)
                 for src in load_sources(sources) if src["kind"] == "manifest"]
    if not manifests or None in manifests:
        return None
    locate = locate or (lambda address: location(address, hosts))
    return moved(pages, set().union(*manifests), hosts, locate)


def _pause(text: str) -> float:
    try:
        seconds = float(text)
    except ValueError:
        raise argparse.ArgumentTypeError("the pause is a number of seconds") from None
    if not seconds >= 0:
        raise argparse.ArgumentTypeError("the pause cannot be below 0")
    return seconds


def _ids(text: str) -> list[str]:
    return [part.strip().upper() for part in text.split(",") if part.strip()]


def main(argv=None, env=None, make_search=Search, sleep=time.sleep, find_moved=None) -> int:
    ap = argparse.ArgumentParser(description="Find doc pages for the rows of Kitden's list.")
    ap.add_argument("--kitden", required=True, help="the Kitden checkout")
    which = ap.add_mutually_exclusive_group()
    which.add_argument("--client", choices=sorted(CLIENTS.values()))
    which.add_argument("--rows", type=_ids, help="only these rows, such as CC-04,CX-12")
    ap.add_argument("--all", action="store_true", help="also the rows that have a page")
    ap.add_argument("--pause", type=_pause, default=PAUSE,
                    help=f"seconds between searches (default {PAUSE})")
    a = ap.parse_args(argv)
    env = os.environ if env is None else env

    key = env.get("COHERE_API_KEY", "")
    if not key:
        print("set COHERE_API_KEY", file=sys.stderr)
        return 2
    path = Path(a.kitden) / "docs" / "clients.md"
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as err:
        print(f"cannot read {path}: {type(err).__name__}", file=sys.stderr)
        return 2
    try:
        items = pick_rows(text, a.client, a.all, a.rows)
    except ValueError as err:
        print(err, file=sys.stderr)
        return 2
    try:
        search = make_search(key)
    except ValueError:
        # Search's own message leaves the key out; this one does not name it either.
        print("COHERE_API_KEY cannot be used: it is empty or has a character a header "
              "cannot carry", file=sys.stderr)
        return 2

    hosts = load_hosts()
    if items:
        if not search.wake():
            print("Agent Docs did not wake up: nothing was searched; try again later",
                  file=sys.stderr)
            return 4
        if not search.has_product():
            print("Agent Docs' /search does not take `product`, or its API description could "
                  "not be read: deploy `product` first, or try again later. Nothing was "
                  "searched.", file=sys.stderr)
            return 3
    results, stopped = check(items, search, sleep, a.pause, hosts)
    left = len(items) - len(results) if stopped else None
    # The table first: the moved check can take 20 seconds a page, and Ctrl-C then must not
    # lose it.
    print(table(results, left), flush=True)
    pages = doc_pages(parse_list(text))
    records = find_moved(pages) if find_moved else moved_pages(pages, hosts)
    print(moved_part(records, hosts), end="", flush=True)
    return 5 if stopped else 0


if __name__ == "__main__":
    sys.exit(main())
