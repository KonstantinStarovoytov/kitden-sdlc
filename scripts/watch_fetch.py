"""Fetch what is new in the watched sources and write the input for the judge."""

import argparse
import copy
import hashlib
import json
import os
import re
import subprocess  # noqa: S404
import sys
import time
import urllib.error
import urllib.parse
from datetime import date
from pathlib import Path
from typing import NamedTuple

import doc_address
from doc_address import (
    NO_TEXT_CLIENTS,
    SHOWABLE,
    Page,
    allowed,
    client_of,
    load_hosts,
    location,
    make_opener,
    page_of,
)
from watch_feed import (
    COUNTS,
    KEEP_DAYS,
    MODES,
    Entry,
    kept_sections,
    page_key,
    read_feed,
    wanted,
)
from watch_list import doc_pages, parse_list, terms
from watch_moved import manifest_addresses, moved
from watch_pages import GONE, Section, get, get_doc, load_sources, pick, releases, sections
from watch_route import TEXT_MAX, TITLE_MAX, _quiet, week_of
from watch_stale import (
    RULES_CLIENT,
    Fact,
    _title,
    page_address,
    page_hash,
    scan_list,
    scan_rules,
    stale,
)

PIECES_MAX = 20
PIECE_CHARS = 12000
MANIFEST_MAX = 5 * 1024 * 1024  # bytes; a larger manifest is a failed read
FAIL_DAYS = 3
# 2: doc pages are read as markdown. A memory with a lower number holds hashes of HTML
# sections, so its doc pages are filled again, quietly, as if new.
# A bump also changes the whole-page hash of every list page in `fact_pages` (plan_stale),
# so each would look changed that day and come back in the weekly summary as stale. In the
# same change, empty `fact_pages` when `doc_format` is lower, so its pages start again as new.
DOC_FORMAT = 2
# Seconds for every doc page read of a run. The job has 15 minutes, and the releases and the
# list's files come before the pages. A page not started in time waits for tomorrow: it is
# not a failed read and keeps its hashes.
PAGES_SECONDS = 420
# Agent Docs' feed of new doc pages and sections (scripts/watch_feed.py). Its pieces come after
# the releases and the list's own pages, in the room they leave: at most FEED_PIECES_MAX a run,
# from at most FEED_PAGES_MAX pages read, under the same PAGES_SECONDS. An entry not reached
# waits in the memory for the next run, at most KEEP_DAYS days after its day.
FEED_PIECES_MAX = 5
FEED_PAGES_MAX = 10
# The entries kept waiting. More could not all be read before KEEP_DAYS at FEED_PAGES_MAX pages
# a run, so the rest are dropped and counted.
WAIT_MAX = FEED_PAGES_MAX * KEEP_DAYS
# A waiting entry keeps at most this many headings, each cut to this many characters: the
# feed's writer has the same caps, so a real heading is never cut. The memory stays small even
# when a feed breaks them.
HEADINGS_MAX = 50
HEADING_CHARS = 200
# The page keys kept as taken on the last day taken. Agent Docs merges a second reindex of a
# day into that day, so a run between the two takes that day again for the pages it has not
# taken. Past this number a page of that day may be taken twice: read again, not lost.
TAKEN_MAX = WAIT_MAX
FEED_SOURCE = "agent-docs-feed"
# In shadow (WATCH_FEED), the feed's rows go into this file beside input.json, one a piece.
SHADOW_FILE = "feed-shadow.json"
# An unknown WATCH_FEED is named on stderr only when it looks like this: a short word cannot
# be a workflow command or a secret.
SHOWN_MODE = re.compile(r"[a-z]{1,10}")
# The rules of the stores, in this checkout: on main, a reviewed file. Each page a rule names
# (scripts/watch_stale.py) is read by fetch itself, as a source of kind `rule-page`: hashed
# whole, never given to the judge, and read only at its own address (read_rule_page).
RULES_FILE = Path(__file__).resolve().parent.parent / "docs" / "platform-rules.md"
# Reads of rule pages a run, the second read of a page included, after the list's pages and
# under the same PAGES_SECONDS. A page not reached waits for the next run, which starts at it
# (`rule_start`); it keeps its entry in `fact_pages` and is not a failed read.
RULE_PAGES_MAX = 40
# A rule page on GitHub written as a blob address is read from its raw file, which holds the
# rule's text without GitHub's page around it. The memory and the summary keep the blob address.
BLOB = re.compile(r"https://github\.com/([^/]+)/([^/]+)/blob/(.+)")
RAW_HOST = "raw.githubusercontent.com"
UNSTABLE_END = " cannot be watched: it reads differently twice"


class Budget:
    """A time budget that starts when it is made. A read already started is not cut short:
    the caller asks `left()` before each read."""

    def __init__(self, seconds: float, clock=time.monotonic):
        self.seconds = seconds
        self.clock = clock
        self.start = clock()

    def left(self) -> bool:
        """Whether some of the seconds are left."""
        return self.clock() - self.start < self.seconds


def _unreadable(meta: dict, source: str) -> dict:
    return {
        "effect": "unknown", "severity": "medium", "sure": True,
        "title": f"Cannot read {source} for {FAIL_DAYS} days",
        "client": meta.get("client", ""), "changed": f"{source} could not be read",
        "why": "The watcher cannot see new changes from this source.",
        "user_gets": "Nothing yet.", "systems": "", "row": "", "files": [],
        "version": "", "url": meta["url"],
    }


