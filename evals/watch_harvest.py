"""Turn judged watcher issues into new watch tasks.

Usage: watch_harvest.py --repo OWNER/kitden --archive <archive.jsonl> --tasks evals/watch/tasks
                        [--sources config/watch-sources.yml]

Run by hand about once a month, on a branch; the new tasks reach main as a pull request. It
reads the `client-change` issues, open and closed, with `gh`, joins each to its line of the
watcher's archive, fetches the piece again by its source (a config id or a doc address) and key,
and writes <tasks>/issue-<n>/task.json.
An issue with a verdict, `confirmed` or `false-alarm`, becomes a task, open or closed. Summary
issues are not harvested.
"""

import argparse
import json
import subprocess  # noqa: S404
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from watch_fetch import PIECE_CHARS, _read  # noqa: E402
from watch_pages import get, load_sources, sections  # noqa: E402

GRAVE_AND_MINOR = ("breaks", "wrong-data", "unknown", "outdated", "gap")
# Archive lines older than docs/watch-effects.md say "minor" and have no severity.
OLD = {"minor": "outdated"}


def _skip(issue: dict, why: str) -> dict:
    return {"issue": issue["number"], "why": why}


def _task(issue: dict, line: dict, piece: dict, kind: str) -> dict:
    if kind == "untouched":
        expect = {"row": None, "effect": None, "severity": None}
    else:
        expect = {"row": line["row"] or "gap", "effect": OLD.get(line["effect"], line["effect"]),
                  "severity": line.get("severity") or "minor"}
    return {"id": f"issue-{issue['number']}", "kind": kind, "source": piece["source"],
            "piece": piece, "expect": expect, "kitden": line["kitden"]}


def harvest(issues: list[dict], archive: list[dict], pieces: dict[str, dict],
            existing: frozenset | set = frozenset()) -> tuple[list[dict], list[dict]]:
    """Return (new tasks, skipped). A skipped item is {"issue": number, "why": reason}.

    issues: {"number", "address", "labels": [names]} for each client-change issue, open or closed.
    archive: the watcher's archive lines; an issue is joined to its line by `issue` == address.
    pieces: the piece of each archive line, by the line's `piece` id.
    existing: task ids that already exist; those are skipped, not made again.
    """
    tasks, skipped = [], []
    for issue in issues:
        marks = {"confirmed", "false-alarm"} & set(issue["labels"])
        line = next((x for x in archive if x.get("issue") == issue["address"]), None)
        if len(marks) == 2:
            skipped.append(_skip(issue, "both confirmed and false-alarm"))
        elif not marks:
            skipped.append(_skip(issue, "neither confirmed nor false-alarm"))
        elif f"issue-{issue['number']}" in existing:
            skipped.append(_skip(issue, "the task exists"))
        elif line is None:
            skipped.append(_skip(issue, "no archive line"))
        elif not line.get("kitden"):
            skipped.append(_skip(issue, "the archive line has no Kitden commit"))
        elif line["piece"] not in pieces:
            skipped.append(_skip(issue, "the piece could not be fetched again"))
        elif marks == {"confirmed"} and OLD.get(effect := line.get("effect"), effect) not in \
                GRAVE_AND_MINOR:
            skipped.append(_skip(issue, "the archive line has no effect"))
        else:
            kind = "touched" if marks == {"confirmed"} else "untouched"
            tasks.append(_task(issue, line, pieces[line["piece"]], kind))
    return tasks, skipped


def _issues(repo: str) -> list[dict]:
    done = subprocess.run(  # noqa: S603
        ["gh", "api", "--paginate",  # noqa: S607
         f"repos/{repo}/issues?labels=client-change&state=all&per_page=100",
         "--jq", ".[] | select(.pull_request | not) | "
                 "{number, address: .html_url, labels: [.labels[].name]}"],
        check=True, capture_output=True, text=True)
    return [json.loads(line) for line in done.stdout.splitlines() if line.strip()]


def _judged(issues: list[dict]) -> list[dict]:
    """The issues with exactly one verdict label; only these need their piece fetched."""
    return [i for i in issues if len({"confirmed", "false-alarm"} & set(i["labels"])) == 1]


def _fetch_pieces(archive: list[dict], sources_file) -> dict[str, dict]:
    sources = {s["id"]: s for s in load_sources(sources_file)}
    read, pieces = {}, {}
    for line in archive:
        sid, _, key = line["piece"].partition("#")
        doc = sid.startswith("https://")
        if line["piece"] in pieces or not (doc or sid in sources):
            continue
        if sid not in read:
            try:
                read[sid] = sections(*get(sid)) if doc else _read(sources[sid])
            except Exception:  # noqa: BLE001 - one unreadable source skips its issues only
                read[sid] = []
        if doc:
            client, kind, version, url = line["client"], "doc", "", sid
        else:
            src = sources[sid]
            client, kind, version = src["client"], "release", key
            url = src.get("url") or f"https://github.com/{src['repo']}/releases"
        for s in read[sid]:
            if s.key == key:
                pieces[line["piece"]] = {
                    "id": line["piece"], "client": client, "kind": kind, "version": version,
                    "url": url, "text": s.text[:PIECE_CHARS], "source": sid, "key": key,
                    "hash": s.hash}
    return pieces


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--repo", required=True)
    ap.add_argument("--archive", required=True)
    ap.add_argument("--tasks", required=True)
    ap.add_argument("--sources", default="config/watch-sources.yml")
    a = ap.parse_args()
    issues = _issues(a.repo)
    archive = [json.loads(x) for x in Path(a.archive).read_text(encoding="utf-8").splitlines()
               if x.strip()]
    addresses = {i["address"] for i in _judged(issues)}
    pieces = _fetch_pieces([x for x in archive if x.get("issue") in addresses], a.sources)
    folder = Path(a.tasks)
    existing = {p.name for p in folder.glob("*") if p.is_dir()}
    tasks, skipped = harvest(issues, archive, pieces, existing)
    for task in tasks:
        (folder / task["id"]).mkdir(parents=True, exist_ok=True)
        (folder / task["id"] / "task.json").write_text(
            json.dumps(task, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"made {len(tasks)} tasks: {', '.join(t['id'] for t in tasks) or 'none'}")
    for s in skipped:
        print(f"skipped issue {s['issue']}: {s['why']}")


if __name__ == "__main__":
    main()
