"""Fetch what is new in the watched sources and write the input for the judge."""

import argparse
import copy
import hashlib
import json
import os
import subprocess  # noqa: S404
import sys
import time
from datetime import date
from pathlib import Path

from doc_address import NO_TEXT_CLIENTS, client_of, load_hosts, location, page_of
from watch_feed import KEEP_DAYS, Entry, kept_sections, read_feed, wanted
from watch_list import doc_pages, parse_list, terms
from watch_moved import manifest_addresses, moved
from watch_pages import get, get_doc, load_sources, pick, releases, sections
from watch_route import TEXT_MAX, TITLE_MAX, _quiet, week_of

PIECES_MAX = 20
PIECE_CHARS = 12000
MANIFEST_MAX = 5 * 1024 * 1024  # bytes; a larger manifest is a failed read
FAIL_DAYS = 3
# 2: doc pages are read as markdown. A memory with a lower number holds hashes of HTML
# sections, so its doc pages are filled again, quietly, as if new.
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
FEED_SOURCE = "agent-docs-feed"


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


def _out_of_time(addresses: list[str], pages: dict[str, str]) -> dict:
    """One item for the doc pages that reached FAIL_DAYS skipped runs in one run. The title
    stays short (the summary's table cuts at 80 characters); the text lists the pages."""
    count = len(addresses)
    pages_were = "1 doc page was" if count == 1 else f"{count} doc pages were"
    clients = {pages[a] for a in addresses}
    listed = ", ".join(f"`{a}`" for a in addresses)
    return {**_unreadable({"client": clients.pop() if len(clients) == 1 else "", "url": ""},
                          "doc pages"),
            "title": f"{pages_were} not read for {FAIL_DAYS} runs: out of time",
            "changed": f"Each of the last {FAIL_DAYS} runs ran out of time before {listed}."}


def _start(state, count: int) -> int:
    start = state.get("page_start", 0) if state else 0
    # A bool is an int in Python; it is not a place in the list.
    if type(start) is not int or not count:
        return 0
    return start % count


def page_order(state, pages: dict[str, str]) -> list[str]:
    """The doc pages in the order to read them: sorted, from the memory's `page_start`,
    wrapping around. So on a slow day the pages a run did not reach come first the next day."""
    order = sorted(pages)
    start = _start(state, len(order))
    return order[start:] + order[:start]


def plan_skips(state, pages: dict[str, str], read: int) -> dict:
    """The memory after a run that started `read` pages of page_order(state, pages).

    `page_start` moves to the first page left unread, or stays when every page was read.
    `skips` counts, for each page left unread, the runs in a row that left it unread; a page
    whose read was started is dropped from it, and so is a page that left the list. The
    pages that reach their third run in a row today go to `kept` as one item, so a slow site
    makes one line of the summary, not one for each page.
    """
    new = copy.deepcopy(state)
    order = page_order(state, pages)
    new["page_start"] = (_start(state, len(order)) + read) % len(order) if order else 0
    old = state.get("skips") if isinstance(state.get("skips"), dict) else {}
    new["skips"] = {}
    for address in order[read:]:
        count = old.get(address, 0)
        new["skips"][address] = (count if type(count) is int else 0) + 1
    # == and not >=: a page is in the item of the run it reaches its third skip, not again.
    third = [address for address, count in new["skips"].items() if count == FAIL_DAYS]
    if third:
        new["kept"].append(_out_of_time(third, pages))
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
            item = _unreadable(meta[sid], sid)
            if new["fails"][sid] == FAIL_DAYS and all(
                k["title"] != item["title"] for k in new["kept"]
            ):
                new["kept"].append(item)
            continue
        new["fails"][sid] = 0
        # The manifest is read for the weekly moved check only; the feed's pieces are made by
        # plan_feed. Neither is hash-compared here.
        if meta[sid]["kind"] in ("manifest", "feed"):
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


def _count(feed: dict, name: str) -> int:
    n = feed.get(name, 0)
    return n if type(n) is int and n >= 0 else 0


