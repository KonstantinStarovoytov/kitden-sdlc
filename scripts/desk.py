"""Work out the owner's desk from facts: five lights, what waits for him, and the week's numbers.

Pure: nothing here calls GitHub, reads a file or reads the clock; the caller passes `now`.
A fact that was not read is None, and what needs it is grey or None, never good news.
A light's `why` names numbers, never a title: a model wrote many of them. A waiting item
carries its own title, on one line and cut short; the page that shows it escapes it.
"""

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from bot_issues import BOT, VERDICTS, names, paused_title
from count_reviews import MAINTAINER, REPO, Review, summary

ORDER = ("red", "amber", "grey", "green")  # the first one any light has is the overall light
RED_ENDINGS = ("failure", "timed_out", "cancelled", "action_required", "startup_failure")
GOOD_ENDINGS = ("success", "neutral", "skipped")
WATCH_LOG_DAYS = 2  # older than this, the watcher's issues say nothing about today
PAUSED = paused_title("")  # " is paused": the end of the title of a pause issue
REVIEWERS = ("claude", "luna")
PARTLY = "main's rules were only partly read."
TITLE_LENGTH = 100
MOSTLY_FAILING = 4  # with fewer runs or reviews in 7 days, an agent's failures say little
DO = {
    "pull": "Review it and merge, or close it.",
    "verdict": "Put `confirmed` on it, or close it with `false-alarm`.",
    "release": "Do what it says under What to do.",
    "paused": "Close it to start the agent again.",
    "spot-check": "Look at the change, then 👍 or 👎 on its Agent review comment.",
}
CAUSED_BY = re.compile(r"^###[ \t]*Caused by[ \t\r]*$(.*?)(?=^###|\Z)", re.I | re.M | re.S)
# "#N" or "PR#N", or the address of a pull request in REPO. Not a bare N, "owner/repo#N", "&#N;".
REFERENCE = re.compile(
    rf"(?:(?<![\w&])|(?<=\bPR))#(\d+)\b|https://github\.com/{re.escape(REPO)}/pull/(\d+)\b", re.I)


@dataclass
class Facts:
    """What was read. None means the read failed or was never made."""

    repo: str = REPO  # the repository the facts were read from
    issues: list[dict] | None = None  # every Kitden issue, open and closed, no pull requests
    pulls: list[dict] | None = None  # every open pull request, and the closed ones of 90 days
    reviews: list[Review] | None = None  # review comments in which a reviewer answered
    silent: list[Review] | None = None  # review comments in which neither reviewer answered
    checks: list[dict] | None = None  # check runs of main's newest commit, each with `event`
    required: list[str] | None = None  # the checks main requires
    required_partial: bool = False  # `required` holds only what one of two reads gave
    runs: dict[str, int | None] = field(default_factory=dict)  # agent id -> runs that ended
    failed: dict[str, int | None] = field(default_factory=dict)  # agent id -> those that failed
    watch_log: list[dict] | None = None  # the watcher's log.jsonl
    stars: int | None = None
    downloads: int | None = None  # PyPI, last month


# --- Time and who wrote what ---


def _utc(when: datetime) -> datetime:
    """`when` in UTC; without an offset it is read as UTC."""
    return when.replace(tzinfo=UTC) if when.tzinfo is None else when.astimezone(UTC)


def _at(text: str) -> datetime:
    return _utc(datetime.fromisoformat(text))


def _age(text: str, now: datetime) -> float:
    """Days from `text` to `now`, not rounded: limits compare against this."""
    return (now - _at(text)).total_seconds() / 86400


def _days(text: str, now: datetime) -> float:
    return round(_age(text, now), 1)