def _out_of_time(addresses: list[str], pages: dict[str, str], noun: str = "doc page") -> dict:
    """One item for the pages (doc pages, or rule pages with `noun`) that reached FAIL_DAYS
    skipped runs in one run. The title stays short (the summary's table cuts at 80
    characters); the text lists the pages."""
    count = len(addresses)
    pages_were = f"1 {noun} was" if count == 1 else f"{count} {noun}s were"
    clients = {pages[a] for a in addresses}
    listed = ", ".join(f"`{a}`" for a in addresses)
    return {**_unreadable({"client": clients.pop() if len(clients) == 1 else "", "url": ""},
                          f"{noun}s"),
            "title": f"{pages_were} not read for {FAIL_DAYS} runs: out of time",
            "changed": f"Each of the last {FAIL_DAYS} runs ran out of time before {listed}."}


def _rule_unreadable(meta: dict, source: str) -> dict:
    """The "Cannot read" item of a rule page: its title is built as watch_stale builds titles
    (under 80 characters, the tail of the path when the address is long), and the address is
    only in `url`, when SHOWABLE matches it."""
    return {**_unreadable(meta, source),
            "title": _title(source, f" for {FAIL_DAYS} days", "Cannot read "),
            "changed": "This page of the store rules could not be read.",
            "url": source if SHOWABLE.fullmatch(source) else ""}


def _start(state, count: int, key: str = "page_start") -> int:
    start = state.get(key, 0) if state else 0
    # A bool is an int in Python; it is not a place in the list.
    if type(start) is not int or not count:
        return 0
    return start % count


def page_order(state, pages, key: str = "page_start") -> list[str]:
    """The pages in the order to read them: sorted, from the memory's `key` (`page_start`
    for the list's doc pages, `rule_start` for the rule pages), wrapping around. So on a slow
    day the pages a run did not reach come first the next day."""
    order = sorted(pages)
    start = _start(state, len(order), key)
    return order[start:] + order[:start]


# The memory's keys for each kind of page read in turns: where the next run starts, the runs
# in a row each page was left unread, and the word for the page in the summary's item.
DOC_TURNS = ("page_start", "skips", "doc page")
RULE_TURNS = ("rule_start", "rule_skips", "rule page")


def plan_skips(state, pages: dict[str, str], read: int, turns=DOC_TURNS) -> dict:
    """The memory after a run that started `read` pages of page_order(state, pages).

    The start (`page_start`, or `rule_start` with RULE_TURNS) moves to the first page left
    unread, or stays when every page was read. The skips (`skips`, or `rule_skips`) count,
    for each page left unread, the runs in a row that left it unread; a page whose read was
    started is dropped from it, and so is a page that left the list. The pages that reach
    their third run in a row today go to `kept` as one item, so a slow site makes one line of
    the summary, not one for each page.
    """
    start_key, skips_key, noun = turns
    new = copy.deepcopy(state)
    order = page_order(state, pages, key=start_key)
    new[start_key] = (_start(state, len(order), start_key) + read) % len(order) if order else 0
    old = state.get(skips_key) if isinstance(state.get(skips_key), dict) else {}
    new[skips_key] = {}
    for address in order[read:]:
        count = old.get(address, 0)
        new[skips_key][address] = (count if type(count) is int else 0) + 1
    # == and not >=: a page is in the item of the run it reaches its third skip, not again.
    third = [address for address, count in new[skips_key].items() if count == FAIL_DAYS]
    if third:
        new["kept"].append(_out_of_time(third, pages, noun))
    return new


def plan_run(state, fetched, meta):
    new = copy.deepcopy(state) if state else {}
    new.setdefault("sources", {})
    new.setdefault("fails", {})
    new.setdefault("kept", [])
    new.setdefault("urgent", {"week": "", "count": 0})
    new.setdefault("summary_week", "")
    new.setdefault("tries", {})
    known = state["sources"] if state else {}
    if state and state.get("doc_format", 0) < DOC_FORMAT:
        # Keep only the sources read this run that are not doc pages: a doc page that has
        # left the list loses its HTML hashes too.
        keep = {sid for sid in meta if meta[sid]["kind"] != "doc"}
        known = {sid: h for sid, h in known.items() if sid in keep}
        new["sources"] = copy.deepcopy(known)
    new["doc_format"] = DOC_FORMAT
    pieces = []
    for sid in sorted(meta, key=lambda s: meta[s]["kind"] != "release"):
        found = fetched.get(sid)
        if found is None:
            new["fails"][sid] = new["fails"].get(sid, 0) + 1
            unreadable = _rule_unreadable if meta[sid]["kind"] == "rule-page" else _unreadable
            item = unreadable(meta[sid], sid)
            if new["fails"][sid] == FAIL_DAYS and all(
                k["title"] != item["title"] for k in new["kept"]
            ):
                new["kept"].append(item)
            continue
        new["fails"][sid] = 0
        # The manifest is read for the weekly moved check only; the feed's pieces are made by
        # plan_feed; a rule page is hashed whole for plan_stale. None is hash-compared here.
        if meta[sid]["kind"] in ("manifest", "feed", "rule-page"):
            continue
        if sid not in known:
            new["sources"][sid] = {s.key: s.hash for s in found}
            continue
        for s in found:
            if known[sid].get(s.key) != s.hash:
                is_doc = meta[sid]["kind"] == "doc"
                pieces.append({
                    "id": f"{sid}#{s.key}", "client": meta[sid]["client"],
                    "kind": meta[sid]["kind"], "version": "" if is_doc else s.key,
                    "url": meta[sid]["url"], "text": s.text[:PIECE_CHARS],
                    "source": sid, "key": s.key, "hash": s.hash,
                })
    return pieces[:PIECES_MAX], new


