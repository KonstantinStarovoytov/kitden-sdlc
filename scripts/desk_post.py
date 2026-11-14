"""Show desk.json as one issue in Kitden, "Kitden desk", rewritten on each run. No model.

    desk_post.py --desk desk.json --repo OWNER/kitden [--dry-run]

The bot (bot_issues.BOT) rewrites its own open issue with this title, or opens one; an issue a
person opened is never touched. The week's first run (weeks start on Monday, UTC) also leaves
one short comment, so the owner gets one notice a week. `--dry-run` prints the page and the
week's note, and calls nothing.

None in desk.json means "not measured": the page says so in words. Every title and `why` was
written by a person or a model, so each goes through `one_line`; only a github.com address
becomes a link, and the usage pages config/agents.json names, which only the owner changes.

Standard library only: it runs with `uv run --no-project`.
"""

import argparse
import functools
import json
import re
import sys
import urllib.parse
from datetime import UTC, datetime, timedelta
from pathlib import Path

import bot_style as style
from bot_issues import BOT, GhIssues, ensure_labels, upsert
from count_reviews import REPO, SINCE_DAYS
from post_findings import one_line

TITLE = "Kitden desk"
LABELS = ["automated", "desk"]
DATA = "https://github.com/KonstantinStarovoytov/kitden-sdlc/blob/numbers/desk.json"
HOW_TO = "https://github.com/KonstantinStarovoytov/kitden-sdlc/blob/main/docs/owner.md"
ROSTER = Path(__file__).resolve().parent.parent / "config" / "agents.json"
LIMIT = 65_536  # GitHub's limit for an issue body; the page counts UTF-8 bytes, never fewer
MARKS = {"green": "🟢", "amber": "🟡", "red": "🔴", "grey": "⚪"}
OVERALL = {
    "green": "All five lights are green.",
    "amber": "Something needs a look.",
    "red": "Something is wrong.",
    "grey": "Some lights are not measured yet; none is amber or red.",
}
# Cells that do not apply: release prep gets no verdict from the owner.
NOT_APPLICABLE = {"release-prep": ("agreed", "disagreed")}
KINDS = {"pull": "Pull request", "verdict": "Verdict", "release": "Release",
         "paused": "Paused agent", "spot-check": "Spot check"}
NOT_MEASURED_YET = "not measured yet"
# An address we put into a link: github.com, and no character that could end the link.
GITHUB = re.compile(r"https://github\.com/[\w.~/#?=&%+-]*\Z")
USAGE = re.compile(r"https://[\w.-]+/[\w.~/#?=&%+-]*\Z")  # the same, on any https host
SLUG = re.compile(r"[\w-]+/[\w.-]+\Z")
SEARCHES = (  # (what, page, query)
    ("Open issues from people", "issues", "is:issue is:open -label:automated"),
    ("Open issues from bots", "issues", "is:issue is:open label:automated"),
    ("Open pull requests by the release bot", "pulls",
     "is:pr is:open author:app/kitden-beacon"),
    ("The watcher's weekly summaries", "issues", "is:issue label:client-change label:summary"),
)
CUT = ("waiting", "misses")  # the lists that can grow long; the longest is cut first


class Safe(str):
    """Markdown this script wrote: a table cell shows it as it is."""


DASH = Safe("—")  # a cell that does not apply to its row; not a measurement


# --- Small pieces ---


def _number(value) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool)


def _figure(value) -> str:
    return f"{value:,}" if isinstance(value, int) else f"{value:g}"


def _n(value, one: str, many: str) -> str:
    return f"{_figure(value)} {one if value == 1 else many}"


def _days(value) -> str:
    """Days as desk.json rounds them, to a tenth: 0.0 is under 0.1, not none."""
    return "under 0.1 days" if 0 <= value < 0.05 else _n(value, "day", "days")


def _utc(when: datetime) -> datetime:
    return when.replace(tzinfo=UTC) if when.tzinfo is None else when.astimezone(UTC)


def _when(text) -> str:
    try:
        return _utc(datetime.fromisoformat(text)).strftime("%Y-%m-%d %H:%M UTC")
    except (TypeError, ValueError):
        return "an unknown time"


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


