"""The bench: what the desk page shows beside the five lights. No model, no network.

Pure: the caller (desk_gather.py) reads GitHub and the stores and passes what it read; nothing
here reads the clock, a file or the network. A fact that was not read is None, and what needs it
is grey or None, never good news.

- `record` turns one scheduled run of a nightly workflow into a line of the history: each job's
  state, the step that failed, the version on main at that commit, and the start-up times the
  job's log printed.
- `merge` keeps the history (history.json on the `numbers` branch) to the newest KEEP_RUNS runs.
- `bench` builds what the page shows: the checks of main's newest push, the nightly rows with
  their last NIGHTS nights, the start-up times by release and system, the stores, the bugs and
  the upstream changes.

Every text here is ours or a job's or step's name from Kitden's own workflows; titles written by
a person or a model never reach this file.
"""

import re
import statistics
from datetime import UTC, date, datetime

NIGHTS = 14  # the nights each row's strip shows
KEEP_RUNS = 120  # runs kept in history.json, across both workflows
NIGHT_DAYS = 1  # desk.NIGHT_DAYS: a newest run older than this means GitHub skipped a night
LOG_TRIES = 3  # a log that could not be read is tried again on this many days, then left
RED = ("failure", "timed_out", "action_required", "startup_failure")
GREEN = ("success",)
# Kitden's runners, as the nightly names them, and how the page names them: OS, architecture.
SYSTEMS = (
    ("macos-latest", "macOS", "arm64"),
    ("macos-15-intel", "macOS", "x86_64 (Intel)"),
    ("ubuntu-latest", "Linux", "x86_64"),
    ("ubuntu-24.04-arm", "Linux", "arm64"),
)
PYTHONS = ("3.13", "3.14")
CLIENT_SYSTEMS = (("macos-latest", "macOS"), ("ubuntu-latest", "Linux"))
STARTUP_STEP = "Run uv run python scripts/measure-start.py"
# The jobs that run STARTUP_STEP: the nightly's systems jobs, and release.yml's build jobs,
# whose run on a release tag measures that release.
MEASURING = ("systems", "build", "startup")
MEASURED_IN = ("nightly.yml", "release.yml", "startup-history.yml")
# Kept for good, however many nightly runs come after: each is one release's own measure.
KEPT = ("release.yml", "startup-history.yml")
TAG = re.compile(r"v(\d+\.\d+\.\d+)")
# What measure-start.py prints, one line each, after the log's timestamp.
STARTUP_LINE = re.compile(
    r"^\S+\s+(first usable|complete|demo \(medium\)): (\d+(?:\.\d+)?) s \(budget", re.M)
STARTUP_KEYS = {"first usable": "first", "complete": "complete", "demo (medium)": "demo"}
BUDGETS = {"first": 2.0, "complete": 5.0}  # docs/development.md in Kitden, Speed
VERSION = re.compile(r'^version\s*=\s*"(\d+\.\d+\.\d+)"', re.M)
JOB = re.compile(r"^([\w-]+)(?: \(([^)]*)\))?$")
ESCAPES = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
# The steps of Kitden's build job on main, by the start of their name, and how the page names
# them. A step not listed here is not shown; one listed but missing is not shown either.
GATE_STEPS = (
    ("Lint", ("Run uv run ruff check", "Run uv run ruff format")),
    ("Types", ("Run uv run pyright",)),
    ("Tests", ("Run uv run pytest",)),
    ("Real keyring", ("The real keyring",)),
    ("Page tests", ("Run node --test",)),
    ("Start-up time", ("Run uv run python scripts/measure-start.py",)),
    ("Workflow security", ("Run uvx zizmor",)),
    ("Dependency audit", ("Run uv run --with pip-audit",)),
    ("Release check", ("The release check",)),
    ("Package", ("Run uv build", "The built files", "The wheel runs")),
)
WORST = ("red", "grey", "green")  # the first one any part has is the whole's state


