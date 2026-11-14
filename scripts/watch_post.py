"""Open the watcher's issues in Kitden and save its memory."""

import argparse
import json
from datetime import date, timedelta
from pathlib import Path

from bot_issues import GhIssues, ensure_labels, pause
from watch_route import (
    VERSION_MAX,
    BadFindings,
    Plan,
    _kind,
    _quiet,
    check,
    client_name,
    labels,
    route,
    word_hits,
)

SUMMARY_MAX = 60000
AGENT = "The client watcher"  # its pause issue is "The client watcher is paused"
PAUSED_MEANS = ("That includes its weekly summary: what it finds is kept for its first summary "
                "after this issue is closed.")


# Plain words for the type and severity of docs/watch-effects.md.
WHAT = {
    "breaks": "A Kitden action fails.",
    "wrong-data": "Kitden shows wrong information.",
    "gap": "Kitden does not show this yet.",
    "unknown": "Kitden cannot tell, and says so.",
    "outdated": "Only Kitden's own notes are out of date.",
}
RISK = {"major": "High", "medium": "Medium", "minor": "Low"}
HOW_IT_WORKS = "https://github.com/KonstantinStarovoytov/kitden-sdlc/blob/main/docs/agents.md"
LANTERN = ("https://raw.githubusercontent.com/KonstantinStarovoytov/kitden-sdlc/main/"
           "docs/images/apps/lantern.svg")
NEXT = ("**Next:** add `confirmed` if this is right (it stays open until it is fixed), or close "
        "it with `false-alarm`. Add `good first issue` or `help wanted` only after `confirmed`.")
NEXT_SUMMARY = ("**Next:** nothing here is urgent. To act on an item, open an issue for it; this "
                "summary is only a list.")

# What a fix must not forget, from Kitden's CONTRIBUTING.md, by the type of the finding.
CHECKS = {
    "docs": "Read the client's own docs first: the note may not say enough.",
    "new-row": "If Kitden should show it, add a row to `docs/clients.md`.",
    "test": "Test with a sandbox home, never your own settings.",
    "apply": "A change to a client's settings goes through preview → Apply with a backup → "
             "verify → Undo.",
    "privacy": "Update `PRIVACY.md` if Kitden now reads a new file or folder.",
    "row": "Update the row in `docs/clients.md` and its checked date.",
    "roadmap": 'Add a line to `ROADMAP.md` under "Not yet released".',
    "guide": "Update `docs/guide.md` if what the user sees changes.",
}
TODO = {
    "breaks": ("test", "apply", "row", "roadmap", "guide"),
    "wrong-data": ("test", "row", "roadmap", "guide"),
    "gap": ("new-row", "test", "privacy", "roadmap", "guide"),
    "unknown": ("docs", "row"),
    "outdated": ("row",),
}


def first_line() -> str:
    """Which bot opened it. The label `automated` says it is automated; the run log names the
    model."""
    return (f'<img src="{LANTERN}" width="18" height="18" align="top" alt=""> '
            f"Opened by **Lantern**, Kitden's [client watcher]({HOW_IT_WORKS})")


def dont_forget(effects: list[str], boxes: bool = True) -> str:
    """The checks a fix needs, once each, in the order of CHECKS."""
    keys = {k for e in effects for k in TODO.get(e, ())}
    mark = "- [ ] " if boxes else "- "
    return "\n".join(mark + text for k, text in CHECKS.items() if k in keys)


def _version(item: dict) -> str:
    return _quiet(item.get("version") or "", VERSION_MAX)


def _hint(item: dict) -> bool:
    """A word of a row is in the note but the model found nothing: not a finding."""
    return bool(item.get("hint")) or item.get("title", "").startswith("Mentions `")


def _who(item: dict) -> str:
    return " ".join(x for x in (client_name(item), _version(item)) if x)