def _table(rows: list[dict], columns: list[tuple[str, object]]) -> list[str] | None:
    """A Markdown table. `columns` are (header, row -> value); the first names the row. A
    column with no value measured in any row is left out, and named under the table unless
    it applies to no row (DASH everywhere). None when no row or no column is left: the
    caller says so in a sentence."""
    values = [[get(row) for _, get in columns] for row in rows]
    keep = [0] + [i for i in range(1, len(columns))
                  if any(v[i] is not None and v[i] is not DASH for v in values)]
    if not rows or len(keep) == 1:
        return None
    lines = ["| " + " | ".join(columns[i][0] for i in keep) + " |", "|" + "---|" * len(keep)]
    lines += ["| " + " | ".join(_cell(v[i]) for i in keep) + " |" for v in values]
    dropped = [header for i, (header, _) in enumerate(columns)
               if i not in keep and any(v[i] is None for v in values)]
    return lines + (["", f"Not measured yet: {', '.join(dropped)}."] if dropped else [])


def _more(items: list, shown: int) -> list[str]:
    return ["", f"…and {len(items) - shown} more."] if shown < len(items) else []


def _list(desk: dict, key: str):
    value = desk.get(key)
    return value if isinstance(value, list) or value is None else []


# --- The page ---


def _small(desk: dict) -> str:
    return style.small("Written by desk_post.py, a script in kitden-sdlc; no model wrote it",
                       f"Numbers read at {_when(desk.get('updated'))}, from [desk.json]({DATA})")


def _badge(light: dict) -> str:
    name = one_line(str(light.get("name") or light.get("id") or "?"))
    state = light.get("state")
    if state == "green":
        return style.ok(name, "ok")
    if state == "amber":
        return style.warn(name, "look")
    if state == "red":
        return style.bad(name, "wrong")
    return style.info(name, "not measured")


def _badges(desk: dict) -> str:
    """The first line, in the bots' one look (bot_style.py): a badge for each light."""
    lights = [light for light in desk.get("lights") or [] if isinstance(light, dict)]
    return style.row(*(_badge(light) for light in lights)) or style.info("lights", "none")


def _light(light: dict) -> str:
    state = light.get("state")
    name = one_line(str(light.get("name") or light.get("id") or "?"))
    why = one_line(str(light.get("why") or ""))
    if state not in MARKS or state == "grey":
        why = re.sub(rf"^{NOT_MEASURED_YET}:?\s*", "", why, flags=re.I)
        return f"- ⚪ {name}: {NOT_MEASURED_YET}" + (f": {why}" if why else ".")
    if state == "green" or not why:
        return f"- {MARKS[state]} {name}"
    return f"- {MARKS[state]} {name}: {_link(why, light.get('url'))}"


def _use(use: dict) -> str:
    issues, pulls = use.get("issues_from_others"), use.get("pulls_from_others")
    stars, downloads = use.get("stars"), use.get("downloads")
    if _number(issues) and _number(pulls):
        parts = [f"{_n(issues, 'issue', 'issues')} and "
                 f"{_n(pulls, 'pull request', 'pull requests')} from others this month"]
    else:
        parts = [f"{_n(issues, 'issue', 'issues')} from others this month" if _number(issues)
                 else f"issues from others: {NOT_MEASURED_YET}",
                 f"{_n(pulls, 'pull request', 'pull requests')} from others this month"
                 if _number(pulls) else f"pull requests from others: {NOT_MEASURED_YET}"]
    parts.append(_n(stars, "star", "stars") if _number(stars) else f"stars: {NOT_MEASURED_YET}")
    parts.append(f"{_n(downloads, 'download', 'downloads')} from PyPI last month"
                 if _number(downloads) else f"downloads: {NOT_MEASURED_YET}")
    if not any(_number(value) for value in (issues, pulls, stars, downloads)):
        return f"Use: {NOT_MEASURED_YET}."
    return "Use: " + "; ".join(parts) + "."


def _health(desk: dict) -> list[str]:
    state = desk.get("overall")
    state = state if state in MARKS else "grey"
    lights = desk.get("lights") or []
    lines = [f"**{MARKS[state]} {OVERALL[state]}**", ""]
    lines += [_light(light) for light in lights if isinstance(light, dict)] or ["- ⚪ No light."]
    return [*lines, "", _use(desk.get("use") or {})]


def _wait(item: dict) -> str:
    kind = item.get("kind")
    what = KINDS.get(kind) or one_line(str(kind or "Item"))
    title = _link(one_line(str(item.get("title") or "")) or "(no title)", item.get("url"))
    line = f"- {what}: {title}"
    if item.get("do"):
        line += f" — {' '.join(str(item['do']).split())}"
    if _number(item.get("days")):
        line += f" Waiting {_days(item['days'])}."
    return line


def _waiting(items: list | None, shown: int) -> list[str]:
    if items is None:
        return ["Not measured."]
    if not items:
        return ["Nothing."]
    return [_wait(item) for item in items[:shown] if isinstance(item, dict)] + _more(items, shown)


