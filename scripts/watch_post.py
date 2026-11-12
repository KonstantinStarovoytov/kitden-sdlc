"""Open the watcher's issues in Kitden and save its memory."""

import argparse
import json
import os
import subprocess  # noqa: S404
from datetime import date, timedelta
from pathlib import Path
from typing import Protocol

import yaml

from watch_list import parse_list, row_labels
from watch_route import (
    TEXT_MAX,
    VERSION_MAX,
    BadFindings,
    _kind,
    _quiet,
    check,
    client_name,
    labels,
    route,
    word_hits,
)

SUMMARY_MAX = 60000
LABELS_FILE = Path(__file__).resolve().parent.parent / "config" / "watch-labels.yml"


class GitHub(Protocol):
    def label_names(self) -> set[str]: ...

    def create_label(self, name: str, color: str, description: str) -> None: ...

    def create_issue(self, title: str, body: str, labels: list[str]) -> str: ...


class GhApi:
    """The GitHub on top of the gh command line tool."""

    def __init__(self, repo: str):
        self.repo = repo

    def _run(self, *args: str) -> str:
        done = subprocess.run(  # noqa: S603
            ["gh", "api", *args],  # noqa: S607
            check=True, capture_output=True, text=True,
        )
        return done.stdout

    def label_names(self) -> set[str]:
        text = self._run(f"repos/{self.repo}/labels?per_page=100", "--paginate", "--jq", ".[].name")
        return set(text.split("\n")) - {""}

    def create_label(self, name: str, color: str, description: str) -> None:
        self._run(f"repos/{self.repo}/labels", "--method", "POST", "-f", f"name={name}",
                  "-f", f"color={color}", "-f", f"description={description}")

    def create_issue(self, title: str, body: str, labels: list[str]) -> str:
        args = [f"repos/{self.repo}/issues", "--method", "POST", "-f", f"title={title}",
                "-f", f"body={body}", "--jq", ".html_url"]
        for name in labels:
            args += ["-f", f"labels[]={name}"]
        return self._run(*args).strip()


# Shown with every finding: docs/watch-effects.md says the same in more words.
TYPE_TEXT = {
    "breaks": ("Breaks",
               "A Kitden action fails, or writes something the client no longer accepts."),
    "wrong-data": ("Wrong data", "Kitden shows one thing while the client has another."),
    "unknown": ("Unknown", "Kitden cannot read the new value and says so."),
    "outdated": ("Outdated", "Kitden stays right; its list or a code comment is out of date."),
    "gap": ("Gap", "The client keeps something that Kitden does not show yet."),
}
SEVERITY_TEXT = {
    "major": "A user who trusts Kitden here does a wrong action and gets a result they did not "
             "expect.",
    "medium": "A user does extra or useless steps, but nothing unexpected happens.",
    "minor": "What a user does stays the same.",
}
MAINTAINERS_SUMMARY = ("To confirm an item or mark it a false alarm, open an issue for it; this "
                       "summary is only a list.")
HOW_IT_WORKS = "https://github.com/KonstantinStarovoytov/kitden-sdlc/blob/main/docs/agents.md"
MAINTAINERS = ("Close it with `confirmed` if this is right, or `false-alarm` if it is not. Add "
               "`good first issue` or `help wanted` only after it is confirmed.")


def first_line(repo: str = "") -> str:
    """The first line of every issue: who opened it, which model wrote it, what happens next."""
    model = os.environ.get("WATCH_MODEL") or "a model"
    policy = f" ([AI policy](https://github.com/{repo}/blob/main/AI_POLICY.md))" if repo else ""
    return (f"Opened by Kitden's [client watcher]({HOW_IT_WORKS}), an automated check of the "
            f"release notes and docs of Claude Code, Codex and Cursor. Written by {model}; a "
            f"maintainer checks it before anyone works on it{policy}.")


def _version(item: dict) -> str:
    return _quiet(item.get("version") or "", VERSION_MAX)


def _seen_in(item: dict, inp: dict) -> str:
    text = inp.get("list", "")
    labels = row_labels(text)
    for r in parse_list(text):
        if (r.client, labels[(r.client, r.what)]) == (item.get("client"), item.get("row")):
            return f"seen in {r.seen_in}"
    return ""


def _scale(item: dict, inp: dict) -> str:
    files = item.get("files") or []
    same = bool(files) and all(inp["files"].get(f, {}).get("same_in_release") for f in files)
    kitden = f"main and {inp['release']}" if same else f"main; {inp['release']} not checked"
    return (f"- Client versions: {_version(item) or 'unknown'}\n"
            f"- Systems: {item.get('systems') or 'not checked'}\n- Kitden versions: {kitden}")