# --- Small pieces ---


def state(conclusion) -> str:
    """A job's or step's state: red when it failed, green when it passed, grey otherwise (not
    finished, cancelled, skipped, or not read)."""
    if conclusion in RED:
        return "red"
    return "green" if conclusion in GREEN else "grey"


def worst(states) -> str:
    found = [s for s in states if s in WORST]
    return min(found, key=WORST.index) if found else "none"


def _text(value) -> str | None:
    return " ".join(value.split()) if isinstance(value, str) and value.strip() else None


def _day(text) -> str | None:
    if not isinstance(text, str):
        return None
    try:
        return datetime.fromisoformat(text).astimezone(UTC).date().isoformat()
    except ValueError:
        return None


def job_parts(name: str) -> tuple[str, tuple[str, ...]]:
    """("systems", ("macos-latest", "3.14")) for "systems (macos-latest, 3.14)"."""
    found = JOB.match(name or "")
    if not found:
        return name or "", ()
    args = tuple(a.strip() for a in (found.group(2) or "").split(",") if a.strip())
    return found.group(1), args


def version_of(pyproject: str) -> str | None:
    found = VERSION.search(pyproject)
    return found.group(1) if found else None


def startup_times(log: str) -> dict[str, float] | None:
    """The times measure-start.py printed in a job's log; None when it printed none of them."""
    found = {}
    for name, seconds in STARTUP_LINE.findall(ESCAPES.sub("", log)):
        found[STARTUP_KEYS[name]] = float(seconds)
    return found or None


def _semver(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in version.split("."))


# --- The history ---


def _failed_step(job: dict) -> str | None:
    return next((_text(step.get("name")) for step in job.get("steps") or []
                 if isinstance(step, dict) and step.get("conclusion") in RED), None)


def _step_state(job: dict, step_name: str) -> str | None:
    step = next((s for s in job.get("steps") or []
                 if isinstance(s, dict) and s.get("name") == step_name), None)
    return None if step is None else state(step.get("conclusion"))


def record(workflow: str, run: dict, jobs: list[dict], version: str | None,
           startup: dict[str, dict[str, float]], unread: int = 0, tries: int = 0) -> dict:
    """One line of the history for a finished run. `startup` maps a job's name to the times its
    log printed; `unread` counts the measuring jobs whose log could not be read, so the line is
    read again later (`tries` times so far)."""
    return {
        "id": run["id"],
        "attempt": run.get("run_attempt") if isinstance(run.get("run_attempt"), int) else 1,
        "unread_logs": unread,
        "tries": tries,
        "workflow": workflow,
        "night": _day(run.get("created_at")),
        "sha": _text(run.get("head_sha")),
        "version": version,
        "url": _text(run.get("html_url")),
        "jobs": [
            {
                "name": _text(job.get("name")) or "?",
                "state": state(job.get("conclusion")),
                "url": _text(job.get("html_url")),
                "failed_step": _failed_step(job),
                "startup": _step_state(job, STARTUP_STEP),
                **({"times": startup[job["name"]]} if job.get("name") in startup else {}),
            }
            for job in jobs if isinstance(job, dict)
        ],
    }


def merge(history: list[dict], new: list[dict], keep: int = KEEP_RUNS) -> list[dict]:
    """The history with the new runs, one line per run id, oldest first: every release, and the
    newest `keep` nightly runs. A release is one line each and is the start-up trend's base."""
    by_id = {line["id"]: line for line in history if isinstance(line, dict) and "id" in line}
    by_id.update({line["id"]: line for line in new})
    lines = sorted(by_id.values(), key=lambda line: (line.get("night") or "", line["id"]))
    nights = [line for line in lines if line.get("workflow") not in KEPT][-keep:]
    kept = {line["id"] for line in nights}
    return [line for line in lines if line.get("workflow") in KEPT or line["id"] in kept]