def _links(desk: dict) -> list[str]:
    repo = desk.get("repo")
    repo = repo if isinstance(repo, str) and SLUG.match(repo) else REPO
    return [
        f"- [{what}](https://github.com/{repo}/{page}?{urllib.parse.urlencode({'q': query})})"
        for what, page, query in SEARCHES
    ]


def _review(review: dict) -> str:
    clean, fixed, days = (review.get(key) for key in ("clean", "fixed", "days_to_merge"))
    if not any(_number(value) for value in (clean, fixed, days)):
        return f"Reviews: {NOT_MEASURED_YET}."
    parts = [
        f"{_n(clean, 'review', 'reviews')} found nothing" if _number(clean)
        else f"reviews that found nothing: {NOT_MEASURED_YET}",
        f"{_n(fixed, 'finding was', 'findings were')} fixed before the merge" if _number(fixed)
        else f"findings fixed: {NOT_MEASURED_YET}",
        f"a reviewed pull request took {_days(days)} to merge (the median)" if _number(days)
        else f"days to merge: {NOT_MEASURED_YET}",
    ]
    return "Reviews: " + "; ".join(parts) + "."


def _ref(value) -> str:
    return f"#{value}" if isinstance(value, int) and not isinstance(value, bool) \
        else one_line(str(value))


def _misses(items: list | None, shown: int) -> list[str]:
    if items is None:
        return [f"Misses: {NOT_MEASURED_YET}."]
    if not items:
        return ["No misses in the last 30 days."]
    lines = ["Misses: bugs opened in the last 30 days that a reviewed pull request caused.", ""]
    lines += [
        f"- {_link('Issue ' + _ref(item.get('issue')), item.get('url'))}, "
        f"caused by pull request {_ref(item.get('pull'))}"
        for item in items[:shown] if isinstance(item, dict)
    ]
    return lines + _more(items, shown)