def _versions(item: dict, inp: dict) -> str:
    files = item.get("files") or []
    same = bool(files) and all(inp["files"].get(f, {}).get("same_in_release") for f in files)
    kitden = f"main and {inp['release']}" if same else f"main ({inp['release']} not checked)"
    systems = item.get("systems") or ""
    on = f" · systems: {systems}" if systems and systems != "not checked" else ""
    return f"Checked on Kitden {kitden}{on}"


def _foot(item: dict, inp: dict) -> str:
    """The small print: what was checked and the source."""
    source = f" · [source]({item['url']})" if item.get("url") else ""
    return f"<sub>{_versions(item, inp)}{source}</sub>"


def _item(item: dict, inp: dict, who: bool = False) -> str:
    """One finding: risk first, then what changed, what it means, why, how to fix, where.
    `who` is for an issue of its own: the client and its version go before the change, where
    no heading says them, and the issue puts the small print at its end."""
    effect, severity = _kind(item)
    gets = item.get("user_gets", "")
    gets = "" if gets.strip(" .").lower() in ("", "not checked") else " " + gets
    files = item.get("files") or []
    lines = [
        f"**Risk: {RISK.get(severity, severity)}** · "
        f"**Sure: {'yes' if item.get('sure') else 'no'}**",
        "",
        f"**What changed:** {_who(item) + ': ' if who else ''}{item.get('changed', '')}",
        f"**What it means:** {WHAT.get(effect, effect)}{gets}",
    ]
    if item.get("why"):
        lines.append(f"**Why:** {item['why']}")
    if item.get("fix"):
        lines.append(f"**How to fix:** {item['fix']}")
    if files:
        lines.append("**Where:** " + ", ".join(f"`{f}`" for f in files))
    if not who:
        lines += ["", _foot(item, inp)]
    return "\n".join(lines)  # GitHub shows each line of an issue on its own line


def render_urgent(finding: dict, inp: dict) -> tuple[str, str]:
    # The title form is what the router matches known issues by: keep it.
    title = f"{client_name(finding)}: {finding['title']}"
    body = f"{first_line()}\n\n**Urgent** · {_item(finding, inp, who=True)}"
    todo = dont_forget([_kind(finding)[0]])
    if todo:
        body += f"\n\n**Don't forget:**\n{todo}"
    body += f"\n\n{_foot(finding, inp)}"
    return title, f"{body}\n\n{NEXT}\n"


def _hints(items: list[dict]) -> str:
    by_piece: dict[str, list[str]] = {}
    for i in items:
        word = i["title"].removeprefix("Mentions ").strip()
        by_piece.setdefault(_who(i) or "a note", []).append(word)
    parts = [f"{who} mentions {', '.join(words)}" for who, words in by_piece.items()]
    return ("**Mentioned, nothing found:** " + "; ".join(parts) + ". The model checked these "
            "rows and saw no change; look only if you want to.")


def render_summary(items: list[dict], today: date,
                   inp: dict | None = None) -> tuple[str, str, list[dict]]:
    """Return the title, the body and the items that did not fit, for the next summary."""
    inp = inp or {"files": {}, "release": "the latest release"}
    monday = today - timedelta(days=today.weekday())
    real = [i for i in items if not _hint(i)]
    hints = [i for i in items if _hint(i)]
    body = first_line()
    if len(real) > 1:
        rows = [f"| {n} | {_who(i)}: {_quiet(i['title'], 80)} | {RISK.get(_kind(i)[1], '')} | "
                f"{'yes' if i.get('sure') else 'no'} |" for n, i in enumerate(real, 1)]
        body += "\n\n| # | Change | Risk | Sure |\n|---|---|---|---|\n" + "\n".join(rows)
    rest = []
    for n, i in enumerate(real, 1):
        block = f"### {n}. {_who(i)}: {i['title']}\n\n{_item(i, inp)}"
        if len(body) + len(block) + 400 > SUMMARY_MAX:
            body += f"\n\n…and {len(real) - n + 1} more items in the next summary"
            rest = real[n - 1:]
            break
        body += "\n\n" + block
    if hints:
        body += "\n\n" + _hints(hints)
    todo = dont_forget([_kind(i)[0] for i in real if i not in rest], boxes=False)
    if todo:
        body += f"\n\n**When you fix one, don't forget:**\n{todo}"
    body += "\n\n" + NEXT_SUMMARY
    return f"Client changes, week of {monday}", body + "\n", rest


