"""Open one `ci-failure` issue in Kitden for each red nightly test part in desk.json, rewrite it
each day, and close it when the part is green. No model.

    desk_post.py --desk desk.json --repo OWNER/kitden [--dry-run]

The desk's own state is on the desk page (docs/desk), which reads desk.json; this script only
writes the issues that notify the owner of a red night. The bot (bot_issues.BOT) writes only its
own issues; an issue a person opened is never touched (see post_nightly). `--dry-run` prints the
issue of each red part and calls nothing.

Every job and step name goes through `_name`; only a github.com address becomes a link, and the
usage pages config/agents.json names, which only the owner changes.

Standard library only: it runs with `uv run --no-project`.
"""

import argparse
import functools
import json
import re
import sys
from pathlib import Path

import bot_style as style
from bot_issues import GhIssues, ensure_labels, upsert
from count_reviews import REPO
from post_findings import WORD_JOINER, one_line

ROSTER = Path(__file__).resolve().parent.parent / "config" / "agents.json"
GITHUB = re.compile(r"https://github\.com/[\w.~/#?=&%+-]*\Z")
USAGE = re.compile(r"https://[\w.-]+/[\w.~/#?=&%+-]*\Z")  # the same, on any https host
CI_LABELS = ["automated", "ci-failure"]
NO_NAME = "Nightly run"  # the title's workflow when the run gave no name and no file
SET_ASIDE = "https://github.com/{repo}/blob/main/tests/set-aside.txt"
# What a red part means, by part; any other part: MEANS_ELSE.
MEANS = {
    "systems": "Kitden may not work on that system or Python.",
    "clients": "The newest Claude Code or Codex writes or answers something Kitden's tests "
               "do not expect.",
    "browser": "A main flow of the page is broken in a real browser.",
}
MEANS_ELSE = "A scheduled test run failed."
# An address GitHub would make a link of by itself, in text: the scheme's "//", "www." or an
# email address. The joiner goes after the "@", as quiet_mentions puts it after one that starts
# a word: before it, the "@" would start a mention.
AUTOLINK = re.compile(r"(?<=[A-Za-z]:)(?=//)|(?<=\bwww)(?=\.)|(?<=\w@)", re.I)


class Safe(str):
    """Markdown this script wrote: a table cell shows it as it is."""


# --- Small pieces ---


def _number(value) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool)


def _figure(value) -> str:
    return f"{value:,}" if isinstance(value, int) else f"{value:g}"


def _n(value, one: str, many: str) -> str:
    return f"{_figure(value)} {one if value == 1 else many}"


def _link(text: str, url) -> str:
    """`text` (already safe) as a link when `url` is a github.com address, else as it is."""
    return f"[{text}]({url})" if isinstance(url, str) and GITHUB.match(url) else text


@functools.cache
def _usage_pages() -> frozenset[str]:
    """The usage pages the roster names; none when it cannot be read."""
    try:
        keys = json.loads(ROSTER.read_text())["keys"]
        return frozenset(key["dashboard"] for key in keys
                         if isinstance(key["dashboard"], str) and USAGE.match(key["dashboard"]))
    except (OSError, ValueError, KeyError, TypeError):
        return frozenset()


def _address(url) -> Safe:
    """An address: a link on github.com or when the roster names it, plain text in a code
    span anywhere else."""
    if not isinstance(url, str) or not url.strip():
        return Safe("not given")
    if GITHUB.match(url) or url in _usage_pages():
        return Safe(f"[{url}]({url})")
    return Safe("`" + re.sub(r"[`|\s]", "", url) + "`")


def _cell(value) -> str:
    if value is None:
        return "not measured"
    if isinstance(value, Safe):
        return value
    if _number(value):
        return _figure(value)
    if isinstance(value, list):
        value = ", ".join(str(item) for item in value)
    return one_line(str(value)) or "not given"


def _name(value) -> str:
    """A name from a run (a job, a step, a part) as `_cell` gives it, with a word joiner where
    GitHub would see an address, so the text is no link even after its entities are read."""
    return AUTOLINK.sub(WORD_JOINER, _cell(value if isinstance(value, str) else ""))


# --- The ci-failure issues ---


def _readable(row) -> bool:
    """A row that says which part it is and whether it is green or red."""
    return (isinstance(row, dict) and isinstance(row.get("part"), str)
            and bool(row["part"].strip()) and row.get("state") in ("green", "red"))