# What the summary says of each verdict of watch_moved.moved: the title, what changed, the fix.
# The title is short and has only the old address, so the summary does not cut it mid-address.
MOVED_TEXT = {
    "moved": ("{address} moved",
              "{address} is not in Agent Docs, and it now redirects to {to}.",
              "Change the address in docs/clients.md to {to}."),
    "maybe": ("{address} may have moved",
              "{address} is not in Agent Docs, and it does not redirect. Agent Docs has {to}: "
              "a page on the same site, under the same path, with the same last part.",
              "Check that {to} is the same page; if it is, change the address in "
              "docs/clients.md to it."),
    "absent": ("{address} was not found",
               "{address} is not in Agent Docs, and it does not redirect.",
               "Find the page's new address, or take it out of docs/clients.md."),
}
# Said once each: an address with this verdict is said again only when its `to` changes.
TOLD_ONCE = ("maybe", "absent")


def _moved_item(record: dict) -> dict:
    title, changed, fix = (t.format(**record) for t in MOVED_TEXT[record["verdict"]])
    return {
        "effect": "outdated", "severity": "minor", "sure": record["verdict"] != "maybe",
        "title": _quiet(title, TITLE_MAX), "client": record["client"],
        "changed": _quiet(changed, TEXT_MAX), "fix": _quiet(fix, TEXT_MAX),
        "why": "Agent Docs keeps every doc page it holds; a page of the list that is not "
               "there may have moved, and the watcher may be reading an old page.",
        "user_gets": "not checked", "systems": "", "row": "", "files": [],
        "version": "", "url": record["address"],
    }


def plan_moved(state, manifest, pages, hosts, locate, week):
    """Once a week, put into `kept` the doc pages of the list that are not in the manifest.

    `manifest` is the set of its addresses, or None when it could not be read today: then
    nothing is checked and the week stays open for the next run. A `maybe` or `absent`
    address is said once, and again only when its `to` changes (`told`: address -> to);
    `moved` is said again each week until the list is fixed.
    """
    new = copy.deepcopy(state)
    if manifest is None or new.get("moved", {}).get("week") == week:
        return new
    old = new.get("moved", {}).get("told", {})
    told = {}
    titles = {k["title"] for k in new["kept"]}
    for record in moved(pages, manifest, hosts, locate):
        address, to = record["address"], record["to"]
        if record["verdict"] in TOLD_ONCE:
            told[address] = to
            if address in old and old[address] == to:
                continue
        item = _moved_item(record)
        if item["title"] not in titles:
            titles.add(item["title"])
            new["kept"].append(item)
    # Only the addresses absent or maybe today: one that is fixed, or left the list, is
    # forgotten.
    new["moved"] = {"week": week, "told": told}
    return new


# The page's address is in the item's `url` (when SHOWABLE matches it), never in its text.
UNSTABLE_TEXT = {
    "changed": "Two reads of this page in one run gave different text, so a real change "
               "cannot be told from what changes on each read. The watcher no longer reads it.",
    "fix": "Check the facts that name this page by hand when you check the others. To watch it "
           "again, point them at a page that reads the same each time, such as the raw file, or "
           "take its entry out of `fact_pages` in the watcher's memory.",
    "why": "The watcher keeps a hash of each page a fact names and tells when it changes. A "
           "page that reads differently each time would look changed every day.",
}


def _unstable_item(address: str, client: str) -> dict:
    text = {k: _quiet(t, TEXT_MAX) for k, t in UNSTABLE_TEXT.items()}
    return {
        "effect": "unknown", "severity": "minor", "sure": True,
        "title": _title(address, UNSTABLE_END), "client": client, **text,
        "user_gets": "not checked", "systems": "", "row": "", "files": [],
        "version": "", "url": address if SHOWABLE.fullmatch(address) else "",
    }


def _fact_pages(state) -> dict[str, dict]:
    """The memory's `fact_pages`, each entry in its shape. An entry with no hash is left out, so
    its page is new again; a `changed` that is not a day is "", an `unstable` that is not true
    is false."""
    pages = state.get("fact_pages") if isinstance(state, dict) else None
    out = {}
    for address, e in pages.items() if isinstance(pages, dict) else ():
        if isinstance(e, dict) and isinstance(e.get("hash"), str):
            out[address] = {"hash": e["hash"],
                            "changed": e["changed"] if _is_day(e.get("changed")) else "",
                            "unstable": e.get("unstable") is True}
    return out