def _append(path: Path, lines: list[dict]) -> None:
    with path.open("a", encoding="utf-8") as f:
        f.writelines(json.dumps(x) + "\n" for x in lines)


def _hold(plan: Plan) -> Plan:
    """The plan of a paused day: nothing posted, every finding kept for the next summary, and
    no urgent issue counted against the week's cap."""
    state = plan.state
    state["kept"] = plan.urgent + (plan.summary or []) + state["kept"]
    state["urgent"]["count"] -= len(plan.urgent)
    if plan.summary:
        state.pop("summary_week", None)  # the summary is still due once the pause is lifted
    return Plan([], None, state)


def run(inp: dict, findings: dict | None, gh: GhIssues, memory: Path, today: date) -> None:
    try:
        found = [] if findings is None else check(findings, inp)
        judged, failed = ([], []) if findings is None else (findings["judged"], findings["failed"])
    except BadFindings as error:
        print(f"Bad findings, nothing posted: {error}")
        raise SystemExit(1) from error
    found += word_hits(found, judged, inp)
    plan = route(found, inp["state"], judged, inp, today, failed)
    ensure_labels(gh)
    paused = pause(gh, AGENT, "client-change", PAUSED_MEANS)
    if paused:
        plan = _hold(plan)
        kept = len(plan.state["kept"])
        print(f"{AGENT} is paused: nothing posted, {kept} finding{'' if kept == 1 else 's'} "
              "kept for its first summary after the pause.")

    posts = [(*render_urgent(f, inp), labels(f)) for f in plan.urgent]
    if plan.summary:
        title, body, rest = render_summary(plan.summary, today, inp)
        posts.append((title, body, ["automated", "client-change", "summary"]))
        plan.state["kept"] = rest + plan.state["kept"]
    addresses = [gh.create(*post) for post in posts]
    opened = {f["title"]: address for f, address in zip(plan.urgent, addresses, strict=False)}

    memory.mkdir(parents=True, exist_ok=True)
    (memory / "state.json").write_text(json.dumps(plan.state, indent=2) + "\n", encoding="utf-8")
    log = {"date": str(today), "pieces": len(inp["pieces"]), "judged": len(judged),
           "failed": len(failed),
           "findings": len(found), "urgent": len(plan.urgent), "summary": len(plan.summary or []),
           "paused": paused}
    _append(memory / "log.jsonl", [log])
    archive = [{"date": str(today), **{k: f[k] for k in
               ("piece", "client", "version", "url", "row", "title", "effect", "severity",
                "sure", "why")},
               "issue": opened.get(f["title"], ""), "kitden": inp.get("kitden", "")}
               for f in found]
    for p in inp["pieces"]:
        if p["id"] in judged and not any(f["piece"] == p["id"] for f in found):
            archive.append({"date": str(today), "piece": p["id"], "client": p["client"],
                            "version": p["version"], "url": p["url"], "row": "", "title": "",
                            "effect": "none", "severity": "", "sure": False, "why": "",
                            "issue": "", "kitden": inp.get("kitden", "")})
    _append(memory / "archive.jsonl", archive)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--findings", type=Path)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--memory", type=Path, required=True)
    parser.add_argument("--today", type=date.fromisoformat, required=True)
    a = parser.parse_args()
    inp = json.loads(a.input.read_text(encoding="utf-8"))
    findings = json.loads(a.findings.read_text(encoding="utf-8")) if a.findings else None
    run(inp, findings, GhIssues(a.repo), a.memory, a.today)


if __name__ == "__main__":
    main()