# --- The rows of the nightly bench ---


def _jobs(line: dict, match) -> list[dict]:
    return [job for job in line.get("jobs") or [] if match(*job_parts(job.get("name", "")))]


def _row_state(line: dict | None, match, key: str = "state") -> str:
    if line is None:
        return "none"
    return worst(job.get(key) or "grey" for job in _jobs(line, match)) if _jobs(line, match) \
        else "none"


def _since(lines: list[dict], match, key: str) -> str | None:
    """The night a red row turned red. As in desk.py, a grey night in between (no finished run,
    or none of its jobs) proves no fix: the red keeps its first night; a green night ends it."""
    since = None
    for line in reversed(lines):
        found = _row_state(line, match, key)
        if found == "green":
            break
        if found == "red":
            since = line.get("night")
    return since


def _row(group: str, name: str, cells: list[tuple[str, object]], lines: list[dict],
         now: date, key: str = "state") -> dict:
    """A row: its cells (label, match) now, its state, and its last NIGHTS nights."""
    newest = lines[-1] if lines else None
    old = newest is None or newest.get("night") is None or \
        (now - date.fromisoformat(newest["night"])).days > NIGHT_DAYS

    def match_any(part, args):
        return any(m(part, args) for _, m in cells)

    out_cells = []
    for label, match in cells:
        jobs = _jobs(newest, match) if newest else []
        # The newest night without the cell's job (renamed, or not run) proves nothing: grey.
        cell_state = "grey" if old or not jobs else _row_state(newest, match, key)
        out_cells.append({"label": label, "state": cell_state,
                          "url": next((j.get("url") for j in jobs if j.get("url")), None)})
    row_state = "grey" if old else worst(c["state"] for c in out_cells)
    failed = []
    if newest and row_state == "red":
        failed = [{"job": j["name"], "step": j.get("failed_step"), "url": j.get("url")}
                  for j in _jobs(newest, match_any) if (j.get(key) or "grey") == "red"]
    return {
        "group": group,
        "name": name,
        "state": row_state,
        "cells": out_cells,
        "since": _since(lines, match_any, key) if row_state == "red" else None,
        "failed": failed,
        "night": newest.get("night") if newest else None,
        "url": newest.get("url") if newest else None,
        "nights": [{"night": line.get("night"), "state": _row_state(line, match_any, key),
                    "url": line.get("url")} for line in lines[-NIGHTS:]],
    }


def _is(part: str, *args: str):
    return lambda p, a: p == part and tuple(a[:len(args)]) == args


def rows(history: list[dict], now: datetime) -> list[dict] | None:
    """The bench's rows, in the page's order. None without a history."""
    if not history:
        return None
    today = now.astimezone(UTC).date()
    nightly = [line for line in history if line.get("workflow") == "nightly.yml"]
    deps = [line for line in history if line.get("workflow") == "latest-deps.yml"]
    found = []
    for runner, os_name, arch in SYSTEMS:
        found.append(_row("platforms", f"{os_name} · {arch}",
                          [(f"Python {py}", _is("systems", runner, py)) for py in PYTHONS],
                          nightly, today))
    found.append(_row("platforms", "End-to-end in Chromium",
                      [("Linux · x86_64", _is("browser"))], nightly, today))
    found.append(_row("platforms", "Start-up time",
                      [(f"{os_name} · {arch.split(' ')[0]}", _is("systems", runner))
                       for runner, os_name, arch in SYSTEMS], nightly, today, key="startup"))
    found.append(_row("compatibility", "Claude Code and Codex, newest",
                      [(os_name, _is("clients", runner)) for runner, os_name in CLIENT_SYSTEMS],
                      nightly, today))
    found.append(_row("compatibility", "Newest dependencies",
                      [("macOS · arm64", _is("test"))], deps, today))
    return found


# --- Start-up times by release ---