def plan_feed(state, entries, listed, hosts, read_page, words, today, room,
              in_time=lambda: True, *, source=FEED_SOURCE):
    """The feed's pieces of this run and the memory after them.

    `entries` are the feed's (watch_feed.read_feed), or None when it could not be read: then
    the memory is left as it was. With no `feed` in the memory, the feed's newest day is
    taken and nothing is read, as on any source's first run.

    Otherwise the queue is the entries waiting in `feed.wait`, then the feed's entries of the
    days after `feed.day`, both through watch_feed.wanted (so a page that joined the list,
    `listed`, leaves it). In that order, an entry leaves the queue when:
    - route marked its piece judged, or given up after its third failed try: its key is in
      `sources[source]`. That map is emptied each run, so it does not grow;
    - its day is more than KEEP_DAYS days before `today` (counted in `dropped`);
    - its page's client (doc_address.client_of, never the feed's product) is in
      NO_TEXT_CLIENTS: the page is not read (counted in `held`);
    - its page holds no section that watch_feed.kept_sections keeps, from every section of an
      added page or the sections `pick` finds for a changed page's new headings.
    The rest make a piece each, read with `read_page(page_of(url))`, until there are
    min(room, FEED_PIECES_MAX) pieces, FEED_PAGES_MAX pages were read or `in_time()` is false
    (the run's page budget). An entry that made a piece, was not reached, or whose read failed
    stays in the queue; neither is a failed read of the feed. A page is read once a run. The
    queue keeps WAIT_MAX entries; the rest are dropped and counted.

    `words` maps a client to its list words. Prints one line of counts (and the class of each
    failed read); no address or heading.
    """
    new = copy.deepcopy(state)
    if entries is None:
        return [], new
    feed = new.get("feed")
    newest = max((e.day for e in entries), default="")
    if not (isinstance(feed, dict) and (feed.get("day") == "" or _is_day(feed.get("day")))):
        new["feed"] = {"day": newest, "wait": [], "dropped": 0, "held": 0}
        return [], new
    day = feed["day"]
    done = new.setdefault("sources", {}).pop(source, None)
    done = done if isinstance(done, dict) else {}
    queue = wanted(_waiting(feed.get("wait")) + [e for e in entries if e.day > day],
                   hosts, listed, "")
    cap = max(0, min(room, FEED_PIECES_MAX))
    pieces, wait, pages = [], [], {}
    dropped = held = failed = 0
    for e in queue:
        page = page_of(e.url, hosts)
        key = f"{page}@{e.day}"
        if key in done:
            continue
        if (today - date.fromisoformat(e.day)).days > KEEP_DAYS:
            dropped += 1
            continue
        client = client_of(page, hosts)
        if client in NO_TEXT_CLIENTS:
            held += 1
            continue
        if len(pieces) >= cap:
            wait.append(e)
            continue
        if page not in pages:
            if len(pages) >= FEED_PAGES_MAX or not in_time():
                wait.append(e)
                continue
            try:
                pages[page] = read_page(page)
            except Exception as error:  # noqa: BLE001 - the entry waits for the next run
                print(f"feed: cannot read a page: {type(error).__name__}", file=sys.stderr)
                pages[page] = None
                failed += 1
        if pages[page] is None:
            wait.append(e)
            continue
        offered = pages[page] if e.kind == "added" else pick(pages[page], list(e.sections))
        kept = kept_sections(offered, words.get(client, []))
        if not kept:
            continue
        text = "\n\n".join(section.text for section, _ in kept)[:PIECE_CHARS]
        pieces.append({
            "id": f"{source}#{key}", "kind": "doc", "client": client, "version": "",
            "url": page, "text": text, "source": source, "key": key,
            "hash": hashlib.sha256(text.encode()).hexdigest(),
        })
        wait.append(e)
    dropped += max(0, len(wait) - WAIT_MAX)
    wait = wait[:WAIT_MAX]
    new["feed"] = {"day": max(day, newest), "wait": [_stored(e) for e in wait],
                   "dropped": _count(feed, "dropped") + dropped,
                   "held": _count(feed, "held") + held}
    print(f"feed: {len(pieces)} pieces, {len(wait)} waiting, {len(pages)} pages read, "
          f"{failed} failed, {dropped} dropped, {held} held back "
          f"(no text for {'/'.join(NO_TEXT_CLIENTS)})", file=sys.stderr)
    return pieces, new


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
    fetched, meta = {}, {}
    hosts = load_hosts()
    today = date.today()
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
    pieces, new_state = plan_run(state, fetched, meta)
    # plan_run keeps the memory's page_start, so plan_skips sees today's order.
    new_state = plan_skips(new_state, pages, done)
    week = week_of(today)
    if manifests and budget.left():
        read = None if None in manifests else set().union(*manifests)
        new_state = plan_moved(new_state, read, pages, hosts,
                               lambda u: location(u, hosts), week)
    elif manifests and new_state.get("moved", {}).get("week") != week:
        # Its requests are page reads too. The week stays open, so the next run with time
        # does it.
        print("Out of time: the weekly check for moved pages waits for the next run.",
              file=sys.stderr)
    if feed is not None:
        found, new_state = plan_feed(new_state, fetched[feed], set(pages), hosts,
                                     lambda u: _read_doc(u, hosts), list_words(list_text),
                                     today, PIECES_MAX - len(pieces), budget.left, source=feed)
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
    Path(a.out).write_text(json.dumps(out, indent=1), encoding="utf-8")
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a") as f:
            f.write(f"pieces={len(pieces)}\n")


if __name__ == "__main__":
    main()
