"""Check the judge's findings and decide which are urgent and which wait for the summary."""

import copy
from dataclasses import dataclass
from datetime import date

from post_findings import MENTION, SECRET_LIKE, WORD_JOINER
from watch_list import CLIENTS, _table_rows, parse_list, terms

URGENT_PER_WEEK = 2
WORD_HITS_MAX = 5
TRIES_MAX = 3
TITLE_MAX = 100
TEXT_MAX = 600
VERSION_MAX = 100
EFFECTS = ("breaks", "wrong-data", "minor", "gap")
STRINGS = ("piece", "client", "title", "changed", "version", "url", "row", "effect",
           "user_gets", "systems", "why")
CUT = ("title", "changed", "user_gets", "systems", "why")
KEYS = {*STRINGS, "files", "sure"}
NAMES = {v: k for k, v in CLIENTS.items()}


class BadFindings(Exception):
    pass


@dataclass
class Plan:
    urgent: list[dict]
    summary: list[dict] | None
    state: dict


def _need(ok: bool, why: str) -> None:
    if not ok:
        raise BadFindings(why)


def check(findings: dict, inp: dict) -> list[dict]:
    _need(isinstance(findings, dict) and set(findings) == {"judged", "findings", "failed"},
          "top level")
    judged, items, failed = findings["judged"], findings["findings"], findings["failed"]
    _need(all(isinstance(x, list) for x in (judged, items, failed)), "top level lists")
    pieces = {p["id"]: p for p in inp["pieces"]}
    _need(all(isinstance(j, str) and j in pieces for j in judged + failed),
          "judged or failed piece not fetched")
    _need(not set(judged) & set(failed), "piece both judged and failed")
    out = []
    for item in items:
        _need(isinstance(item, dict) and set(item) == KEYS, "finding keys")
        _need(all(isinstance(item[k], str) for k in STRINGS), "finding text types")
        _need(isinstance(item["sure"], bool), "sure must be true or false")
        _need(isinstance(item["files"], list) and all(isinstance(f, str) for f in item["files"]),
              "files must be a list of strings")
        _need(item["effect"] in EFFECTS, "unknown effect")
        _need(item["piece"] in judged and item["piece"] in pieces, "piece not judged")
        src = pieces[item["piece"]]
        _need(all(item[k] == src[k] for k in ("url", "client", "version")), "url, client, version")
        _need(all(f in inp["files"] for f in item["files"]), "file not in input")
        rows = {cells[0] for client, cells in _table_rows(inp["list"]) if client == src["client"]}
        _need(item["row"] in {"", *rows}, "row not in the list")
        texts = [item[k] for k in STRINGS] + item["files"]
        _need(not any(SECRET_LIKE.search(t) for t in texts), "secret-like text")
        clean = dict(item)
        for k in CUT:
            clean[k] = _quiet(item[k], TITLE_MAX if k == "title" else TEXT_MAX)
        out.append(clean)
    return out


def client_name(item: dict) -> str:
    return NAMES.get(item.get("client", ""), item.get("client") or "Unknown")


def _quiet(text: str, limit: int) -> str:
    return MENTION.sub("@" + WORD_JOINER, text)[:limit]


def _grade(f: dict) -> int:
    if f.get("overflow"):
        return 0
    if f["effect"] in ("breaks", "wrong-data") and not f["sure"]:
        return 1
    return 2 + ("breaks", "wrong-data", "gap", "minor").index(f["effect"])


def _not_judged(piece: dict) -> dict:
    return {"effect": "minor", "sure": False, "title": _quiet(f"Could not judge {piece['id']}",
                                                             TITLE_MAX),
            "client": piece["client"], "url": piece["url"], "version": piece["version"],
            "changed": f"The model failed on this piece {TRIES_MAX} times; it is now skipped.",
            "why": "Read the source by hand.", "user_gets": "not checked",
            "systems": "not checked", "row": "", "files": []}


def route(findings: list[dict], state: dict, judged: list[str], inp: dict, today: date,
          failed: list[str] = ()) -> Plan:
    new = copy.deepcopy(state)
    year, week, _ = today.isocalendar()
    this_week = f"{year}-W{week:02d}"
    if new["urgent"]["week"] != this_week:
        new["urgent"] = {"week": this_week, "count": 0}
    titles = set(inp["known_titles"]) | {k["title"] for k in new["kept"]}
    urgent, grave_rows = [], set()
    for f in copy.deepcopy(findings):
        if f["title"] in titles or f"{client_name(f)}: {f['title']}" in titles:
            continue
        titles.add(f["title"])
        if f["effect"] in ("breaks", "wrong-data") and f["sure"]:
            first = (f["client"], f["row"]) not in grave_rows
            grave_rows.add((f["client"], f["row"]))
            if first and new["urgent"]["count"] < URGENT_PER_WEEK:
                new["urgent"]["count"] += 1
                urgent.append(f)
                continue
            if first:
                f["overflow"] = True
        new["kept"].append(f)
    tries = new.setdefault("tries", {})
    for piece in inp["pieces"]:
        pid = piece["id"]
        if pid in failed:
            tries[pid] = tries.get(pid, 0) + 1
            if tries[pid] < TRIES_MAX:
                continue
            new["kept"].append(_not_judged(piece))
        elif pid not in judged:
            continue
        tries.pop(pid, None)
        new["sources"].setdefault(piece["source"], {})[piece["key"]] = piece["hash"]
    summary = None
    if new["kept"] and new.get("summary_week") != this_week:
        summary = sorted(new["kept"], key=_grade)
        new["kept"], new["summary_week"] = [], this_week
    return Plan(urgent, summary, new)


def labels(finding: dict) -> list[str]:
    effect = finding["effect"]
    out = ["client-change", finding["client"], "kitden-gap" if effect == "gap" else effect]
    return out + ([] if finding["sure"] else ["unsure"])


def word_hits(findings: list[dict], judged: list[str], inp: dict) -> list[dict]:
    words = terms(inp["list"])
    raw = {c.replace("`", ""): c for c in (
        line.strip("| ").split(" | ")[0] for line in inp["list"].splitlines() if "`" in line)}
    hits = []
    for piece in inp["pieces"]:
        if piece["id"] not in judged:
            continue
        named = {f["row"] for f in findings if f["piece"] == piece["id"]}
        for row in parse_list(inp["list"]):
            label = raw.get(row.what, row.what)
            if row.client != piece["client"] or label in named:
                continue
            word = next((w for w in words[(row.client, row.what)] if w in piece["text"]), None)
            if word is None:
                continue
            where = _quiet(piece["version"], VERSION_MAX) or "this page"
            hits.append({
                "piece": piece["id"], "client": row.client, "title": f"Mentions `{word}`",
                "changed": f"The text of {where} has the word `{word}`.",
                "version": piece["version"],
                "url": piece["url"], "row": label, "files": row.files,
                "effect": "minor", "sure": False, "user_gets": "not checked",
                "systems": "not checked",
                "why": "The word is in the text; the model reported nothing for this row.",
            })
    return hits[:WORD_HITS_MAX]
