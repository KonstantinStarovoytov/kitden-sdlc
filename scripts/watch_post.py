"""Open the watcher's issues in Kitden and save its memory."""

import argparse
import json
import os
import subprocess  # noqa: S404
from datetime import date, timedelta
from pathlib import Path
from typing import Protocol

import yaml

from watch_list import _table_rows
from watch_route import (
    TEXT_MAX,
    VERSION_MAX,
    BadFindings,
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


def first_line() -> str:
    model = os.environ.get("WATCH_MODEL") or "gpt-6-luna"
    return f"Automated issue by Kitden's client watcher ({model})."


def _version(item: dict) -> str:
    return _quiet(item.get("version") or "", VERSION_MAX)


def _seen_in(item: dict, inp: dict) -> str:
    return next((f"seen in {cells[3]}" for client, cells in _table_rows(inp.get("list", ""))
                 if client == item.get("client") and cells[0] == item.get("row")), "")


def _scale(item: dict, inp: dict) -> str:
    files = item.get("files") or []
    same = bool(files) and all(inp["files"].get(f, {}).get("same_in_release") for f in files)
    kitden = f"main and {inp['release']}" if same else f"main; {inp['release']} not checked"
    return (f"- Client versions: {_version(item) or 'unknown'}\n"
            f"- Systems: {item.get('systems') or 'not checked'}\n- Kitden versions: {kitden}")


def _item(item: dict, inp: dict) -> str:
    row = _quiet(item.get("row") or "", TEXT_MAX)
    touches = ", ".join(x for x in [row, _seen_in(item, inp), *(item.get("files") or [])] if x)
    return "\n\n".join([
        f"**What changed**\n{client_name(item)} {_version(item)}: "
        f"{item.get('changed', '')}\n{item.get('url', '')}".replace("  ", " "),
        f"**What it touches**\n{touches or 'not checked'}",
        f"**What the user gets**\n{item.get('user_gets', '')}",
        f"**Scale**\n{_scale(item, inp)}",
        f"**How sure**\n{'Sure' if item.get('sure') else 'Not sure'}. {item.get('why', '')}",
    ])


def render_urgent(finding: dict, inp: dict) -> tuple[str, str]:
    title = f"{client_name(finding)}: {finding['title']}"
    return title, f"{first_line()}\n\n{_item(finding, inp)}\n"


def render_summary(items: list[dict], today: date, inp: dict | None = None) -> tuple[str, str]:
    inp = inp or {"files": {}, "release": "the latest release"}
    monday = today - timedelta(days=today.weekday())
    blocks = [f"### {i['title']}\n\n`{'` `'.join(labels(i))}`\n\n{_item(i, inp)}" for i in items]
    body = first_line()
    for n, block in enumerate(blocks):
        if len(body) + len(block) + 100 > SUMMARY_MAX:
            body += f"\n\n…and {len(blocks) - n} more items"
            break
        body += "\n\n" + block
    return f"Client changes, week of {monday}", body + "\n"


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

    posts = [(*render_urgent(f, inp), labels(f)) for f in plan.urgent]
    if plan.summary:
        posts.append((*render_summary(plan.summary, today, inp), ["client-change", "summary"]))
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
               ("piece", "client", "version", "url", "row", "title", "effect", "sure", "why")},
               "issue": opened.get(f["title"], "")} for f in found]
    for p in inp["pieces"]:
        if p["id"] in judged and not any(f["piece"] == p["id"] for f in found):
            archive.append({"date": str(today), "piece": p["id"], "client": p["client"],
                            "version": p["version"], "url": p["url"], "row": "", "title": "",
                            "effect": "none", "sure": False, "why": "", "issue": ""})
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
