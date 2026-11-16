"""Read Agent Docs' feed of new doc pages and new sections, and keep what touches Kitden.

The feed (`reports/docs-changes/feed.json` in agent-docs, part 1 of
docs/superpowers/specs/2026-11-15-agent-docs-design.md) comes from another repository over
the network, so every byte of it is untrusted. Its outer shape must be exact, or the whole
feed is a failed read; an entry of another shape is skipped and counted. An address from it
is used only after `doc_address.allowed`. A heading from it is only compared with a page's
own headings, never printed: a message names counts and exception classes only.
"""

import json
import sys
import urllib.parse
from datetime import date, timedelta
from typing import NamedTuple

from doc_address import allowed, client_of, page_of
from watch_list import held
from watch_pages import Section, get

FEED_MAX = 1024 * 1024  # bytes; a larger feed is a failed read, refused before it is parsed
# A feed whose `checked` day is more than this many days before today is a failed read: the
# reindex that writes it has stopped.
STALE_DAYS = 3
# An entry waits at most this many days for its turn (Task 6.5).
KEEP_DAYS = 14
PRODUCTS = ("claude-code", "codex", "cursor")
# Words for what Kitden shows. A section that holds one, anywhere and in any case, is kept.
# The shadow week tunes them.
TOPIC_WORDS = ("mcp", "skill", "plugin", "hook", "marketplace", "agents.md", "claude.md",
               ".cursor/rules", "instruction file")
KINDS = ("added", "changed", "removed")
# How far `checked` may be after today: the feed is written on UTC days, and a run by hand
# on a computer west of UTC can still be on the day before.
AHEAD = timedelta(days=1)


class Entry(NamedTuple):
    """One page of one day of the feed. `sections` holds the new headings of a changed
    page, as the feed writes them; it is empty for an added or a removed page."""

    day: str
    kind: str
    url: str
    product: str
    sections: tuple[str, ...]


def read_feed(source: dict, today: date) -> list[Entry]:
    """The feed at `source["url"]`, read with the FEED_MAX limit. Raises on any failure, so
    `watch_fetch.read_or_none` makes it a failed read of the source."""
    body, _ = get(source["url"], limit=FEED_MAX)
    return load_feed(body, today)


def _day(value) -> date:
    """`value` as a date, when it is written YYYY-MM-DD; else ValueError."""
    if not isinstance(value, str):
        raise ValueError("a day must be text")
    day = date.fromisoformat(value)  # raises ValueError
    if day.isoformat() != value:
        raise ValueError("a day must be written YYYY-MM-DD")
    return day


def _entry(day: str, kind: str, value) -> Entry | None:
    """`value` as an Entry, or None when it has another shape."""
    if not isinstance(value, dict):
        return None
    url, product = value.get("url"), value.get("product")
    if not (isinstance(url, str) and isinstance(product, str)):
        return None
    if kind != "changed":
        return Entry(day, kind, url, product, ())
    headings = value.get("new_sections")
    if not isinstance(headings, list) or not all(isinstance(h, str) for h in headings):
        return None
    return Entry(day, kind, url, product, tuple(headings))


def _parse(body) -> dict:
    if not isinstance(body, str):
        raise ValueError("the feed must be text")
    try:
        data = json.loads(body)
    except RecursionError:
        raise ValueError("the feed is nested too deeply") from None
    if not isinstance(data, dict):
        raise ValueError("the feed must be an object")
    return data