def plan_stale(state, facts: list[Fact], hashes: dict[str, str | None], unstable: set[str],
               today: date, week: str) -> dict:
    """The memory after today's reads of the pages the facts name, and once a week the stale
    pages in `kept`.

    `fact_pages` keeps, for each page a fact names (Fact.address), its hash (watch_stale.
    page_hash), the last day that hash changed and whether the page cannot be watched. A page
    seen for the first time gets its hash and the day ""; a hash that differs sets the day to
    `today`; a page not read today (None in `hashes`, or not there) keeps its entry; a page no
    fact names any more is dropped. A page in `unstable` (its two reads today differed) keeps
    its old hash and day, is marked, and gets one item in `kept`. A page already marked is
    never compared again.

    In a new `week` (`stale_week`), watch_stale.stale gives one item a page that changed after
    one of its facts was checked; an item whose title is already in `kept` is not added. It
    comes again each week until the facts' dates are later. The items wait for the summary,
    as the moved check's do: none is an urgent issue.
    """
    new = copy.deepcopy(state)
    kept = new.setdefault("kept", [])
    titles = {k["title"] for k in kept}
    old = _fact_pages(state)
    clients: dict[str, str] = {}
    for fact in facts:
        clients.setdefault(fact.address, fact.client)
    pages = {}
    for address, client in clients.items():
        entry, found = old.get(address), hashes.get(address)
        if entry and entry["unstable"]:
            pages[address] = entry
        elif address in unstable:
            pages[address] = {**(entry or {"hash": "", "changed": ""}), "unstable": True}
            item = _unstable_item(address, client)
            if item["title"] not in titles:
                titles.add(item["title"])
                kept.append(item)
        elif found is None:
            if entry:
                pages[address] = entry
        elif entry is None:
            pages[address] = {"hash": found, "changed": "", "unstable": False}
        elif entry["hash"] != found:
            pages[address] = {"hash": found, "changed": today.isoformat(), "unstable": False}
        else:
            pages[address] = entry
    new["fact_pages"] = pages
    if new.get("stale_week") != week:
        for item in stale(facts, {a: e["changed"] for a, e in pages.items()}):
            if item["title"] not in titles:
                titles.add(item["title"])
                kept.append(item)
        new["stale_week"] = week
    return new


def _is_day(value) -> bool:
    """Whether `value` is a day written YYYY-MM-DD."""
    try:
        return isinstance(value, str) and date.fromisoformat(value).isoformat() == value
    except ValueError:
        return False


def _waiting(items) -> list[Entry]:
    """The memory's waiting entries, in their order; one of another shape is skipped."""
    out = []
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        day, kind, url, product, headings = (item.get(k) for k in Entry._fields)
        if (_is_day(day) and kind in ("added", "changed") and isinstance(url, str)
                and isinstance(product, str) and isinstance(headings, list)
                and all(isinstance(h, str) for h in headings)):
            out.append(Entry(day, kind, url, product, tuple(headings)))
    return out


def _stored(e: Entry) -> dict:
    return {**e._asdict(), "sections": [h[:HEADING_CHARS] for h in e.sections[:HEADINGS_MAX]]}


def _taken(feed: dict) -> set[str] | None:
    """The memory's taken page keys, or None when it has none (as before `taken` was kept):
    then no more entries of its day are taken."""
    taken = feed.get("taken")
    if isinstance(taken, list) and all(isinstance(k, str) for k in taken):
        return set(taken)
    return None


def _keys(entries: list[Entry], day: str, hosts) -> list[str]:
    """The page keys of the entries of `day`, in order, each once, at most TAKEN_MAX."""
    found = [page_key(page_of(e.url, hosts)) for e in entries if e.day == day]
    return list(dict.fromkeys(found))[:TAKEN_MAX]


def _one_a_page(entries: list[Entry], hosts) -> list[Entry]:
    """`entries` with one entry a page (watch_feed.page_key), in the place of its first: a
    page in the queue from two days makes one piece a run. The later day names it, and its new
    headings are both days': added when either is added."""
    out: dict[str, Entry] = {}
    for e in entries:
        key = page_key(page_of(e.url, hosts))
        first = out.get(key)
        if first is None:
            out[key] = e
            continue
        early, late = sorted((first, e), key=lambda x: x.day)
        added = "added" in (first.kind, e.kind)
        out[key] = late._replace(
            kind="added" if added else "changed",
            sections=() if added else tuple(dict.fromkeys(early.sections + late.sections)))
    return list(out.values())


def _count(feed: dict, name: str) -> int:
    n = feed.get(name, 0)
    return n if type(n) is int and n >= 0 else 0


class Made(NamedTuple):
    """A feed piece of this run, its entry's day and the words that kept its sections: each
    once, in the order first found."""

    piece: dict
    day: str
    words: tuple[str, ...]


def plan_feed(state, entries, listed, hosts, read_page, words, today, room,
              in_time=lambda: True, *, source=FEED_SOURCE):
    """The feed's pieces of this run and the memory after them, in live (WATCH_FEED).

    `entries` are the feed's (watch_feed.read_feed), or None when it could not be read: then
    the memory is left as it was. With no `feed` in the memory, the feed's newest day is
    taken and nothing is read, as on any source's first run.

    Otherwise the queue is the entries waiting in `feed.wait`, then the feed's entries not
    taken yet, both through watch_feed.wanted (so a page that joined the list, `listed`,
    leaves it). Not taken yet: of a day after `feed.day`, or of that day with a page key
    (watch_feed.page_key) not in `feed.taken`, since Agent Docs merges a second reindex of a
    day into it. `taken` holds the keys of the entries taken on the last day taken; a memory
    without it takes no more of its day. In that order, an entry leaves the queue when:
    - route marked its piece judged, or given up after its third failed try: its key is in
      `sources[source]`. That map is emptied each run, so it does not grow;
    - its day is more than KEEP_DAYS days before `today` (counted in `dropped`);
    - its page is in the queue from a later day too: the two make one entry of the later day
      (`_one_a_page`), so a page makes one piece a run;
    - its page's client (doc_address.client_of, never the feed's product) is in
      NO_TEXT_CLIENTS: the page is not read (counted in `held`). So is a page whose read
      ended, after redirects, at an address of another client or of one in NO_TEXT_CLIENTS;
    - its page holds no section that watch_feed.kept_sections keeps, from every section of an
      added page or the sections `pick` finds for a changed page's new headings;
    - its page is gone: the read answered 404 or 410 (counted in `gone`).
    The rest make a piece each, read with `read_page(page_of(url))`, which gives the page's
    sections and the address read from, until there are min(room, FEED_PIECES_MAX) pieces,
    FEED_PAGES_MAX pages were read or `in_time()` is false (the run's page budget). An entry
    that made a piece, was not reached, or whose read failed another way stays in the queue;
    neither is a failed read of the feed. A failed one goes to the back of the queue, so pages
    that keep failing cannot take every read of each run; `feed.failed` counts them, this
    run's only. A page is read once a run. The queue keeps WAIT_MAX entries; the rest are
    dropped and counted.

    `words` maps a client to its list words. Prints one line of counts (and the class of each
    failed read); no address or heading.
    """
    made, new = _plan_feed(state, entries, listed, hosts, read_page, words, today, room,
                           in_time, source=source, shadow=False)
    return [m.piece for m in made], new