def _rows(desk: dict, key: str) -> list[dict]:
    rows = desk.get(key)
    return [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []


def _applies(row: dict, key: str):
    return DASH if key in NOT_APPLICABLE.get(row.get("agent"), ()) else row.get(key)


def _this_week(desk: dict, shown: dict[str, int]) -> list[str]:
    lines = [f"Reviews are counted over the last {SINCE_DAYS} days, the weekly columns over "
             "the last 7 (the watcher's verdicts over 30).", ""]
    week = _table(_rows(desk, "week"), [
        ("Agent", lambda r: r.get("name") or r.get("agent")),
        ("Runs", lambda r: r.get("runs")),
        ("Failed", lambda r: r.get("failed")),
        ("Did", lambda r: r.get("did")),
        ("No answer", lambda r: r.get("no_answer", DASH)),  # only a reviewer has the key
        ("You agreed", lambda r: _applies(r, "agreed")),
        ("You disagreed", lambda r: _applies(r, "disagreed")),
    ])
    if week:
        lines += [*week, "", "Runs: runs that ended, well or badly; the two reviewers share one "
                  "per push. Failed: those that failed. Did: pull requests reviewed, issues "
                  "opened or release pull requests opened. No answer: review comments in which "
                  "that reviewer gave none. Agreed and disagreed: your 👍 and 👎 on a review, or "
                  "`confirmed` and `false-alarm` on the watcher's issues."]
    else:
        lines += [f"The agents' week: {NOT_MEASURED_YET}."]
    lines += ["", _review(desk.get("review") or {}), ""]
    found = _table(_rows(desk, "found_by"), [
        ("Month", lambda r: r.get("month")),
        *[(header, lambda r, key=key: r.get(key)) for header, key in (
            ("Review", "review"), ("Nightly", "nightly"), ("Tester", "tester"),
            ("Watcher", "watcher"), ("You", "owner"), ("Others", "others"))],
    ])
    if found:
        lines += ["Who found problems, by month. Review: findings fixed before the merge. "
                  "Watcher: confirmed client changes. You and Others: bugs opened.", "", *found]
    else:
        lines += [f"Who found problems: {NOT_MEASURED_YET}."]
    return [*lines, "", *_misses(_list(desk, "misses"), shown["misses"])]


def _budget(desk: dict) -> list[str]:
    budget = desk.get("budget") or {}
    names = {row.get("agent"): row.get("name") for row in _rows(desk, "week")}
    agents = [row for row in budget.get("agents") or [] if isinstance(row, dict)]
    keys = [row for row in budget.get("keys") or [] if isinstance(row, dict)]
    caps = _table(agents, [
        ("Agent", lambda r: names.get(r.get("agent")) or r.get("agent")),
        ("Runs", lambda r: r.get("runs")),
        ("Cap", lambda r: r.get("cap")),
    ])
    lines = (["Each agent's runs in the last 7 days, and its cap:", "", *caps] if caps
             else ["No agent is listed."])
    stored = _table(keys, [
        ("Key", lambda r: r.get("name")),
        ("Stored in", lambda r: r.get("stored")),
        ("Used by", lambda r: r.get("used_by")),
        ("Money cap", lambda r: r.get("money_cap")),
        ("Usage page", lambda r: _address(r.get("dashboard"))),
    ])
    lines += ["", "The keys the agents use:", "", *stored] if stored else ["", "No key is listed."]
    return [*lines, "", "The providers enforce the money caps; no billing key is stored."]


def _page(desk: dict, shown: dict[str, int]) -> str:
    parts = [
        [_badges(desk)],
        ["### Health", "", *_health(desk)],
        ["### Waiting for you", "", *_waiting(_list(desk, "waiting"), shown["waiting"])],
        ["### Links", "", *_links(desk)],
        ["### This week", "", *_this_week(desk, shown)],
        ["### Budget", "", *_budget(desk)],
        ["### How to", "", f"What each light means and what to do: [docs/owner.md]({HOW_TO})."],
        [_small(desk)],
    ]
    return "\n\n".join("\n".join(part) for part in parts) + "\n"


def _fits(body: str) -> bool:
    return len(body.encode()) < LIMIT


def _cut_text(body: str) -> str:
    """The page cut at a line that fits, when even the lists cut to nothing do not."""
    note = "\n\n…the rest of the page is cut: it is too long for an issue.\n"
    head = body.encode()[: LIMIT - len(note.encode()) - 1].decode(errors="ignore")
    return head.rsplit("\n", 1)[0] + note


def render(desk: dict) -> str:
    """The desk issue's body. When it is too long for GitHub, the longest list is cut, with
    "…and N more", until it fits."""
    shown = {key: len(_list(desk, key) or []) for key in CUT}
    while True:
        body = _page(desk, shown)
        if _fits(body):
            return body
        longest = max(CUT, key=lambda key: shown[key])
        if not shown[longest]:
            return _cut_text(body)
        shown[longest] -= max(1, shown[longest] // 20)


# --- The week's note ---


def _monday(now: datetime) -> datetime:
    day = _utc(now)
    return day - timedelta(days=day.weekday())


def week_note(desk: dict, now: datetime) -> str:
    """The weekly comment: "Week of <that Monday>", the overall light, how many things wait,
    and the spot check's link when there is one."""
    state = desk.get("overall")
    state = state if state in MARKS else "grey"
    items = _list(desk, "waiting")
    if items is None:
        count = "What waits for you was not measured."
    else:
        count = f"{_n(len(items), 'thing waits', 'things wait')} for you."
    lines = [f"Week of {_monday(now):%Y-%m-%d}", "", f"{MARKS[state]} {OVERALL[state]} {count}"]
    spot = next((item for item in items or [] if isinstance(item, dict)
                 and item.get("kind") == "spot-check"), None)
    if spot:
        title = one_line(str(spot.get("title") or "")) or "this week's spot check"
        lines += ["", f"Spot check: {_link(title, spot.get('url'))}"]
    return "\n".join(lines) + "\n"


def _first_line(comment: dict) -> str:
    return (comment.get("body") or "").split("\n", 1)[0].strip()


def post(gh: GhIssues, desk: dict, now: datetime) -> None:
    """Rewrite the desk issue; comment the week's note once a week: its first line, "Week of
    <that Monday>", tells whether this week's is there already."""
    ensure_labels(gh)
    number = upsert(gh, TITLE, render(desk), LABELS)
    if number is None:
        return
    note = week_note(desk, now)
    week = note.split("\n", 1)[0]
    if any((c.get("user") or {}).get("login") == BOT and _first_line(c) == week
           for c in gh.comments(number)):
        return
    gh.comment(number, note)


def main(argv: list[str], now: datetime | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--desk", type=Path, required=True)
    parser.add_argument("--repo", help="OWNER/kitden, where the desk issue is")
    parser.add_argument("--dry-run", action="store_true", help="print the page; call nothing")
    args = parser.parse_args(argv)
    if not args.dry_run and not args.repo:
        parser.error("--repo is needed to post; --dry-run only prints")
    desk = json.loads(args.desk.read_text())
    now = now or datetime.now(UTC)
    if args.dry_run:
        print(render(desk), end="")
        print("\n----- The week's note, posted with the week's first run -----\n")
        print(week_note(desk, now), end="")
        return 0
    post(GhIssues(args.repo), desk, now)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
