"""Fetch what is new in the watched sources and write the input for the judge."""

import argparse
import copy
import json
import os
import subprocess  # noqa: S404
import sys
from pathlib import Path

from watch_list import doc_pages, parse_list
from watch_pages import get, load_sources, releases, sections

PIECES_MAX = 20
PIECE_CHARS = 12000
FAIL_DAYS = 3


def _unreadable(meta: dict, source: str) -> dict:
    return {
        "effect": "minor", "sure": True, "title": f"Cannot read {source} for {FAIL_DAYS} days",
        "client": meta["client"], "changed": f"{source} could not be read",
        "why": "The watcher cannot see new changes from this source.",
        "user_gets": "Nothing yet.", "systems": "", "row": "", "files": [],
        "version": "", "url": meta["url"],
    }


def plan_run(state, fetched, meta):
    new = copy.deepcopy(state) if state else {}
    new.setdefault("sources", {})
    new.setdefault("fails", {})
    new.setdefault("kept", [])
    new.setdefault("urgent", {"week": "", "count": 0})
    new.setdefault("summary_week", "")
    new.setdefault("tries", {})
    known = state["sources"] if state else {}
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


def _fetch(sid, reader, address):
    try:
        return reader(address)
    except Exception as e:  # noqa: BLE001 - one unreadable source must not stop the run
        print(f"cannot read {sid}: {type(e).__name__}", file=sys.stderr)
        return None


def main():
    ap = argparse.ArgumentParser()
    for name in ("sources", "kitden", "state", "titles", "out"):
        ap.add_argument(f"--{name}", required=True)
    a = ap.parse_args()
    state = json.loads(Path(a.state).read_text()) if Path(a.state).is_file() else None
    list_text = (Path(a.kitden) / "docs/clients.md").read_text(encoding="utf-8")
    rows = parse_list(list_text)
    fetched, meta = {}, {}
    for src in load_sources(a.sources):
        meta[src["id"]] = {"client": src["client"], "kind": "release",
                           "url": src.get("url") or f"https://github.com/{src['repo']}/releases"}
        fetched[src["id"]] = _fetch(src["id"], _read, src)
    for address, client in doc_pages(rows).items():
        meta[address] = {"client": client, "kind": "doc", "url": address}
        fetched[address] = _fetch(address, lambda u: sections(*get(u)), address)
    pieces, new_state = plan_run(state, fetched, meta)
    release = _git(a.kitden, "describe", "--tags", "--abbrev=0").stdout.strip()
    names = sorted({f for r in rows for f in r.files})

    def same(name):
        return _git(a.kitden, "diff", "--quiet", release, "HEAD", "--", name).returncode == 0

    titles = json.loads(Path(a.titles).read_text())
    out = build_input(pieces, a.kitden, list_text, names, same, release, titles,
                      new_state)
    Path(a.out).write_text(json.dumps(out, indent=1), encoding="utf-8")
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a") as f:
            f.write(f"pieces={len(pieces)}\n")


if __name__ == "__main__":
    main()