def plan_shadow(state, entries, listed, hosts, read_page, words, today, room,
                in_time=lambda: True, *, source=FEED_SOURCE):
    """plan_feed in shadow (WATCH_FEED): the rows of this run and the memory after them.

    The same entries are read and the same pieces made, under the same caps, so the rows show
    what live would send. But no piece goes to the judge, so route never marks one judged:
    an entry leaves the queue as soon as its row is made. A row is the page's address (it
    passed doc_address.allowed), the entry's day, the words that kept its sections (one a
    section from watch_feed.kept_sections, which made the piece; each word once, in page
    order) and the length of the piece's text. It holds no page text and no heading.
    """
    made, new = _plan_feed(state, entries, listed, hosts, read_page, words, today, room,
                           in_time, source=source, shadow=True)
    return [{"page": m.piece["url"], "day": m.day, "words": list(m.words),
             "chars": len(m.piece["text"])} for m in made], new


def _plan_feed(state, entries, listed, hosts, read_page, words, today, room, in_time, *,
               source, shadow):
    new = copy.deepcopy(state)
    if entries is None:
        return [], new
    feed = new.get("feed")
    newest = max((e.day for e in entries), default="")
    if not (isinstance(feed, dict) and (feed.get("day") == "" or _is_day(feed.get("day")))):
        fill = wanted([e for e in entries if e.day == newest], hosts, listed, "")
        new["feed"] = {"day": newest, "wait": [], "dropped": 0, "held": 0, "gone": 0,
                       "taken": _keys(fill, newest, hosts)}
        return [], new
    day, taken = feed["day"], _taken(feed)
    done = new.setdefault("sources", {}).pop(source, None)
    done = done if isinstance(done, dict) else {}
    fresh = [e for e in entries if e.day > day or (
        e.day == day and taken is not None and page_key(page_of(e.url, hosts)) not in taken)]
    queue = wanted(_waiting(feed.get("wait")) + fresh, hosts, listed, "")
    cap = max(0, min(room, FEED_PIECES_MAX))
    made, wait, retry, pages, live = [], [], [], {}, []
    dropped = held = failed = gone = 0
    for e in queue:
        if f"{page_of(e.url, hosts)}@{e.day}" in done:
            continue
        if (today - date.fromisoformat(e.day)).days > KEEP_DAYS:
            dropped += 1
            continue
        live.append(e)
    for e in _one_a_page(live, hosts):
        page = page_of(e.url, hosts)
        key = f"{page}@{e.day}"
        client = client_of(page, hosts)
        if client in NO_TEXT_CLIENTS:
            held += 1
            continue
        if len(made) >= cap:
            wait.append(e)
            continue
        if page not in pages:
            if len(pages) >= FEED_PAGES_MAX or not in_time():
                wait.append(e)
                continue
            try:
                found, read_from = read_page(page)
                # A redirect may end on another client's page: its text is that client's.
                other = client_of(read_from, hosts)
                pages[page] = found if other == client and other not in NO_TEXT_CLIENTS else "held"
            except urllib.error.HTTPError as error:
                if error.code not in GONE:
                    print(f"feed: cannot read a page: {type(error).__name__}", file=sys.stderr)
                    failed += 1
                # A gone page (deleted after it was indexed) would cost a read every run.
                pages[page] = "gone" if error.code in GONE else None
            except Exception as error:  # noqa: BLE001 - the entry waits for the next run
                print(f"feed: cannot read a page: {type(error).__name__}", file=sys.stderr)
                pages[page] = None
                failed += 1
        if pages[page] == "gone":
            gone += 1
            continue
        if pages[page] == "held":
            held += 1
            continue
        if pages[page] is None:
            retry.append(e)
            continue
        offered = pages[page] if e.kind == "added" else pick(pages[page], list(e.sections))
        kept = kept_sections(offered, words.get(client, []))
        if not kept:
            continue
        text = "\n\n".join(section.text for section, _ in kept)[:PIECE_CHARS]
        made.append(Made({
            "id": f"{source}#{key}", "kind": "doc", "client": client, "version": "",
            "url": page, "text": text, "source": source, "key": key,
            "hash": hashlib.sha256(text.encode()).hexdigest(),
        }, e.day, tuple(dict.fromkeys(word for _, word in kept))))
        # Live: it waits until route marks it judged. Shadow: its row is the end of it.
        if not shadow:
            wait.append(e)
    wait += retry
    dropped += max(0, len(wait) - WAIT_MAX)
    wait = wait[:WAIT_MAX]
    new["feed"] = {"day": max(day, newest), "wait": [_stored(e) for e in wait],
                   "dropped": _count(feed, "dropped") + dropped,
                   "held": _count(feed, "held") + held, "gone": _count(feed, "gone") + gone,
                   "failed": failed}
    if new["feed"]["day"] != day:
        new["feed"]["taken"] = _keys(queue, new["feed"]["day"], hosts)
    elif taken is not None:
        # The memory's own order first, so the cut never drops a key already kept.
        both = feed["taken"] + _keys(queue, day, hosts)
        new["feed"]["taken"] = list(dict.fromkeys(both))[:TAKEN_MAX]
    print(f"feed{' (shadow)' if shadow else ''}: {len(made)} pieces, {len(wait)} waiting, "
          f"{len(pages)} pages read, {failed} failed, {dropped} dropped, {gone} gone, "
          f"{held} held back (no text for {'/'.join(NO_TEXT_CLIENTS)})", file=sys.stderr)
    return made, new