def startup(history: list[dict]) -> dict | None:
    """Per system, the median of each time measured on each release: its build on its tag
    (release.yml: macOS arm64 and Linux x86_64) and the nights main was at that release's own
    commit (the nightly: every system, both Pythons). A night on a later commit belongs to no
    release: the newest such night is the last point, "main", so a slowdown merged after a
    release shows before the next one. None when nothing printed a time."""
    releases = {line.get("sha"): line.get("version") for line in history
                if line.get("workflow") == "release.yml" and isinstance(line.get("version"), str)
                and line.get("sha")}
    values: dict[tuple[str, str, str], list[float]] = {}

    def take(line: dict, point: str | None) -> bool:
        """The line's times under `point`; a job whose name ends in a release tag (the
        startup-history workflow) counts for that release instead."""
        took = False
        for job in line.get("jobs") or []:
            part, args = job_parts(job.get("name", ""))
            times = job.get("times")
            if part not in MEASURING or not args or not isinstance(times, dict):
                continue
            tagged = next((m.group(1) for a in args[1:] if (m := TAG.fullmatch(a))), None)
            at = tagged or point
            if at is None:
                continue
            for key in ("first", "complete"):
                if isinstance(times.get(key), int | float) and not isinstance(times[key], bool):
                    values.setdefault((args[0], at, key), []).append(float(times[key]))
                    took = True
        return took

    later = None
    for line in history:
        workflow = line.get("workflow")
        if workflow == "release.yml" and isinstance(line.get("version"), str):
            take(line, line["version"])
        elif workflow == "startup-history.yml":
            take(line, None)  # each job names its release
        elif workflow == "nightly.yml":
            if line.get("sha") in releases:
                take(line, releases[line["sha"]])
            elif any(isinstance(job.get("times"), dict) for job in line.get("jobs") or []):
                later = line  # the history is oldest first: the last one is the newest
    if later is not None:
        take(later, "main")
    if not values:
        return None
    points = sorted({p for _, p, _ in values if p != "main"}, key=_semver)
    if any(p == "main" for _, p, _ in values):
        points.append("main")
    systems = []
    for runner, os_name, arch in SYSTEMS:
        def median(key, point, runner=runner):
            got = values.get((runner, point, key))
            return round(statistics.median(got), 2) if got else None
        systems.append({
            "id": runner, "os": os_name, "arch": arch,
            "first": [median("first", p) for p in points],
            "complete": [median("complete", p) for p in points],
            "runs": [len(values.get((runner, p, "first"), ())) for p in points],
        })
    return {"versions": points, "systems": systems, "budgets": BUDGETS,
            "main_night": later.get("night") if later else None}


# --- The checks of main's newest push ---


def gate(jobs: list[dict] | None, run: dict | None) -> dict | None:
    """Each step of GATE_STEPS: red when it failed on any build job, green when it passed on
    every one it ran on; a step that never ran is left out. A build job that failed on a step
    GATE_STEPS does not name adds "Other" with that step's name, so a red job is never shown
    green. Each step links the job where it is worst. None when the jobs were not read."""
    if jobs is None or run is None:
        return None
    builds = [job for job in jobs if isinstance(job, dict)
              and job_parts(job.get("name", ""))[0] == "build"]
    steps = []
    named = tuple(start for _, starts in GATE_STEPS for start in starts)
    for label, starts in GATE_STEPS:
        found = []  # (state, url)
        for job in builds:
            for step in job.get("steps") or []:
                name = step.get("name") if isinstance(step, dict) else None
                if isinstance(name, str) and name.startswith(starts) \
                        and step.get("conclusion") != "skipped":
                    found.append((state(step.get("conclusion")), _text(job.get("html_url"))))
        if found:
            worst_state = worst(s for s, _ in found)
            url = next(u for s, u in found if s == worst_state)
            steps.append({"name": label, "state": worst_state, "url": url})
    for job in builds:
        failed = _failed_step(job)
        if state(job.get("conclusion")) == "red" and not (failed or "").startswith(named):
            steps.append({"name": f"Other: {failed}" if failed else "Other: the job failed",
                          "state": "red", "url": _text(job.get("html_url"))})
    job_states = [state(job.get("conclusion")) for job in builds]
    return {
        "sha": _text(run.get("head_sha")),
        "at": _text(run.get("updated_at")) or _text(run.get("created_at")),
        "url": _text(run.get("html_url")),
        "state": worst([*(s["state"] for s in steps), *job_states]) if steps or job_states
        else "grey",
        "steps": steps,
    }


