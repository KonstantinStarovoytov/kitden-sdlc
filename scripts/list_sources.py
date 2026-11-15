"""Check the rows a Kitden pull request adds or changes in its list against their doc pages.

A workflow runs it on every Kitden pull request that changes docs/clients.md. It has no model
and no secret, and it never fails the pull request: it always exits 0.

For each row that is new or whose client, What or Source changed (compared by their text,
not their place; an edit of Kind, Files, Seen in or the systems column alone is not checked):

- `Source` is a doc address: read the page (as `.md` first, watch_pages.get_doc) and warn
  when an exact word of the row (watch_list.row_words) does not stand alone on it
  (watch_list.held).
- `Source` is `guess`: warn that no page is named.
- `help` or `install`: nothing.
- any other `Source`, or an address that fails the address check: warn, and do not read it.

A row with no exact word gets no warning; the summary counts it. A table under a `## `
heading that is not a client's is not read; the summary names its heading.

Each page is read once, and at most 20 pages a run, and no new page once the reads took 180
seconds in all: rows on further pages are listed as not checked.

The pull request is untrusted, so is every row's text. A warning holds a row id, digits and
fixed words only, so no text can pass for a workflow command. The job summary may name the
missing words, cleaned, cut to 60 characters and shown as code. No text from a page and no
address is printed.

    python scripts/list_sources.py --base base.md --head head.md

Warnings go to stdout as workflow commands; the summary goes to $GITHUB_STEP_SUMMARY, or to
stdout when that is not set.
"""

import argparse
import http.client
import os
import re
import sys
import time
from collections.abc import Callable
from typing import NamedTuple

from doc_address import allowed, load_hosts
from watch_list import held, row_places, unknown_tables
from watch_pages import get_doc, sections
from watch_sources import pick_rows

FILE = "docs/clients.md"
PAGES_MAX = 20
TIME_MAX = 180  # seconds for all page reads of a run
WORD_MAX = 60  # characters of a missing word shown in the summary
WORDS_SHOWN = 10  # missing words shown for one row
ROWS_SHOWN = 100  # rows listed in the summary; GitHub takes 1 MiB of summary a step
HEADINGS_SHOWN = 10  # skipped tables named in the summary
ROW_ID = re.compile(r"[A-Z]{2}-\d{2,}")
NO_SOURCE = ("help", "install")

HELD = "held"
MISSING = "missing"
GUESS = "guess"
UNREAD = "unread"
NOT_ADDRESS = "not an address"
CANNOT = "cannot check"
NOT_CHECKED = "not checked"
SLOW = "too slow"
NO_CHECK = "help or install"

TEXTS = {
    GUESS: "no page named; scripts/watch_sources.py can look for one",
    UNREAD: "the page could not be read",
    NOT_ADDRESS: "`Source` is not a doc address",
    CANNOT: "cannot check: the row has no exact word",
    NOT_CHECKED: f"not checked: more than {PAGES_MAX} pages in one pull request",
    SLOW: "not checked: the pages took too long",
}
WARNED = (MISSING, GUESS, UNREAD, NOT_ADDRESS)
COUNTS = (("Every word on the page", (HELD,)), ("Words missing", (MISSING,)),
          ("Page not read", (UNREAD,)), ("Not a doc address", (NOT_ADDRESS,)),
          ("No page named", (GUESS,)), ("Cannot check", (CANNOT,)),
          ("Not checked", (NOT_CHECKED, SLOW)), ("`help` or `install`", (NO_CHECK,)))
# A read that fails this way leaves the page unread; any other error is a bug and goes out.
READ_ERRORS = (OSError, ValueError, http.client.HTTPException)
NOTE = ("Each page is read as `.md` when it has one. An exact word is a word in backticks in "
        "the row's What; it counts only where it stands alone on the page. This check never "
        "fails the pull request.")


class Line(NamedTuple):
    row_id: str
    line: int  # the row's line in the head file, from 1
    verdict: str
    missing: list[str]  # the exact words not on the page, as the row writes them
    words: int = 0  # how many exact words the row has


def changed_rows(base: str, head: str) -> list[str]:
    """The ids, in the head list, of the rows whose client, What and Source are not those of
    a row in the base list.

    A row is compared by its text, not by its place: a row added above others leaves them
    unchanged. Only the cells the check reads count: an edit of Kind, Files, Seen in or the
    systems column alone, as a refactor of Kitden's code makes, is not checked again.
    """
    def key(client, cells):
        return client, cells[0], cells[5]

    old = {key(client, cells) for _, client, cells in row_places(base).values()}
    return [row_id for row_id, (_, client, cells) in row_places(head).items()
            if key(client, cells) not in old]


def _page_text(address: str, read: Callable) -> str | None:
    """The text of the page to search in, or None when it could not be read."""
    try:
        body, kind, _ = read(address)
    except READ_ERRORS:
        return None
    if "html" in kind:
        return "\n".join(section.text for section in sections(body, kind))
    return body