def _monday(now: datetime) -> datetime:
    """This ISO week's Monday, 00:00 UTC."""
    day = now.astimezone(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    return day - timedelta(days=day.weekday())


def _month(when: datetime, back: int = 0) -> str:
    """'YYYY-MM' of the month `back` months before `when`."""
    index = when.year * 12 + when.month - 1 - back
    return f"{index // 12:04d}-{index % 12 + 1:02d}"


def _login(item: dict) -> str:
    return (item.get("user") or {}).get("login") or ""


def _by_a_bot(item: dict) -> bool:
    """An app's account ("…[bot]"), or any account GitHub marks as a bot, such as Copilot."""
    return _login(item).endswith("[bot]") or (item.get("user") or {}).get("type") == "Bot"


def _by_a_person_not_the_owner(item: dict) -> bool:
    return not _by_a_bot(item) and _login(item).lower() != MAINTAINER.lower()


def _bots(issues: list[dict], *labels: str, open_only: bool = True) -> list[dict]:
    """The issues BOT opened that have every one of `labels`."""
    return [
        item for item in issues
        if _login(item) == BOT and set(labels) <= names(item)
        and (not open_only or item["state"] == "open")
    ]


def _findings(issues: list[dict], open_only: bool = False) -> list[dict]:
    """The watcher's client-change issues, its weekly summary left out."""
    found = _bots(issues, "client-change", open_only=open_only)
    return [item for item in found if "summary" not in names(item)]


def _pauses(issues: list[dict]) -> list[dict]:
    return [item for item in _bots(issues, "desk") if item["title"].endswith(PAUSED)]


def _opened(item: dict) -> tuple[datetime, int]:
    return _at(item["created_at"]), item["number"]


def _oldest(issues: list[dict]) -> dict | None:
    return min(issues, key=_opened, default=None)


# --- The lights ---


def _light(light_id: str, state: str, why: str = "", url: str = "") -> dict:
    """A light; `url` is the address of the issue or pull request its `why` names."""
    light = {"id": light_id, "name": light_id.capitalize(), "state": state, "why": why}
    return {**light, "url": url} if url else light


def _worst(*lights: dict | None) -> dict | None:
    """The light with the worst state; None when none is given."""
    given = [light for light in lights if light]
    return min(given, key=lambda light: ORDER.index(light["state"]), default=None)


def _settle(light_id: str, found: list[dict | None], missing: str = "",
            unproven: str = "") -> dict:
    """The worst light the read facts prove, its `why` ending with what `missing` names; else
    grey when `missing` names a fact that was not read and could have shown something bad,
    or `unproven` says why nothing read shows good news; else green."""
    worst = _worst(*found)
    if worst:
        if missing:
            return {**worst, "why": f"{worst['why']} Also not measured: {missing}"}
        return worst
    reason = " ".join(filter(None, [unproven, missing]))
    if reason:
        return _light(light_id, "grey", f"Not measured yet: {reason}")
    return _light(light_id, "green")


def _limits(light_id: str, item: dict | None, now: datetime, amber: float, red: float,
            what: str) -> dict | None:
    """Red past `red` days, amber past `amber`, for the oldest `item`; None when neither."""
    if item is None or _age(item["created_at"], now) <= amber:
        return None
    state = "red" if _age(item["created_at"], now) > red else "amber"
    days = _days(item["created_at"], now)
    return _light(light_id, state, f"Issue #{item['number']} {what} has been open {days} days.",
                  item.get("html_url") or "")


def _checks_named(checks: list[dict], test) -> list[str]:
    return sorted({c["name"] for c in checks if test(c)})


def _started(check: dict) -> tuple[datetime, int]:
    """When a check run started, then its id; a run without a readable time sorts first."""
    try:
        when = _at(check["started_at"])
    except (KeyError, TypeError, ValueError):
        when = datetime.min.replace(tzinfo=UTC)
    number = check.get("id")
    return when, number if isinstance(number, int) else 0


def _judged(checks: list[dict], required: list[str] | None) -> list[dict]:
    """The check runs Works judges: of each name, the newest run, among the runs started by the
    push to main or of unknown event. A check main requires counts whatever its event."""
    needed = set(required or ())
    ours = [c for c in checks if c.get("event") in (None, "push") or c["name"] in needed]
    newest: dict[str, dict] = {}
    for check in ours:
        if check["name"] not in newest or _started(check) > _started(newest[check["name"]]):
            newest[check["name"]] = check
    return list(newest.values())


def _verb(names: list[str]) -> str:
    return "has" if len(names) == 1 else "have"


def _not_passed(required: list[str] | None, passed: list[str]) -> dict | None:
    """Amber when a check main requires is missing on the commit or did not succeed."""
    left = sorted(set(required or ()) - set(passed))
    if not left:
        return None
    return _light("works", "amber",
                  f"{', '.join(left)} {_verb(left)} not passed on main's newest commit.")


def _failed(failed: list[str], required: list[str] | None, partial: bool) -> dict | None:
    """Red for a failed check main requires, or any failed check when main's rules were not
    read whole; amber, with the names, when main surely requires none of them."""
    if not failed:
        return None
    if required is None or partial or set(failed) & set(required):
        return _light("works", "red", f"On main, {', '.join(failed)} failed.")
    them = "it" if len(failed) == 1 else "any of them"
    return _light("works", "amber",
                  f"On main, {', '.join(failed)} failed; main does not require {them}.")


def light_works(checks: list[dict] | None, required: list[str] | None = None,
                partial: bool = False) -> dict:
    """Main's newest commit: the newest run of each check its push started, and of each check
    main requires (see _judged). Each check main requires must also have passed. `required`
    None: main's rules were not read, so passing checks are not yet good news. `partial`:
    `required` is only part of main's rules, so nothing bad found there is not yet good news
    either. A check run's `event` is that of its workflow run; None when not known."""
    if checks is None:
        return _light("works", "grey", "Not measured yet: no check run of main was read.")
    missing = ["main's rules were not read."] if required is None else []
    if partial:
        missing.append(PARTLY)
    if not checks:
        found = None
        if required:
            found = _light("works", "amber", f"{', '.join(required)} {_verb(required)} not run "
                                             "on main's newest commit.")
        return _settle("works", [found], " ".join(missing),
                       "no check has run on main's newest commit.")
    judged = _judged(checks, required)
    done = [c for c in judged if c.get("status") == "completed"]
    failed = _checks_named(done, lambda c: c.get("conclusion") in RED_ENDINGS)
    running = _checks_named(judged, lambda c: c.get("status") != "completed")
    odd = _checks_named(done, lambda c: c.get("conclusion") not in GOOD_ENDINGS + RED_ENDINGS)
    passed = _checks_named(done, lambda c: c.get("conclusion") == "success")
    found = [
        _failed(failed, required, partial),
        _light("works", "amber", f"On main, {', '.join(running)} has not finished.")
        if running else None,
        _light("works", "amber", f"On main, {', '.join(odd)} ended neither well nor badly.")
        if odd else None,
        _not_passed(required, passed),
    ]
    unproven = "" if passed else "no check on main's newest commit passed."
    return _settle("works", found, " ".join(missing), unproven)


def _log_day(line: dict) -> datetime | None:
    """The start of the day a log line gives, in UTC; None when it gives none."""
    try:
        return datetime.fromisoformat(line["date"] + "T00:00:00+00:00")
    except (KeyError, TypeError, ValueError):
        return None


def _measured(line: dict) -> bool:
    """A run that read something: nothing new to read (`pieces` 0), or `judged` above 0.
    A run whose every model call failed still writes a line; it measured nothing."""
    def number(key):
        value = line.get(key)
        return value if isinstance(value, int) and not isinstance(value, bool) else None
    return number("pieces") == 0 or (number("judged") or 0) > 0


def _watch_log_age(watch_log: list[dict] | None, now: datetime) -> float | None:
    """Days since the end of the day of the watcher's newest run that measured something: the
    run may have been as late as that, so an age above WATCH_LOG_DAYS proves no run in the
    last WATCH_LOG_DAYS days. None without one. A line dated after `now` is not believed."""
    lines = [line for line in watch_log or [] if isinstance(line, dict) and _measured(line)]
    days = [day for day in map(_log_day, lines) if day and day <= now]
    if not days:
        return None
    return (now - max(days) - timedelta(days=1)).total_seconds() / 86400


def light_clients(issues: list[dict] | None, watch_log: list[dict] | None, now: datetime) -> dict:
    now = _utc(now)
    if issues is None:
        return _light("clients", "grey", "Not measured yet: the issues were not read.")
    late = _oldest(_bots(issues, "client-change", "confirmed", "major"))
    found = _limits("clients", late, now, 3.5, 7, "(a confirmed major client change)")
    age = _watch_log_age(watch_log, now)
    stale = age is None or age > WATCH_LOG_DAYS
    missing = f"the watcher logged no run in the last {WATCH_LOG_DAYS} days." if stale else ""
    return _settle("clients", [found], missing)


def _open_bugs_on(issues: list[dict], monday: datetime) -> int:
    """Open `bug` issues at that Monday 00:00: opened before it and not closed before it.
    An issue open today counts as never closed, whatever its `closed_at` says."""
    return sum(
        1 for item in issues
        if "bug" in names(item) and _at(item["created_at"]) < monday
        and not (item["state"] != "open" and item.get("closed_at")
                 and _at(item["closed_at"]) < monday)
    )


def _bugs_grew(issues: list[dict], now: datetime) -> dict | None:
    """Red when the open bugs grew on each of the last three Mondays, amber on the last two."""
    monday = _monday(now)
    counts = [_open_bugs_on(issues, monday - timedelta(weeks=n)) for n in range(4)]
    grew = 0
    while grew < 3 and counts[grew] > counts[grew + 1]:
        grew += 1
    if grew < 2:
        return None
    shown = ", ".join(map(str, reversed(counts[: grew + 1])))
    return _light("bugs", "red" if grew == 3 else "amber",
                  f"Open bugs grew on each of the last {grew} Mondays: {shown}.")


def light_bugs(issues: list[dict] | None, now: datetime) -> dict:
    now = _utc(now)
    if issues is None:
        return _light("bugs", "grey", "Not measured yet: the issues were not read.")
    late = _oldest(_bots(issues, "confirmed", "major"))
    return _settle("bugs", [_limits("bugs", late, now, 7, 14, "(confirmed and major)"),
                            _bugs_grew(issues, now)])


def _required_agents(required: list[str]) -> dict | None:
    reviews = sorted(name for name in required if name.lower().startswith("review /"))
    if not reviews:
        return None
    return _light("agents", "red",
                  f"Main requires {', '.join(reviews)}; an agent's job must never be required.")


def _watcher_over_cap(issues: list[dict], now: datetime) -> dict | None:
    monday = _monday(now)
    this_week = [item for item in _findings(issues) if _at(item["created_at"]) >= monday]
    if len(this_week) <= 2:
        return None
    return _light("agents", "red",
                  f"The watcher opened {len(this_week)} issues this week, more than 2.")


def _paused_agent(issues: list[dict]) -> dict | None:
    paused = _oldest(_pauses(issues))
    if paused is None:
        return None
    return _light("agents", "amber", f"Issue #{paused['number']} says an agent is paused.",
                  paused.get("html_url") or "")


def _and(items: list[str]) -> str:
    """"a", "a and b", "a, b and c"."""
    return items[0] if len(items) == 1 else f"{', '.join(items[:-1])} and {items[-1]}"


def _mostly_failing(rows: list[dict]) -> dict | None:
    """Amber, naming each agent that failed more than half of at least MOSTLY_FAILING runs in
    7 days, and each reviewer that gave no answer in more than half of at least as many
    review comments."""
    named = []
    for row in rows:
        runs, failed = row.get("runs"), row.get("failed")
        if None not in (runs, failed) and runs >= MOSTLY_FAILING and failed * 2 > runs:
            named.append(f"{row['name']} failed {failed} of its {runs} runs")
        silent, did = row.get("no_answer"), row.get("did")
        if silent is not None and did is not None:
            seen = silent + did
            if seen >= MOSTLY_FAILING and silent * 2 > seen:
                named.append(f"{row['name']} gave no answer in {silent} of {seen} reviews")
    if not named:
        return None
    return _light("agents", "amber", f"In the last 7 days, {'; '.join(named)}.")


def light_agents(issues: list[dict] | None, required: list[str] | None, now: datetime,
                 partial: bool = False, rows: list[dict] | None = None) -> dict:
    """`partial`: `required` is only part of main's rules (see light_works). `rows`: the
    week's rows (see week); without them, failed runs are not judged."""
    now = _utc(now)
    found, missing = [], []
    if required is None:
        missing.append("main's rules")
    else:
        found.append(_required_agents(required))
    if issues is None:
        missing.append("the issues")
    else:
        found += [_watcher_over_cap(issues, now), _paused_agent(issues)]
    if rows is not None:
        found.append(_mostly_failing(rows))
        unread = [row["name"] for row in rows if row.get("failed") is None]
        if unread:
            missing.append(f"the runs of {_and(unread)}")
        if any("no_answer" in row and row["no_answer"] is None for row in rows):
            missing.append("the reviews")
    note = [f"{_and(missing)} were not read."] if missing else []
    if partial and required is not None:
        note.append(PARTLY)
    return _settle("agents", found, " ".join(note))


def light_queue(waiting: list[dict] | None, complete: bool = True) -> dict:
    """`complete` is False when a fact the list is made from was not read, so `waiting` may
    hold only part of what waits."""
    if waiting is None:
        return _light("queue", "grey", "Not measured yet: what waits for you was not read.")
    days = max((item["days"] for item in waiting), default=0)
    found = None
    if days > 3.5:
        state = "red" if days > 7 else "amber"
        found = _light("queue", state, f"Something has waited {days} days for you.")
    missing = "" if complete else "not all of what could wait for you was read."
    return _settle("queue", [found], missing)


def overall(states: list[str]) -> str:
    return next((state for state in ORDER if state in states), "grey")


# --- What waits for the owner ---


def _wait(kind: str, title: str, url: str, days: float) -> dict:
    return {"kind": kind, "title": title, "url": url, "do": DO[kind], "days": days}


def _title(item: dict) -> str:
    """The item's own title, white space collapsed to single spaces, cut to TITLE_LENGTH."""
    return " ".join((item.get("title") or "").split())[:TITLE_LENGTH]


def _issue_waits(kind: str, items: list[dict], now: datetime) -> list[dict]:
    items = sorted(items, key=_opened)
    return [_wait(kind, _title(item), item["html_url"], _days(item["created_at"], now))
            for item in items]


def _agent_pulls(pulls: list[dict]) -> list[dict]:
    return [
        item for item in pulls
        if item["state"] == "open" and _by_a_bot(item)
        and item["head"]["ref"].startswith(("agent/", "prepare-v"))
    ]


def _spot_check(reviews: list[Review], now: datetime) -> list[dict]:
    """The clean review merged last in the 7 days before this Monday, until the owner votes on
    any clean review of those days (spec 2.4)."""
    monday = _monday(now)
    week = [
        r for r in reviews
        if r.clean and r.merged and monday - timedelta(days=7) <= _at(r.merged) < monday
    ]
    if not week or any(r.up or r.down for r in week):
        return []
    last = max(week, key=lambda r: (_at(r.merged), r.pr))
    url = f"https://github.com/{REPO}/pull/{last.pr}"
    days = round((now - monday).total_seconds() / 86400, 1)
    return [_wait("spot-check", f"#{last.pr}, reviewed with no findings", url, days)]


def waiting(issues: list[dict] | None, pulls: list[dict] | None,
            reviews: list[Review] | None, now: datetime) -> list[dict] | None:
    """What the owner must do, in the order of DO, oldest first inside each kind; without
    `reviews`, everything but the spot check. None without `issues` or `pulls`: a part of
    the list would read as the whole of it."""
    if issues is None or pulls is None:
        return None
    return _waits(issues, pulls, reviews, _utc(now))


def _waits(issues: list[dict] | None, pulls: list[dict] | None,
           reviews: list[Review] | None, now: datetime) -> list[dict]:
    """Every waiting item the facts that were read give; the Queue light reads this."""
    verdictless = [
        item for item in _findings(issues or [], open_only=True)
        if not names(item) & set(VERDICTS)
    ]
    return [
        *_issue_waits("pull", _agent_pulls(pulls or []), now),
        *_issue_waits("verdict", verdictless, now),
        *_issue_waits("release", _bots(issues or [], "release"), now),
        *_issue_waits("paused", _pauses(issues or []), now),
        *([] if reviews is None else _spot_check(reviews, now)),
    ]


# --- Numbers ---


def use(issues: list[dict] | None, pulls: list[dict] | None,
        stars: int | None, downloads: int | None, now: datetime) -> dict:
    """Issues and pull requests other people opened this month; stars and downloads as given."""
    now = _utc(now)
    month = _month(now)

    def count(items):
        if items is None:
            return None
        return sum(1 for item in items
                   if _by_a_person_not_the_owner(item) and _month(_at(item["created_at"])) == month)

    return {"issues_from_others": count(issues), "pulls_from_others": count(pulls),
            "stars": stars, "downloads": downloads}


def _reviewer_week(agent: str, reviews: list[Review] | None, silent: list[Review] | None,
                   now: datetime) -> dict:
    """What the reviewer did in 7 days, and in how many review comments of those days it
    gave no answer (None unless both kinds of comment were read)."""
    if reviews is None:
        return {"did": None, "agreed": None, "disagreed": None, "no_answer": None}

    def recent(r: Review) -> bool:
        return bool(r.updated) and _age(r.updated, now) <= 7

    answered = [r for r in reviews if r.counts.get(agent) is not None and recent(r)]
    no_answer = None if silent is None else sum(
        1 for r in [*reviews, *silent] if r.counts.get(agent) is None and recent(r))
    return {"did": len(answered), "agreed": sum(r.up for r in answered),
            "disagreed": sum(r.down for r in answered), "no_answer": no_answer}


def _watcher_week(issues: list[dict] | None, now: datetime) -> dict:
    if issues is None:
        return {"did": None, "agreed": None, "disagreed": None}
    found = _findings(issues)
    month = [item for item in found if _age(item["created_at"], now) <= 30]
    return {"did": sum(1 for item in found if _age(item["created_at"], now) <= 7),
            "agreed": sum("confirmed" in names(item) for item in month),
            "disagreed": sum("false-alarm" in names(item) for item in month)}


def _release_week(pulls: list[dict] | None, now: datetime) -> dict:
    did = None if pulls is None else sum(
        1 for item in pulls
        if _by_a_bot(item) and item["head"]["ref"].startswith("prepare-v")
        and _age(item["created_at"], now) <= 7
    )
    return {"did": did, "agreed": None, "disagreed": None}


def week(roster: dict, reviews: list[Review] | None, issues: list[dict] | None,
         pulls: list[dict] | None, runs: dict[str, int | None], now: datetime,
         failed: dict[str, int | None] | None = None,
         silent: list[Review] | None = None) -> list[dict]:
    """One row per roster agent: its runs that ended and those that failed, what it did in 7
    days, and the owner's answers; for a reviewer also `no_answer` (see _reviewer_week)."""
    now = _utc(now)
    failed = failed or {}
    rows = []
    for agent in roster["agents"]:
        agent_id = agent["id"]
        if agent_id in REVIEWERS:
            did = _reviewer_week(agent_id, reviews, silent, now)
        elif agent_id == "watcher":
            did = _watcher_week(issues, now)
        elif agent_id == "release-prep":
            did = _release_week(pulls, now)
        else:
            did = {"did": None, "agreed": None, "disagreed": None}
        rows.append({"agent": agent_id, "name": agent["name"], "runs": runs.get(agent_id),
                     "failed": failed.get(agent_id), **did})
    return rows


def _found_in(month: str, reviews: list[Review] | None, issues: list[dict] | None) -> dict:
    row = {"month": month, "review": None, "nightly": None, "tester": None,
           "watcher": None, "owner": None, "others": None}
    if reviews is not None:
        merged = [r for r in reviews if r.merged and _month(_at(r.merged)) == month]
        row["review"] = summary(merged)["fixed"]
    if issues is not None:
        opened = [item for item in issues if _month(_at(item["created_at"])) == month]
        bugs = [item for item in opened if "bug" in names(item)]
        row["watcher"] = len(_bots(opened, "client-change", "confirmed", open_only=False))
        row["owner"] = sum(1 for item in bugs if _login(item).lower() == MAINTAINER.lower())
        row["others"] = sum(1 for item in bugs if _by_a_person_not_the_owner(item))
    return row


def found_by(reviews: list[Review] | None, issues: list[dict] | None,
             now: datetime) -> list[dict]:
    """Who found what, this month and the two before, newest first."""
    now = _utc(now)
    return [_found_in(_month(now, back), reviews, issues) for back in range(3)]


def _causes(body: str) -> list[int]:
    """Every pull request named under the form's `### Caused by`, up to the next heading."""
    section = CAUSED_BY.search(body)
    if not section:
        return []
    return sorted({int(a or b) for a, b in REFERENCE.findall(section.group(1))})


def misses(issues: list[dict] | None, reviews: list[Review] | None,
           now: datetime) -> list[dict] | None:
    """Bugs opened in the last 30 days whose form says a reviewed pull request caused them."""
    now = _utc(now)
    if issues is None or reviews is None:
        return None
    reviewed = {r.pr for r in reviews}
    found = []
    for item in sorted(issues, key=lambda item: item["number"]):
        if "bug" not in names(item) or _age(item["created_at"], now) > 30:
            continue
        for pull in _causes(item.get("body") or ""):
            if pull in reviewed:
                found.append({"issue": item["number"], "pull": pull, "url": item["html_url"]})
    return found


# --- The whole desk ---


def build(facts: Facts, roster: dict, now: datetime) -> dict:
    """desk.json, version 1."""
    now = _utc(now)
    wait = waiting(facts.issues, facts.pulls, facts.reviews, now)
    rows = week(roster, facts.reviews, facts.issues, facts.pulls, facts.runs, now,
                failed=facts.failed, silent=facts.silent)
    lights = [
        light_works(facts.checks, facts.required, facts.required_partial),
        light_clients(facts.issues, facts.watch_log, now),
        light_bugs(facts.issues, now),
        light_agents(facts.issues, facts.required, now, facts.required_partial, rows),
        light_queue(_waits(facts.issues, facts.pulls, facts.reviews, now),
                    complete=None not in (facts.issues, facts.pulls, facts.reviews)),
    ]
    review = (summary(facts.reviews) if facts.reviews is not None
              else {"clean": None, "fixed": None, "days_to_merge": None})
    return {
        "version": 1,
        "updated": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "repo": facts.repo,
        "overall": overall([light["state"] for light in lights]),
        "lights": lights,
        "use": use(facts.issues, facts.pulls, facts.stars, facts.downloads, now),
        "waiting": wait,
        "week": rows,
        "review": review,
        "found_by": found_by(facts.reviews, facts.issues, now),
        "misses": misses(facts.issues, facts.reviews, now),
        "budget": {
            "agents": [{"agent": a["id"], "runs": facts.runs.get(a["id"]), "cap": a["cap"]}
                       for a in roster["agents"]],
            "keys": roster["keys"],
        },
    }