def _where(item: dict, inp: dict) -> str:
    row = _quiet(item.get("row") or "", TEXT_MAX)
    lines = []
    if row:
        seen = _seen_in(item, inp)
        lines.append(f"- Row in `docs/clients.md`: {row}" + (f" ({seen})" if seen else ""))
    else:
        lines.append("- No row in `docs/clients.md` is about it.")
    files = item.get("files") or []
    if files:
        lines.append("- Files: " + ", ".join(f"`{f}`" for f in files))
    return "\n".join(lines)


def _item(item: dict, inp: dict, level: str = "##") -> str:
    """One finding in sections, the same in an urgent issue and in the summary."""
    effect, severity = _kind(item)
    name, means = TYPE_TEXT.get(effect, (effect, ""))
    who = " ".join(x for x in (client_name(item), _version(item)) if x)
    source = f"\n\nSource: {item['url']}" if item.get("url") else ""
    sure = ("Sure: the note says it plainly and the code shows it." if item.get("sure")
            else "Not sure: the note or the code leaves room for doubt; check before acting.")
    return "\n\n".join([
        f"{level} What changed\n\n{who}: {item.get('changed', '')}{source}",
        f"{level} What it means for Kitden\n\n**{name}, {severity}.** {means} "
        f"{SEVERITY_TEXT.get(severity, '')}\n\n{item.get('user_gets', '')}".rstrip(),
        f"{level} Why\n\n{item.get('why', '')}".rstrip(),
        f"{level} Where in Kitden\n\n{_where(item, inp)}",
        f"{level} Scale\n\n{_scale(item, inp)}",
        f"{level} How sure\n\n{sure}",
    ])


def render_urgent(finding: dict, inp: dict, repo: str = "") -> tuple[str, str]:
    title = f"{client_name(finding)}: {finding['title']}"
    return title, (f"{first_line(repo)}\n\n{_item(finding, inp)}\n\n"
                   f"## For maintainers\n\n{MAINTAINERS}\n")


def render_summary(items: list[dict], today: date, inp: dict | None = None,
                   repo: str = "") -> tuple[str, str, list[dict]]:
    """Return the title, the body and the items that did not fit, for the next summary."""
    inp = inp or {"files": {}, "release": "the latest release"}
    monday = today - timedelta(days=today.weekday())
    blocks = [f"## {i['title']}\n\n`{'` `'.join(labels(i))}`\n\n{_item(i, inp, '###')}"
              for i in items]
    body = (f"{first_line(repo)}\n\nThe changes of this week that are not urgent, the gravest "
            f"first. {MAINTAINERS_SUMMARY}")
    rest = []
    for n, block in enumerate(blocks):
        if len(body) + len(block) + 100 > SUMMARY_MAX:
            body += f"\n\n…and {len(blocks) - n} more items in the next summary"
            rest = items[n:]
            break
        body += "\n\n" + block
    return f"Client changes, week of {monday}", body + "\n", rest


def _append(path: Path, lines: list[dict]) -> None:
    with path.open("a", encoding="utf-8") as f:
        f.writelines(json.dumps(x) + "\n" for x in lines)


def run(inp: dict, findings: dict | None, gh: GitHub, memory: Path, today: date) -> None:
    try:
        found = [] if findings is None else check(findings, inp)
        judged, failed = ([], []) if findings is None else (findings["judged"], findings["failed"])
    except BadFindings as error:
        print(f"Bad findings, nothing posted: {error}")
        raise SystemExit(1) from error
    found += word_hits(found, judged, inp)
    plan = route(found, inp["state"], judged, inp, today, failed)

    repo = getattr(gh, "repo", "")
    posts = [(*render_urgent(f, inp, repo), labels(f)) for f in plan.urgent]
    if plan.summary:
        title, body, rest = render_summary(plan.summary, today, inp, repo)
        posts.append((title, body, ["automated", "client-change", "summary"]))
        plan.state["kept"] = rest + plan.state["kept"]
    have = gh.label_names()
    for entry in yaml.safe_load(LABELS_FILE.read_text()):
        if entry["name"] not in have:
            gh.create_label(entry["name"], entry["color"], entry["description"])
    addresses = [gh.create_issue(*post) for post in posts]
    opened = {f["title"]: address for f, address in zip(plan.urgent, addresses, strict=False)}

    memory.mkdir(parents=True, exist_ok=True)
    (memory / "state.json").write_text(json.dumps(plan.state, indent=2) + "\n", encoding="utf-8")
    log = {"date": str(today), "pieces": len(inp["pieces"]), "judged": len(judged),
           "failed": len(failed),
           "findings": len(found), "urgent": len(plan.urgent), "summary": len(plan.summary or [])}
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
    run(inp, findings, GhApi(a.repo), a.memory, a.today)


if __name__ == "__main__":
    main()