def feed_counts(mode: str, state, pieces: int, planned: bool = True) -> dict:
    """The feed's counts for input.json and the log, one for each name of watch_feed.COUNTS:
    `pieces` (this run's pieces, or rows in shadow), `waiting` (the queue after this run),
    `failed` (this run's failed page reads; 0 when this run did not plan the feed, `planned`),
    and the memory's running totals for the rest. A memory with no feed of its shape counts 0.
    """
    feed = state.get("feed") if isinstance(state, dict) else None
    feed = feed if isinstance(feed, dict) else {}
    wait = feed.get("wait")
    this_run = {"pieces": pieces, "waiting": len(wait) if isinstance(wait, list) else 0,
                "failed": _count(feed, "failed") if planned else 0}
    return {"mode": mode, **{name: this_run[name] if name in this_run else _count(feed, name)
                             for name in COUNTS}}


def feed_mode(value: str | None) -> str:
    """The feed's mode (watch_feed.MODES) from the value of WATCH_FEED. Unset, empty or `off`
    is off; any other value is off too, with one line on stderr. That line shows the value
    only when it is a short lower-case word."""
    if value in (None, "", "off"):
        return "off"
    if value in MODES:
        return value
    shown = f'is "{value}"' if SHOWN_MODE.fullmatch(value) else "has an unknown value"
    print(f"WATCH_FEED {shown}, not off, shadow or live: the feed is treated as off.",
          file=sys.stderr)
    return "off"


def list_words(list_text: str) -> dict[str, list[str]]:
    """The list's words (watch_list.terms) of each client, in the list's order, each once."""
    out: dict[str, list[str]] = {}
    for (client, _), found in terms(list_text).items():
        words = out.setdefault(client, [])
        words.extend(w for w in dict.fromkeys(found) if w not in words)
    return out


def build_input(pieces, kitden, list_text, file_names, same, release, titles, new_state):
    files = {}
    for name in file_names:
        path = Path(kitden) / name
        if path.is_file():
            files[name] = {"text": path.read_text(encoding="utf-8"), "same_in_release": same(name)}
    kept = [k["title"] for k in new_state.get("kept", [])]
    return {"pieces": pieces, "list": list_text, "files": files, "release": release,
            "known_titles": titles + kept, "state": new_state}


def _git(kitden, *args):
    return subprocess.run(["git", "-C", str(kitden), *args], capture_output=True, text=True)  # noqa: S603, S607


def _read(source):
    if source["kind"] == "github-releases":
        body, _ = get(f"https://api.github.com/repos/{source['repo']}/releases")
        return releases(json.loads(body))
    body, ctype = get(source["url"])
    return sections(body, ctype, source.get("level", 3), source.get("split"))


def read_manifest(source):
    """The addresses in Agent Docs' manifest, read with the 5 MB limit."""
    body, _ = get(source["url"], limit=MANIFEST_MAX)
    return manifest_addresses(body)


def _read_doc(address, hosts):
    body, ctype, _ = get_doc(address, hosts)
    return sections(body, ctype)


def rule_read_address(address: str) -> str:
    """Where a rule page is read from: a GitHub blob address
    (https://github.com/OWNER/REPO/blob/REF/PATH) from its raw file
    (https://raw.githubusercontent.com/OWNER/REPO/REF/PATH); any other at itself."""
    found = BLOB.fullmatch(address)
    return f"https://{RAW_HOST}/{found[1]}/{found[2]}/{found[3]}" if found else address


def read_rule_page(address: str, hosts, handlers=()) -> list[Section]:
    """The sections of a page of docs/platform-rules.md.

    An address the config's `hosts` allow is read as any doc page (get_doc). Any other is read
    at rule_read_address(address) only, with that address's host and path as the one allowed
    pair, a doc_address.Page: a redirect is followed only to the same path, or below it by
    whole path parts ("/submit/", never "/submitx"), and only to the root for a page at the
    root. Any other redirect raises ValueError before it is followed, and so does an address
    with a user, a port or a query. The pair is used for this read only; `hosts` is not
    changed. `handlers` go into the opener: tests use them to answer without the network.
    Raises like doc_address.read.
    """
    if allowed(address, hosts):
        body, ctype, _ = get_doc(address, hosts, make_opener(hosts, True, *handlers))
        return sections(body, ctype)
    source = rule_read_address(address)
    parts = urllib.parse.urlsplit(source)
    if not parts.hostname:
        raise ValueError("a rule page's address has no host")
    pair = [Page(parts.hostname, parts.path)]
    body, ctype, _ = doc_address.read(source, pair, make_opener(pair, True, *handlers))
    return sections(body, ctype)