def _workflow(row: dict) -> str:
    """The run's name; the file's name when the run gave none, and NO_NAME when there is no
    file either: never empty."""
    named = (" ".join(value.split()) for value in (row.get("name"), row.get("workflow"))
             if isinstance(value, str))
    return next((text for text in named if text), NO_NAME)


def ci_title(row: dict) -> str:
    """"<workflow>: <part> is red", the workflow as _workflow names it."""
    return f"{_workflow(row)}: {' '.join(row['part'].split())} is red"


def _failed_job(item: dict) -> str:
    name, url, step = _name(item.get("job")), item.get("url"), item.get("step")
    if isinstance(url, str) and GITHUB.match(url):
        name = _link(name, url)
    elif isinstance(url, str) and url.strip():
        name = f"{name} ({_address(url)})"
    return f"- {name}: " + (f'the step "{_name(step)}" failed' if isinstance(step, str)
                            else "no failed step is named")


def ci_body(row: dict) -> str:
    """The issue of a red nightly part, in the bots' one look (bot_style.py), as drift_body in
    release_watch.py: badges, one line, Failed, What it means, What to do, the small print.
    Names go through _name, addresses through _address or _link."""
    part = _name(row.get("part"))
    since = row.get("since") if isinstance(row.get("since"), str) else "unknown"
    night = row.get("night")
    failed = [item for item in row.get("failed") or [] if isinstance(item, dict)]
    jobs = _n(len(failed), "job of the nightly part", "jobs of the nightly part")
    lead = (f"{jobs} {part} failed." if failed else f"The nightly part {part} failed.")
    if isinstance(night, str):
        lead += f" Its newest run was made {_name(night)}."
    run = row.get("run")
    opened = (_link("Open the run", run) if isinstance(run, str) and GITHUB.match(run)
              else f"Open the run: {_address(run)}")
    set_aside = SET_ASIDE.format(repo=REPO)
    parts = [
        style.row(style.info(_workflow(row), str(row.get("part") or "?")),
                  style.bad("red since", since)),
        lead,
        "### Failed\n" + ("\n".join(_failed_job(item) for item in failed)
                          or "No failed job is named."),
        f"### What it means\n{MEANS.get(row.get('part'), MEANS_ELSE)}",
        f"### What to do\n{opened}. If it failed by chance, re-run the failed jobs; if the same "
        f"test fails by chance again, add it to [`tests/set-aside.txt`]({set_aside}). If it is "
        "real, fix it.",
        style.small("Opened by the desk, a daily script in kitden-sdlc with no AI model",
                    "updated every day", "closes itself when the job is green"),
    ]
    return "\n\n".join(parts) + "\n"


def post_nightly(gh: GhIssues, rows: list[dict] | None) -> None:
    """One `ci-failure` issue per red nightly part, rewritten each day; a green part's issue
    is closed. A grey row proves neither a failure nor a fix, so its issue is left alone, as
    is the issue of a row that cannot be read. When there are rows and every one is green or
    red, an open
    `ci-failure` issue of the bot whose title is no row's title is closed: its job no longer
    exists. With `rows` None (not read) nothing is opened or closed."""
    if not isinstance(rows, list):
        return
    titles, sure = set(), True
    for row in rows:
        if not _readable(row):
            sure = False
            continue
        titles.add(ci_title(row))
        upsert(gh, ci_title(row), ci_body(row) if row["state"] == "red" else "", CI_LABELS)
    if sure and titles:  # no row at all proves no job is gone
        for item in gh.by_bot("open", "ci-failure"):
            if item["title"] not in titles:
                gh.close(item["number"])


def post(gh: GhIssues, desk: dict) -> None:
    """The nightly's issues, with the labels made first."""
    ensure_labels(gh)
    post_nightly(gh, desk.get("nightly"))


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--desk", type=Path, required=True)
    parser.add_argument("--repo", help="OWNER/kitden, where the issues are")
    parser.add_argument("--dry-run", action="store_true", help="print the issues; call nothing")
    args = parser.parse_args(argv)
    if not args.dry_run and not args.repo:
        parser.error("--repo is needed to post; --dry-run only prints")
    desk = json.loads(args.desk.read_text())
    if args.dry_run:
        rows = desk.get("nightly")
        for row in rows if isinstance(rows, list) else []:
            if _readable(row) and row["state"] == "red":
                print(f"----- The issue {ci_title(row)!r}, opened or rewritten -----\n")
                print(ci_body(row), end="")
        return 0
    post(GhIssues(args.repo), desk)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
