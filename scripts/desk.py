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
TITLE_LENGTH = 100
DO = {
    "pull": "Review it and merge, or close it.",
    "verdict": "Put `confirmed` on it, or close it with `false-alarm`.",
    "release": "Do what it says under What to do.",
    "paused": "Close it to start the agent again.",
    "spot-check": "Look at the change, then 👍 or 👎 on its Agent review comment.",
}
CAUSED_BY = re.compile(
    rf"###\s*Caused by\s*\n\s*(?:#(\d+)|https://github\.com/{re.escape(REPO)}/pull/(\d+))\b",
    re.IGNORECASE,
)


@dataclass
class Facts:
    """What was read. None means the read failed or was never made."""

    issues: list[dict] | None = None  # every Kitden issue, open and closed, no pull requests
    pulls: list[dict] | None = None  # pull requests updated in the last 90 days
    reviews: list[Review] | None = None
    checks: list[dict] | None = None  # check runs of main's newest commit
    required: list[str] | None = None  # the checks main requires
    runs: dict[str, int | None] = field(default_factory=dict)  # agent id -> runs, last 7 days
    watch_log: list[dict] | None = None  # the watcher's log.jsonl
    stars: int | None = None
    downloads: int | None = None  # PyPI, last month


# --- Time and who wrote what ---


def _at(text: str) -> datetime:
    return datetime.fromisoformat(text).astimezone(UTC)


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
    return _login(item).endswith("[bot]")


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


def _light(light_id: str, state: str, why: str = "") -> dict:
    return {"id": light_id, "name": light_id.capitalize(), "state": state, "why": why}


def _worst(*lights: dict | None) -> dict | None:
    """The light with the worst state; None when none is given."""
    given = [light for light in lights if light]
    return min(given, key=lambda light: ORDER.index(light["state"]), default=None)


def _settle(light_id: str, found: list[dict | None], missing: str = "") -> dict:
    """The worst light the read facts prove; else grey when `missing` names a fact that was not
    read and could have shown something bad; else green."""
    worst = _worst(*found)
    if worst:
        return worst
    if missing:
        return _light(light_id, "grey", f"Not measured yet: {missing}")
    return _light(light_id, "green")


def _limits(light_id: str, item: dict | None, now: datetime, amber: float, red: float,
            what: str) -> dict | None:
    """Red past `red` days, amber past `amber`, for the oldest `item`; None when neither."""
    if item is None or _age(item["created_at"], now) <= amber:
        return None
    state = "red" if _age(item["created_at"], now) > red else "amber"
    days = _days(item["created_at"], now)
    return _light(light_id, state, f"Issue #{item['number']} {what} has been open {days} days.")


def light_works(checks: list[dict] | None) -> dict:
    if not checks:
        return _light("works", "grey", "Not measured yet: no check run of main was read.")
    failed = sorted({c["name"] for c in checks if c.get("conclusion") in RED_ENDINGS})
    if failed:
        return _light("works", "red", f"On main, {', '.join(failed)} failed.")
    running = sorted({c["name"] for c in checks if c.get("status") != "completed"})
    if running:
        return _light("works", "amber", f"On main, {', '.join(running)} has not finished.")
    odd = sorted({c["name"] for c in checks if c.get("conclusion") not in GOOD_ENDINGS})
    if odd:
        return _light("works", "amber", f"On main, {', '.join(odd)} ended neither well nor badly.")
    return _light("works", "green")


def _log_day(line: dict) -> datetime | None:
    """The start of the day a log line gives, in UTC; None when it gives none."""
    try:
        return datetime.fromisoformat(line["date"] + "T00:00:00+00:00")
    except (KeyError, TypeError, ValueError):
        return None


def _watch_log_age(watch_log: list[dict] | None, now: datetime) -> float | None:
    """Days since the start of the day of the watcher's newest log line; None without one.
    A line dated after `now` is not believed."""
    days = [day for day in map(_log_day, watch_log or []) if day and day <= now]
    if not days:
        return None
    return (now - max(days)).total_seconds() / 86400


def light_clients(issues: list[dict] | None, watch_log: list[dict] | None, now: datetime) -> dict:
    if issues is None:
        return _light("clients", "grey", "Not measured yet: the issues were not read.")
    late = _oldest(_bots(issues, "client-change", "confirmed", "major"))
    found = _limits("clients", late, now, 3.5, 7, "(a confirmed major client change)")
    age = _watch_log_age(watch_log, now)
    stale = age is None or age > WATCH_LOG_DAYS
    missing = f"the watcher logged no run in the last {WATCH_LOG_DAYS} days." if stale else ""
    return _settle("clients", [found], missing)


