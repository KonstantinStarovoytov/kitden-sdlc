"""Show desk.json as one issue in Kitden, "Kitden desk", rewritten on each run, and open one
`ci-failure` issue for each red nightly test job. No model.

    desk_post.py --desk desk.json --repo OWNER/kitden [--dry-run]

The bot (bot_issues.BOT) rewrites its own open issue with this title, or opens one; an issue a
person opened is never touched. The week's first run (weeks start on Monday, UTC) also leaves
one short comment, so the owner gets one notice a week. Then each red row of desk.json's
`nightly` gets its issue, opened or rewritten, and each green row's issue is closed (see
post_nightly). `--dry-run` prints the page, the week's note and the issue of each red row,
and calls nothing.

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
from post_findings import WORD_JOINER, one_line

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
# The nightly test jobs: one issue per red part, rewritten each day (see post_nightly).
CI_LABELS = ["automated", "ci-failure"]
NO_NAME = "Nightly run"  # the title's workflow when the run gave no name and no file
SET_ASIDE = "https://github.com/{repo}/blob/main/tests/set-aside.txt"
GREY_SHOWN = 2  # from its second grey night, a part says since when it has had no run
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


def _name(value) -> str:
    """A name from a run (a job, a step, a part) as `_cell` gives it, with a word joiner where
    GitHub would see an address, so the text is no link even after its entities are read."""
    return AUTOLINK.sub(WORD_JOINER, _cell(value if isinstance(value, str) else ""))


def _repo(desk: dict) -> str:
    repo = desk.get("repo")
    return repo if isinstance(repo, str) and SLUG.match(repo) else REPO


def _more(items: list, shown: int) -> list[str]:
    return ["", f"…and {len(items) - shown} more."] if shown < len(items) else []


def _list(desk: dict, key: str):
    value = desk.get(key)
    return value if isinstance(value, list) or value is None else []


# --- The page ---


def _small(desk: dict) -> str:
    return style.small("Written by desk_post.py, a script in kitden-sdlc; no model wrote it",
                       f"Numbers read at {_when(desk.get('updated'))}, from [desk.json]({DATA})")


# What each light checks, in a few words; the rules are in docs/owner.md.
CHECKS = {
    "works": "the checks on `main` pass",
    "clients": "no confirmed client change waits long",
    "bugs": "open bugs do not keep growing",
    "agents": "the bots run and are not paused",
    "queue": "nothing waits for you long",
}


def _state(light: dict) -> str:
    state = light.get("state")
    if state == "green":
        return style.mark("ok", style.GREEN, "check")
    if state == "amber":
        return style.mark("look", style.AMBER, "ask")
    if state == "red":
        return style.mark("wrong", style.RED, "cross")
    return style.mark("not measured")


def _why(light: dict) -> str:
    """Why a light is not green, in words; "" when its mark says it all."""
    state = light.get("state")
    why = one_line(str(light.get("why") or ""))
    if state == "green" or not why:
        return ""
    if state not in MARKS or state == "grey":
        return re.sub(rf"^{NOT_MEASURED_YET}:?\s*", "", why, flags=re.I)
    return _link(why, light.get("url"))


def _badges(desk: dict) -> str:
    """The first thing on the page, in the bots' one look (bot_style.py): a small table with a
    row for each light: its name, its mark, what it checks, and the reason when it is not green."""
    lights = [light for light in desk.get("lights") or [] if isinstance(light, dict)]
    if not lights:
        return style.info("lights", "none")
    rows = []
    for light in lights:
        name = one_line(str(light.get("name") or light.get("id") or "?"))
        checks = CHECKS.get(light.get("id"), "")
        why = _why(light).replace("|", "&#124;")
        rows.append(f"| **{name}** | {_state(light)} | {checks} | {why} |")
    head = f"| Light | {style.wide('State', 8)} | Checks that | Why not |\n|---|---|---|---|\n"
    return head + "\n".join(rows)


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


def _lead(desk: dict) -> str:
    """The one line under the badges: how the five lights stand."""
    state = desk.get("overall")
    return OVERALL[state if state in MARKS else "grey"]


def _set_aside(desk: dict) -> str:
    count = desk.get("set_aside")
    if not isinstance(count, int) or isinstance(count, bool):
        return f"Tests set aside: {NOT_MEASURED_YET}."
    return (f"Tests set aside: {_figure(count)} "
            f"([tests/set-aside.txt]({SET_ASIDE.format(repo=_repo(desk))})).")


def _part_mark(row: dict) -> str:
    """A nightly part: its mark, its name linked to its run, and since when it is red. A grey
    part that was red before its grey nights says since when it was red and since when it has
    had no finished run; another grey part says the second from its GREY_SHOWN-th grey night."""
    state = row.get("state") if row.get("state") in ("green", "red") else "grey"
    text = f"{MARKS[state]} {_link(_name(row.get('part')), row.get('run'))}"
    since, grey_since, nights = row.get("since"), row.get("grey_since"), row.get("grey_nights")
    if state == "red" and isinstance(since, str):
        return f"{text} since {_name(since)}"
    if state != "grey":
        return text
    if isinstance(since, str):
        text += f" red since {_name(since)}"
        if isinstance(grey_since, str):
            text += f" (no finished run since {_name(grey_since)})"
        return text
    if isinstance(grey_since, str) and isinstance(nights, int) and nights >= GREY_SHOWN:
        return f"{text} (no finished run since {_name(grey_since)})"
    return text


def _nightly(desk: dict) -> str:
    """One line: each nightly part, grouped by the night its row is about (GitHub starts
    scheduled runs hours late, so the desk may see the night before), then the tests set
    aside."""
    rows = desk.get("nightly")
    if not isinstance(rows, list):
        return f"Nightly runs: {NOT_MEASURED_YET}. {_set_aside(desk)}"
    nights: dict[str | None, list[str]] = {}
    for row in rows:
        if isinstance(row, dict):
            night = row.get("night")
            nights.setdefault(_name(night) if isinstance(night, str) else None,
                              []).append(_part_mark(row))
    if not nights:
        return f"Nightly: no nightly job is expected. {_set_aside(desk)}"
    parts = "; ".join(f"{', '.join(marks)} "
                      f"({'the night of ' + night if night else 'the night is not known'})"
                      for night, marks in nights.items())
    return f"Nightly: {parts}. {_set_aside(desk)}"


def _health(desk: dict) -> list[str]:
    """How Kitden is used, and how the nightly tests stand. The lights are the badges on
    top."""
    return [_use(desk.get("use") or {}), _nightly(desk)]


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
    repo = _repo(desk)
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
        # The Nightly column is named only when it is shown (see _table).
        nightly = ("Nightly: `ci-failure` issues the desk opened for a red nightly test job. "
                   if any(r.get("nightly") is not None for r in _rows(desk, "found_by")) else "")
        lines += ["Who found problems, by month. Review: findings fixed before the merge. "
                  f"{nightly}Watcher: confirmed client changes. You and Others: bugs opened.", "",
                  *found]
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
        [_lead(desk)],
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


def _week_note(gh: GhIssues, number: int, desk: dict, now: datetime) -> None:
    """Comment the week's note once a week: its first line, "Week of <that Monday>", tells
    whether this week's is there already."""
    note = week_note(desk, now)
    week = note.split("\n", 1)[0]
    if any((c.get("user") or {}).get("login") == BOT and _first_line(c) == week
           for c in gh.comments(number)):
        return
    gh.comment(number, note)


def post(gh: GhIssues, desk: dict, now: datetime) -> None:
    """Rewrite the desk issue and comment the week's note; then the nightly's issues."""
    ensure_labels(gh)
    number = upsert(gh, TITLE, render(desk), LABELS)
    if number is not None:
        _week_note(gh, number, desk, now)
    post_nightly(gh, desk.get("nightly"))


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
        rows = desk.get("nightly")
        for row in rows if isinstance(rows, list) else []:
            if _readable(row) and row["state"] == "red":
                print(f"\n----- The issue {ci_title(row)!r}, opened or rewritten -----\n")
                print(ci_body(row), end="")
        return 0
    post(GhIssues(args.repo), desk, now)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
