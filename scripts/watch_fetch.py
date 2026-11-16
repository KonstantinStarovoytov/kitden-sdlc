"""Fetch what is new in the watched sources and write the input for the judge."""

import argparse
import copy
import json
import os
import subprocess  # noqa: S404
import sys
import time
from datetime import date
from pathlib import Path

from doc_address import load_hosts, location
from watch_list import doc_pages, parse_list
from watch_moved import manifest_addresses, moved
from watch_pages import get, get_doc, load_sources, releases, sections
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


def _out_of_time(client: str, address: str) -> dict:
    return {**_unreadable({"client": client, "url": address}, address),
            "title": f"{address} was not read for {FAIL_DAYS} days: out of time",
            "changed": f"{address} was not read: each run ran out of time before it"}


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
    whose read was started is dropped from it, and so is a page that left the list. On the
    third run in a row an item goes to `kept`, once, like the "Cannot read" one.
    """
    new = copy.deepcopy(state)
    order = page_order(state, pages)
    new["page_start"] = (_start(state, len(order)) + read) % len(order) if order else 0
    old = state.get("skips") if isinstance(state.get("skips"), dict) else {}
    titles = {k["title"] for k in new["kept"]}
    new["skips"] = {}
    for address in order[read:]:
        count = old.get(address, 0)
        new["skips"][address] = (count if type(count) is int else 0) + 1
        if new["skips"][address] != FAIL_DAYS:
            continue
        item = _out_of_time(pages[address], address)
        if item["title"] not in titles:
            titles.add(item["title"])
            new["kept"].append(item)
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
        if meta[sid]["kind"] == "manifest":  # read for the weekly moved check only
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
    manifests = []
    for src in load_sources(a.sources):
        if src["kind"] == "manifest":
            meta[src["id"]] = {"kind": "manifest", "url": src["url"]}
            fetched[src["id"]] = read_or_none(src["id"], read_manifest, src)
            manifests.append(fetched[src["id"]])
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
    if manifests:
        read = None if None in manifests else set().union(*manifests)
        new_state = plan_moved(new_state, read, pages, hosts,
                               lambda u: location(u, hosts), week_of(date.today()))
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