def load_feed(body: str, today: date) -> list[Entry]:
    """Every entry of the feed in `body`, the oldest day first; in a day the added pages,
    then the changed, then the removed, each in the feed's order.

    Raises ValueError, and only ValueError, when the body is not JSON of the feed's shape:
    an object whose `checked` is a day (YYYY-MM-DD) at most STALE_DAYS days before `today`
    and at most one day after it, and whose `days` is a list of objects, each with a `day`
    no later than `checked` and found once, and lists `added`, `changed` and `removed`. An
    entry of another shape (not an object, or a `url` or `product` that is not text, or a
    changed page whose `new_sections` is not a list of text) is skipped and counted on
    stderr. Keys the feed does not define are ignored.
    """
    data = _parse(body)
    checked = _day(data.get("checked"))
    if (today - checked).days > STALE_DAYS:
        raise ValueError("the feed is stale")
    if checked > today + AHEAD:
        raise ValueError("the feed is checked on a day still to come")
    days = data.get("days")
    if not isinstance(days, list):
        raise ValueError("the feed's days must be a list")
    seen: dict[date, dict] = {}
    for value in days:
        if not isinstance(value, dict):
            raise ValueError("a day of the feed must be an object")
        day = _day(value.get("day"))
        if day > checked or day in seen:
            raise ValueError("a day of the feed is after checked or found twice")
        if not all(isinstance(value.get(kind), list) for kind in KINDS):
            raise ValueError("a day of the feed must have its three lists")
        seen[day] = value
    out, skipped = [], 0
    for day in sorted(seen):
        for kind in KINDS:
            for value in seen[day][kind]:
                found = _entry(day.isoformat(), kind, value)
                if found is None:
                    skipped += 1
                else:
                    out.append(found)
    if skipped:
        print(f"feed: {skipped} entries of another shape skipped", file=sys.stderr)
    return out


def _page_key(address: str) -> str:
    """`address` as pages are compared: no fragment, no last `/`, no `.md`, host in lower
    case. An address Python cannot split is compared as written."""
    try:
        parts = urllib.parse.urlsplit(urllib.parse.urldefrag(address).url)
    except ValueError:
        return address
    path = parts.path.removesuffix("/").removesuffix(".md").removesuffix("/")
    return urllib.parse.urlunsplit((parts.scheme, parts.netloc.lower(), path, "", ""))


def wanted(entries: list[Entry], hosts, listed: set[str], after_day: str) -> list[Entry]:
    """The entries whose page the watcher reads, in their order.

    Kept: an added page, or a changed page with at least one new section; of a product in
    PRODUCTS; of a day after `after_day` (YYYY-MM-DD, or "" for every day); whose address
    passes `doc_address.allowed` and can be shown (`page_of`); whose product is the client
    config/doc-hosts.yml gives its host and path (`doc_address.client_of`), so a feed cannot
    call a Cursor page another client's; that is not one of the list's pages in `listed`. Pages
    are compared without `.md`, a fragment or a last `/`, and with the host in lower case; a
    page found again on the same day is kept once, the first time. The entries dropped for
    their product are counted on stderr.
    """
    listed_keys = {_page_key(address) for address in listed}
    out, taken, mislabeled = [], set(), 0
    for e in entries:
        if not (e.kind == "added" or (e.kind == "changed" and e.sections)):
            continue
        if e.product not in PRODUCTS or e.day <= after_day:
            continue
        if not allowed(e.url, hosts):
            continue
        if e.product != client_of(e.url, hosts):
            mislabeled += 1
            continue
        page = page_of(e.url, hosts)
        key = _page_key(page)
        if not page or key in listed_keys or (key, e.day) in taken:
            continue
        taken.add((key, e.day))
        out.append(e)
    if mislabeled:
        print(f"feed: {mislabeled} entries whose product is not their host's dropped",
              file=sys.stderr)
    return out


def kept_sections(sections: list[Section], list_words: list[str]) -> list[tuple[Section, str]]:
    """The sections worth a look, each with the word that kept it, in page order.

    A list word (from `watch_list.terms` for the page's client) counts where it stands alone
    in the section's text, as written (`watch_list.held`). Else a topic word counts anywhere
    in the text, in any case. A blank list word counts nowhere.
    """
    words = [w for w in list_words if w.strip()]
    out = []
    for section in sections:
        word = next((w for w in words if not held([w], section.text)), None)
        if word is None:
            text = section.text.lower()
            word = next((w for w in TOPIC_WORDS if w in text), None)
        if word is not None:
            out.append((section, word))
    return out
