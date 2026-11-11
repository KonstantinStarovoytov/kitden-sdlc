"""Check the judge's findings and decide which are urgent and which wait for Monday."""

import copy
import re
from dataclasses import dataclass
from datetime import date

from post_findings import MENTION, SECRET_LIKE, WORD_JOINER
from watch_list import _table_rows, terms  # noqa: PLC2701

URGENT_PER_WEEK = 2
WORD_HITS_MAX = 5
TITLE_MAX = 100
TEXT_MAX = 600
EFFECTS = ("breaks", "wrong-data", "minor", "gap")
STRINGS = ("piece", "client", "title", "changed", "version", "url", "row", "effect",
           "user_gets", "systems", "why")
CUT = ("title", "changed", "row", "user_gets", "systems", "why")
KEYS = {*STRINGS, "files", "sure"}


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
    _need(isinstance(findings, dict) and set(findings) == {"judged", "findings"}, "top level")
    judged, items = findings["judged"], findings["findings"]
    _need(isinstance(judged, list) and isinstance(items, list), "judged and findings are lists")
    pieces = {p["id"]: p for p in inp["pieces"]}
    _need(all(isinstance(j, str) and j in pieces for j in judged), "judged piece not fetched")
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
        _need(item["url"] == src["url"] and item["client"] == src["client"], "url or client")
        _need(all(f in inp["files"] for f in item["files"]), "file not in input")
        texts = [item[k] for k in STRINGS] + item["files"]
        _need(not any(SECRET_LIKE.search(t) for t in texts), "secret-like text")
        clean = dict(item)
        for k in CUT:
            quiet = MENTION.sub("@" + WORD_JOINER, item[k])
            clean[k] = quiet[: TITLE_MAX if k == "title" else TEXT_MAX]
        out.append(clean)
    return out


def _grade(f: dict) -> int:
    if f.get("overflow"):
        return 0
    if f["effect"] in ("breaks", "wrong-data") and not f["sure"]:
        return 1
    return 2 + ("breaks", "wrong-data", "gap", "minor").index(f["effect"])


def route(findings: list[dict], state: dict, judged: list[str], inp: dict, today: date) -> Plan:
    new = copy.deepcopy(state)
    year, week, weekday = today.isocalendar()
    this_week = f"{year}-W{week:02d}"
    if new["urgent"]["week"] != this_week:
        new["urgent"] = {"week": this_week, "count": 0}
    titles = set(inp["known_titles"]) | {k["title"] for k in new["kept"]}
    urgent = []
    for f in copy.deepcopy(findings):
        if f["title"] in titles:
            continue
        titles.add(f["title"])
        if f["effect"] in ("breaks", "wrong-data") and f["sure"]:
            if new["urgent"]["count"] < URGENT_PER_WEEK:
                new["urgent"]["count"] += 1
                urgent.append(f)
                continue
            f["overflow"] = True
        new["kept"].append(f)
    for piece in inp["pieces"]:
        if piece["id"] in judged:
            new["sources"].setdefault(piece["source"], {})[piece["key"]] = piece["hash"]
    summary = None
    if weekday == 1 and new["kept"]:
        summary = sorted(new["kept"], key=_grade)
        new["kept"] = []
    return Plan(urgent, summary, new)


def labels(finding: dict) -> list[str]:
    effect = finding["effect"]
    out = ["client-change", finding["client"], "kitden-gap" if effect == "gap" else effect]
    return out + ([] if finding["sure"] else ["unsure"])


def word_hits(findings: list[dict], judged: list[str], inp: dict) -> list[dict]:
    words = terms(inp["list"])
    rows = list(_table_rows(inp["list"]))
    hits = []
    for piece in inp["pieces"]:
        if piece["id"] not in judged:
            continue
        named = {f["row"] for f in findings if f["piece"] == piece["id"]}
        for client, cells in rows:
            if client != piece["client"] or cells[0] in named:
                continue
            word = next((w for w in words[(client, cells[0].replace("`", ""))]
                         if w in piece["text"]), None)
            if word is None:
                continue
            line = next(x for x in piece["text"].splitlines() if word in x)
            hits.append({
                "piece": piece["id"], "client": client, "title": f"Mentions `{word}`",
                "changed": line[:TEXT_MAX], "version": piece["version"], "url": piece["url"],
                "row": cells[0], "files": re.findall(r"`([^`]+)`", cells[2]),
                "effect": "minor", "sure": False, "user_gets": "not checked",
                "systems": "not checked",
                "why": "The word is in the text; the model reported nothing for this row.",
            })
    return hits[:WORD_HITS_MAX]