def _open_bugs_on(issues: list[dict], monday: datetime) -> int:
    """Open `bug` issues at that Monday 00:00: opened before it and not closed before it."""
    return sum(
        1 for item in issues
        if "bug" in names(item) and _at(item["created_at"]) < monday
        and not (item.get("closed_at") and _at(item["closed_at"]) < monday)
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
    if issues is None:
        return _light("bugs", "grey", "Not measured yet: the issues were not read.")
    late = _oldest(_bots(issues, "confirmed", "major"))
    return _settle("bugs", [_limits("bugs", late, now, 7, 14, "(confirmed and major)"),
                            _bugs_grew(issues, now)])


def _required_agents(required: list[str]) -> dict | None:
    reviews = sorted(name for name in required if name.startswith("review /"))
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
    return _light("agents", "amber", f"Issue #{paused['number']} says an agent is paused.")


def light_agents(issues: list[dict] | None, required: list[str] | None, now: datetime) -> dict:
    found, missing = [], []
    if required is None:
        missing.append("main's rules")
    else:
        found.append(_required_agents(required))
    if issues is None:
        missing.append("the issues")
    else:
        found += [_watcher_over_cap(issues, now), _paused_agent(issues)]
    return _settle("agents", found, f"{' and '.join(missing)} were not read." if missing else "")


def light_queue(waiting: list[dict] | None, complete: bool = True) -> dict:
    """`complete` is False when the list could not hold everything: the reviews were not read,
    so it has no spot check."""
    if waiting is None:
        return _light("queue", "grey", "Not measured yet: what waits for you was not read.")
    days = max((item["days"] for item in waiting), default=0)
    found = None
    if days > 3.5:
        state = "red" if days > 7 else "amber"
        found = _light("queue", state, f"Something has waited {days} days for you.")
    missing = "" if complete else "the reviews were not read, so there is no spot check."
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
    `reviews`, everything but the spot check."""
    if issues is None or pulls is None:
        return None
    verdictless = [
        item for item in _findings(issues, open_only=True) if not names(item) & set(VERDICTS)
    ]
    return [
        *_issue_waits("pull", _agent_pulls(pulls), now),
        *_issue_waits("verdict", verdictless, now),
        *_issue_waits("release", _bots(issues, "release"), now),
        *_issue_waits("paused", _pauses(issues), now),
        *([] if reviews is None else _spot_check(reviews, now)),
    ]


# --- Numbers ---


def use(issues: list[dict] | None, pulls: list[dict] | None,
        stars: int | None, downloads: int | None, now: datetime) -> dict:
    """Issues and pull requests other people opened this month; stars and downloads as given."""
    month = _month(now)

    def count(items):
        if items is None:
            return None
        return sum(1 for item in items
                   if _by_a_person_not_the_owner(item) and _month(_at(item["created_at"])) == month)

    return {"issues_from_others": count(issues), "pulls_from_others": count(pulls),
            "stars": stars, "downloads": downloads}


def _reviewer_week(agent: str, reviews: list[Review] | None, now: datetime) -> dict:
    if reviews is None:
        return {"did": None, "agreed": None, "disagreed": None}
    answered = [
        r for r in reviews
        if r.counts.get(agent) is not None and r.updated and _age(r.updated, now) <= 7
    ]
    return {"did": len(answered), "agreed": sum(r.up for r in answered),
            "disagreed": sum(r.down for r in answered)}


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
         pulls: list[dict] | None, runs: dict[str, int | None], now: datetime) -> list[dict]:
    """One row per roster agent: its runs, what it did in 7 days, and the owner's answers."""
    rows = []
    for agent in roster["agents"]:
        agent_id = agent["id"]
        if agent_id in REVIEWERS:
            did = _reviewer_week(agent_id, reviews, now)
        elif agent_id == "watcher":
            did = _watcher_week(issues, now)
        elif agent_id == "release-prep":
            did = _release_week(pulls, now)
        else:
            did = {"did": None, "agreed": None, "disagreed": None}
        rows.append({"agent": agent_id, "name": agent["name"], "runs": runs.get(agent_id), **did})
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
    return [_found_in(_month(now, back), reviews, issues) for back in range(3)]


def misses(issues: list[dict] | None, reviews: list[Review] | None,
           now: datetime) -> list[dict] | None:
    """Bugs opened in the last 30 days whose form says a reviewed pull request caused them."""
    if issues is None or reviews is None:
        return None
    reviewed = {r.pr for r in reviews}
    found = []
    for item in sorted(issues, key=lambda item: item["number"]):
        if "bug" not in names(item) or _age(item["created_at"], now) > 30:
            continue
        cause = CAUSED_BY.search(item.get("body") or "")
        pull = cause and int(cause.group(1) or cause.group(2))
        if pull in reviewed:
            found.append({"issue": item["number"], "pull": pull, "url": item["html_url"]})
    return found


# --- The whole desk ---


def build(facts: Facts, roster: dict, now: datetime) -> dict:
    """desk.json, version 1."""
    wait = waiting(facts.issues, facts.pulls, facts.reviews, now)
    lights = [
        light_works(facts.checks),
        light_clients(facts.issues, facts.watch_log, now),
        light_bugs(facts.issues, now),
        light_agents(facts.issues, facts.required, now),
        light_queue(wait, complete=facts.reviews is not None),
    ]
    review = (summary(facts.reviews) if facts.reviews is not None
              else {"clean": None, "fixed": None, "days_to_merge": None})
    return {
        "version": 1,
        "updated": now.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "repo": REPO,
        "overall": overall([light["state"] for light in lights]),
        "lights": lights,
        "use": use(facts.issues, facts.pulls, facts.stars, facts.downloads, now),
        "waiting": wait,
        "week": week(roster, facts.reviews, facts.issues, facts.pulls, facts.runs, now),
        "review": review,
        "found_by": found_by(facts.reviews, facts.issues, now),
        "misses": misses(facts.issues, facts.reviews, now),
        "budget": {
            "agents": [{"agent": a["id"], "runs": facts.runs.get(a["id"]), "cap": a["cap"]}
                       for a in roster["agents"]],
            "keys": roster["keys"],
        },
    }