class RuleReads(NamedTuple):
    """What read_rules read: each page read and its sections (None for a failed read), the
    hash of each page whose hash is sure today, the pages whose two reads differed, how many
    pages of the order were done, and why the reads stopped: "cap" (RULE_PAGES_MAX), "time",
    or "" when every page was done."""

    fetched: dict[str, list[Section] | None]
    hashes: dict[str, str]
    unstable: set[str]
    done: int
    stopped: str


def read_rules(order: list[str], known: dict[str, str], reader, in_time) -> RuleReads:
    """Read the rule pages in `order` with `reader` (sections, or None when the read failed),
    at most RULE_PAGES_MAX reads, while `in_time()`.

    A page whose hash is not its hash in `known` (a new page, or one that changed) is read once
    more: the same hash twice is its hash today; two hashes make it unstable; a failed second
    read is a failed read. A page whose second read finds no room or no time stops the reads
    there: its first read counts, and it is not done, so the next run starts at it.
    """
    fetched: dict[str, list[Section] | None] = {}
    hashes: dict[str, str] = {}
    unstable: set[str] = set()
    reads = done = 0
    stopped = ""

    def stop() -> str:
        """Why no more read may start now, or "" when one may. Asked when the reads would
        stop, so the reason is the one at that moment."""
        if reads >= RULE_PAGES_MAX:
            return "cap"
        return "" if in_time() else "time"

    for address in order:
        if stopped := stop():
            break
        found = reader(address)
        reads += 1
        fetched[address] = found
        if found is not None:
            first = page_hash(found)
            if known.get(address) != first:
                if stopped := stop():
                    break
                again = reader(address)
                reads += 1
                if again is None:
                    fetched[address] = None
                    done += 1
                    continue
                if page_hash(again) != first:
                    unstable.add(address)
                    done += 1
                    continue
            hashes[address] = first
        done += 1
    return RuleReads(fetched, hashes, unstable, done, stopped)


def _read_feed_page(address, hosts, opener=None):
    """A feed page's sections and the address it was read from, after redirects: plan_feed
    checks that address's client."""
    body, ctype, read_from = get_doc(address, hosts, opener)
    return sections(body, ctype), read_from


# The skipped rows and rules the log line names, each kind; the rest are counted.
SKIPPED_SHOWN = 20


def _some(things: list, word: str) -> str:
    """ "(<word> a, b and n more)": at most SKIPPED_SHOWN, or "" when there are none."""
    if not things:
        return ""
    shown = ", ".join(str(t) for t in things[:SKIPPED_SHOWN])
    more = f" and {len(things) - SKIPPED_SHOWN} more" if len(things) > SKIPPED_SHOWN else ""
    return f" ({word}{shown}{more})"


def facts_line(list_found: list[Fact], undated: list[str], rule_found: list[Fact],
               skipped: list[int]) -> str:
    """The log line of the facts: how many, and which were skipped for want of a date: the
    list's row ids (watch_list's own ids, never the list's text) and the rules file's line
    numbers, at most SKIPPED_SHOWN of each."""
    rows = f"{len(undated)} row{'' if len(undated) == 1 else 's'} of the list"
    lines = "line " if len(skipped) == 1 else "lines "
    return (f"Facts with a page and a date: {len(list_found) + len(rule_found)} "
            f"({len(list_found)} in the list, {len(rule_found)} in the rules); skipped for want "
            f"of a date: {rows}{_some(undated, '')}, {len(skipped)} in the rules"
            f"{_some(skipped, lines)}.")


def read_or_none(sid, reader, address):
    """`reader(address)`, or None with one line on stderr when it fails."""
    try:
        return reader(address)
    except Exception as e:  # noqa: BLE001 - one unreadable source must not stop the run
        print(f"cannot read {sid}: {type(e).__name__}", file=sys.stderr)
        return None