def check(head_text: str, ids: list[str], hosts, read: Callable,
          clock: Callable[[], float] = time.monotonic) -> list[Line]:
    """One line for each row named by `ids`, in the list's order.

    `read(address)` gives (body, content type, address read from), as get_doc does. Each
    address is read once, and at most PAGES_MAX addresses are read. No new address is read
    once the reads have taken TIME_MAX seconds in all, by `clock`; a read already started is
    not cut short.
    """
    places = row_places(head_text)
    pages: dict[str, str | None] = {}
    spent = 0.0
    lines = []
    for item in pick_rows(head_text, ids=ids):
        verdict, missing = HELD, []
        if item.source in NO_SOURCE:
            verdict = NO_CHECK
        elif item.source == "guess":
            verdict = GUESS
        elif not allowed(item.source, hosts):
            verdict = NOT_ADDRESS
        elif not item.words:
            verdict = CANNOT
        elif item.source not in pages and len(pages) >= PAGES_MAX:
            verdict = NOT_CHECKED
        elif item.source not in pages and spent >= TIME_MAX:
            verdict = SLOW
        else:
            if item.source not in pages:
                started = clock()
                pages[item.source] = _page_text(item.source, read)
                spent += clock() - started
            text = pages[item.source]
            if text is None:
                verdict = UNREAD
            else:
                missing = held(item.words, text)
                verdict = MISSING if missing else HELD
        lines.append(Line(item.id, places[item.id][0], verdict, missing, len(item.words)))
    return lines


def text(line: Line) -> str:
    """What a line says, after its row id. Fixed words and digits only."""
    if line.verdict == MISSING:
        count, total = len(line.missing), line.words
        word = "word" if total == 1 else "words"
        verb = "is" if count == 1 else "are"
        return f"{count:d} of {total:d} exact {word} {verb} not on the page"
    return TEXTS[line.verdict]


def shown_word(word: str) -> str:
    """A word from the list, safe in a code span: printable characters only, without a
    backtick, `|` or line break, at most WORD_MAX characters."""
    return "".join(c for c in word if c.isprintable() and c not in "`|")[:WORD_MAX]


def _item(line: Line) -> str:
    item = f"- {line.row_id}, line {line.line:d}: {text(line)}"
    if line.verdict == MISSING:
        words = [f"`{w}`" for w in map(shown_word, line.missing) if w]
        more = len(words) - WORDS_SHOWN
        item += ": " + ", ".join(words[:WORDS_SHOWN])
        if more > 0:
            item += f" and {more:d} more"
    return item


def _skipped(heading: str) -> str:
    name = shown_word(heading)
    where = f"`{name}`" if name else "an empty heading"
    return f"- the table under {where} was skipped: its heading is not a client's"


def render(lines: list[Line], skipped: list[str] = ()) -> tuple[list[str], str]:
    """The workflow warnings and the job summary's markdown. `skipped`: the headings of the
    tables that are not a client's (watch_list.unknown_tables)."""
    for line in lines:
        # The ids come from watch_list.row_ids; this keeps a bug from printing other text.
        if not ROW_ID.fullmatch(line.row_id):
            raise ValueError("a row id is not of the form CC-01")
    warnings = [f"::warning file={FILE},line={line.line:d}::{line.row_id}: {text(line)}"
                for line in lines if line.verdict in WARNED]
    out = ["### The list's changed rows against their doc pages", ""]
    if skipped:
        out += [_skipped(heading) for heading in skipped[:HEADINGS_SHOWN]]
        if len(skipped) > HEADINGS_SHOWN:
            out.append(f"- and {len(skipped) - HEADINGS_SHOWN:d} more skipped tables")
        out.append("")
    if not lines:
        none = ("No row was added or changed in the tables of the known clients." if skipped
                else "No row was added or changed.")
        return warnings, "\n".join(out + [none, ""])
    counts = " ".join(f"{name}: {sum(line.verdict in verdicts for line in lines):d}."
                      for name, verdicts in COUNTS)
    out += [f"Rows added or changed: {len(lines):d}. {counts}", ""]
    listed = [line for line in lines if line.verdict not in (HELD, NO_CHECK)]
    out += [_item(line) for line in listed[:ROWS_SHOWN]]
    if len(listed) > ROWS_SHOWN:
        out.append(f"- and {len(listed) - ROWS_SHOWN:d} more rows")
    if listed:
        out.append("")
    out += [NOTE, ""]
    return warnings, "\n".join(out)


def _summary(summary: str, env) -> None:
    path = env.get("GITHUB_STEP_SUMMARY")
    if path:
        with open(path, "a", encoding="utf-8") as f:
            f.write(summary)
    else:
        print(summary, end="")


def _read(path: str) -> str | None:
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except (OSError, UnicodeError):
        return None


def run(argv, env, read, clock) -> int:
    ap = argparse.ArgumentParser(
        description="Check the rows a pull request changes in Kitden's list against their pages.")
    ap.add_argument("--base", required=True, help="the list on the base branch")
    ap.add_argument("--head", required=True, help="the list in the pull request")
    try:
        a = ap.parse_args(argv)
    except SystemExit:
        return 0
    texts = {"base": _read(a.base), "head": _read(a.head)}
    for name, value in texts.items():
        if value is None:
            print(f"the {name} list could not be read", file=sys.stderr)
            title = "### The list's changed rows against their doc pages\n\n"
            _summary(f"{title}The {name} list could not be read: nothing was checked.\n", env)
            return 0
    head = texts["head"]
    hosts = load_hosts()
    if read is None:
        def read(address):
            return get_doc(address, hosts)
    lines = check(head, changed_rows(texts["base"], head), hosts, read, clock)
    warnings, summary = render(lines, unknown_tables(head))
    for warning in warnings:
        print(warning)
    sys.stdout.flush()
    _summary(summary, env)
    return 0


def main(argv=None, env=None, read=None, clock=time.monotonic) -> int:
    """Always 0. A bug prints one line naming its exception's class, and nothing else."""
    env = os.environ if env is None else env
    try:
        return run(argv, env, read, clock)
    except Exception as err:  # this check must never block a pull request
        print(f"list check failed: {type(err).__name__}", file=sys.stderr)
        return 0


if __name__ == "__main__":
    sys.exit(main())