# --- Bugs and upstream changes ---


def _labels(item: dict) -> set[str]:
    return {label.get("name") for label in item.get("labels") or [] if isinstance(label, dict)}


def bugs(issues: list[dict] | None, repo: str) -> dict | None:
    if issues is None:
        return None
    open_bugs = [i for i in issues if i.get("state") == "open" and "bug" in _labels(i)]
    return {"open": len(open_bugs),
            "url": f"https://github.com/{repo}/issues?q=is%3Aissue+is%3Aopen+label%3Abug"}


def upstream(issues: list[dict] | None, watch_days: float | None, repo: str) -> dict | None:
    """The watcher's open client changes: confirmed ones Kitden has not met yet, and those
    still waiting for a verdict; how many days ago the watcher last read the release notes."""
    if issues is None:
        return None
    changes = [i for i in issues if i.get("state") == "open"
               and "client-change" in _labels(i) and "summary" not in _labels(i)]
    return {
        "confirmed": sum(1 for i in changes if "confirmed" in _labels(i)),
        "unconfirmed": sum(1 for i in changes if "confirmed" not in _labels(i)),
        "watcher_days": None if watch_days is None else round(watch_days, 1),
        "url": f"https://github.com/{repo}/issues?q=is%3Aissue+is%3Aopen+label%3Aclient-change",
    }


# --- The stores ---


def stores(newest: dict | None, seen: dict[str, dict | None]) -> dict:
    """Each store's version against the newest release. `seen` maps a store id to what was read
    there ({"version", "at", "url"}), or None when it could not be read."""
    version = newest.get("version") if newest else None
    names = (("pypi", "PyPI"), ("homebrew", "Homebrew"), ("registry", "MCP Registry"),
             ("glama", "Glama"), ("mcprush", "MCP Rush"))
    out = []
    for store_id, name in names:
        got = seen.get(store_id)
        if got is None:
            out.append({"id": store_id, "name": name, "state": "grey", "version": None,
                        "at": None, "url": None, "note": "Could not be read"})
            continue
        listed_only = got.get("version") is None
        if listed_only:
            store_state = "green" if got.get("listed") else "grey"
        else:
            # Without the newest release there is nothing to compare with: grey, not amber.
            store_state = "grey" if not version else \
                "green" if got["version"] == version else "amber"
        out.append({"id": store_id, "name": name, "state": store_state,
                    "listed": bool(got.get("listed")), "version": got.get("version"),
                    "at": got.get("at"), "url": got.get("url"), "note": got.get("note")})
    out.append({"id": "claude-plugin", "name": "Claude plugin", "state": "planned",
                "version": None, "at": None, "url": None, "note": "Not published yet"})
    return {"newest": newest, "stores": out}


def bench(history: list[dict] | None, now: datetime, *, gate_read: dict | None,
          newest: dict | None, seen: dict[str, dict | None], issues: list[dict] | None,
          watch_days: float | None, repo: str) -> dict:
    """Everything the page shows beside the lights, as desk.json's `bench`."""
    return {
        "gate": gate_read,
        "rows": rows(history or [], now),
        "startup": startup(history or []),
        "stores": stores(newest, seen),
        "bugs": bugs(issues, repo),
        "upstream": upstream(issues, watch_days, repo),
    }