def main(argv=None, clock=time.monotonic):
    ap = argparse.ArgumentParser()
    for name in ("sources", "kitden", "state", "titles", "out"):
        ap.add_argument(f"--{name}", required=True)
    a = ap.parse_args(argv)
    state = json.loads(Path(a.state).read_text()) if Path(a.state).is_file() else None
    list_text = (Path(a.kitden) / "docs/clients.md").read_text(encoding="utf-8")
    rows = parse_list(list_text)
    list_found, undated = scan_list(list_text)
    rule_found, skipped = scan_rules(RULES_FILE.read_text(encoding="utf-8"))
    facts = list_found + rule_found
    print(facts_line(list_found, undated, rule_found, skipped), file=sys.stderr)
    fetched, meta = {}, {}
    hosts = load_hosts()
    today = date.today()
    mode = feed_mode(os.environ.get("WATCH_FEED"))
    manifests, feed = [], None
    for src in load_sources(a.sources):
        if src["kind"] == "manifest":
            meta[src["id"]] = {"kind": "manifest", "url": src["url"]}
            fetched[src["id"]] = read_or_none(src["id"], read_manifest, src)
            manifests.append(fetched[src["id"]])
            continue
        if src["kind"] == "feed":
            # The memory has one `feed`: a second feed source would share its queue.
            if feed is not None:
                raise ValueError("the sources may hold only one feed source")
            feed = src["id"]
            if mode == "off":
                # Skipped before it is read: out of meta and fetched, it is never a failed
                # read, and plan_feed never touches the memory's `feed`.
                continue
            meta[feed] = {"kind": "feed", "url": src["url"]}
            fetched[feed] = read_or_none(feed, lambda s: read_feed(s, today), src)
            continue
        meta[src["id"]] = {"client": src["client"], "kind": "release",
                           "url": src.get("url") or f"https://github.com/{src['repo']}/releases"}
        fetched[src["id"]] = read_or_none(src["id"], _read, src)
    pages = doc_pages(rows)
    order = page_order(state, pages)
    budget = Budget(PAGES_SECONDS, clock)
    done = 0
    for address in order:
        if not budget.left():
            # Left out of meta and fetched: plan_run keeps their hashes and counts no fail.
            print(f"Out of time for doc pages after {PAGES_SECONDS} seconds; left for "
                  f"tomorrow: {len(order) - done}.", file=sys.stderr)
            break
        meta[address] = {"client": pages[address], "kind": "doc", "url": address}
        fetched[address] = read_or_none(address, lambda u: _read_doc(u, hosts), address)
        done += 1
    # The rules' pages, after the list's, in the same budget. A page the list names too was
    # read above; one that cannot be watched is not read again.
    known = _fact_pages(state)
    rule_pages = ({f.address for f in rule_found} - {page_address(p) for p in pages}
                  - {a for a, e in known.items() if e["unstable"]})
    rule_order = page_order(state, rule_pages, key="rule_start")
    got = read_rules(rule_order, {a: e["hash"] for a, e in known.items()},
                     lambda u: read_or_none(u, lambda x: read_rule_page(x, hosts), u),
                     budget.left)
    for address, found in got.fetched.items():
        meta[address] = {"client": RULES_CLIENT, "kind": "rule-page", "url": address}
        fetched[address] = found
    if got.stopped:
        # Left out of meta: plan_run counts no fail, and plan_stale keeps their entries.
        why = (f"Out of time for rule pages after {PAGES_SECONDS} seconds"
               if got.stopped == "time"
               else f"{RULE_PAGES_MAX} reads of rule pages, the most a run, are used")
        print(f"{why}; left for tomorrow: {len(rule_order) - got.done}.", file=sys.stderr)
    pieces, new_state = plan_run(state, fetched, meta)
    # plan_run keeps the memory's page_start and rule_start, so plan_skips sees today's order.
    new_state = plan_skips(new_state, pages, done)
    new_state = plan_skips(new_state, dict.fromkeys(rule_pages, RULES_CLIENT), got.done,
                           RULE_TURNS)
    week = week_of(today)
    # A list page's hash is made from the sections read above: it is not read again.
    hashes: dict[str, str | None] = dict(got.hashes)
    named = {f.address for f in facts}
    for page in pages:
        address = page_address(page)
        if address in named and fetched.get(page) is not None:
            hashes.setdefault(address, page_hash(fetched[page]))
    new_state = plan_stale(new_state, facts, hashes, got.unstable, today, week)
    if manifests and budget.left():
        read = None if None in manifests else set().union(*manifests)
        new_state = plan_moved(new_state, read, pages, hosts,
                               lambda u: location(u, hosts), week)
    elif manifests and new_state.get("moved", {}).get("week") != week:
        # Its requests are page reads too. The week stays open, so the next run with time
        # does it.
        print("Out of time: the weekly check for moved pages waits for the next run.",
              file=sys.stderr)
    found = []
    if feed is not None and mode != "off":
        # Shadow has the caps of live: the same room, the same budget, the same page cap.
        plan = plan_shadow if mode == "shadow" else plan_feed
        found, new_state = plan(new_state, fetched[feed], set(pages), hosts,
                                lambda u: _read_feed_page(u, hosts), list_words(list_text),
                                today, PIECES_MAX - len(pieces), budget.left, source=feed)
    if mode == "live":
        pieces = pieces + found
    release = _git(a.kitden, "describe", "--tags", "--abbrev=0").stdout.strip()
    names = sorted({f for r in rows for f in r.files})

    def same(name):
        return _git(a.kitden, "diff", "--quiet", release, "HEAD", "--", name).returncode == 0

    titles = json.loads(Path(a.titles).read_text())
    out = build_input(pieces, a.kitden, list_text, names, same, release, titles,
                      new_state)
    # The Kitden commit the pieces are judged at: the archive keeps it, so a harvested task is
    # pinned to it (evals/watch_harvest.py).
    out["kitden"] = _git(a.kitden, "rev-parse", "HEAD").stdout.strip()
    # A run that did not plan the feed (off, or the feed unread) read none of its pages.
    planned = feed is not None and mode != "off" and fetched.get(feed) is not None
    out["feed"] = feed_counts(mode, new_state, len(found), planned)
    if mode == "shadow":
        # Rows only: an address, a day, words, a number. The judge never reads this file.
        Path(a.out).with_name(SHADOW_FILE).write_text(json.dumps(found, indent=1),
                                                      encoding="utf-8")
    Path(a.out).write_text(json.dumps(out, indent=1), encoding="utf-8")
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a") as f:
            f.write(f"pieces={len(pieces)}\n")


if __name__ == "__main__":
    main()
