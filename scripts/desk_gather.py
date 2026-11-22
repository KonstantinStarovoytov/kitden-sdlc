"""Read the desk's facts from GitHub and from files, and write desk.json, numbers.md and
numbers.json.

Each fact is read on its own. One that cannot be read is None, never a default that looks like
good news: it prints one `::warning::` line naming the field (never a token or an answer's text),
the other reads still run, and desk.py shows what needs the missing fact as grey. The reviews
are read once: the numbers files come from the same read (count_reviews.write_numbers), and
when the reviews could not be read both files stay as they are. The command exits 0 whatever
could not be read; it fails only when it cannot write its files.
"""

import argparse
import json
import re
import sys
import urllib.request
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

import desk_bench
import map_text
import release_stores
from count_reviews import REPO, SINCE_DAYS, GhNumbersApi, collect, write_numbers
from desk import NIGHTLY, Facts, _log_day, _measured, build

Fetch = Callable[[str], str]

PYPISTATS = "https://pypistats.org/api/packages/kitden/recent"
SET_ASIDE = "https://raw.githubusercontent.com/{repo}/main/tests/set-aside.txt"
FETCH_SECONDS = 10
RUN_DAYS = 7
BRANCH = "main"
SCHEDULED_ONLY = ("watcher",)  # watch.yml also has an eval started by hand: it is not a watch
COUNTED = ("success", "failure")  # a skipped, cancelled or unfinished run is not a run
HERE = Path(__file__).resolve().parent.parent  # this repository's checkout
ROSTER = HERE / "config" / "agents.json"
MAP = Path("docs/map/index.html")
API = "https://api.github.com/"
WORKFLOW = re.compile(r"^jobs:", re.M)  # every workflow file has it; an error page has not
RUN_ID = re.compile(r"/actions/runs/(\d+)/")  # in a check run's details_url


# --- Talking to GitHub ---


class GhDeskApi(GhNumbersApi):
    """GhNumbersApi, and the two reads the desk adds. Only reads."""

    def get(self, address: str):
        return json.loads(self._run(address))

    def text(self, address: str) -> str:
        """The answer at `address` as gh prints it."""
        return self._run(address)

    def log(self, address: str) -> str:
        """A job's log: plain text with the colours its tools printed, which gh refuses to print
        unless asked. Only numbers are read from it (desk_bench.startup_times)."""
        return self._run(address, "--allow-escape-sequences")

    def pages(self, address: str, key: str | None = None) -> list:
        """Every page of `address`: the items of each list, or of each object's `key`."""
        text = self._run(address, "--paginate")  # one JSON value per page, one after another
        decoder, items, index, count = json.JSONDecoder(), [], 0, 0
        while index < len(text):
            if text[index].isspace():
                index += 1
                continue
            page, index = decoder.raw_decode(text, index)
            items += page_items(page, key)
            count += 1
        if not count:
            raise ValueError("gh gave no answer")
        return items


def page_items(page, key: str | None) -> list:
    """The items of one page: the page itself when `key` is None, else its `key`. A page of
    another shape is an error, not an empty list."""
    if key is not None:
        page = page.get(key) if isinstance(page, dict) else None
    if not isinstance(page, list):
        raise TypeError("an answer of another shape than expected")
    return page


def fetch_url(url: str) -> str:
    """The text at an https address. No token goes along: this only reads public pages."""
    if not url.startswith("https://"):
        raise ValueError("only https addresses")
    request = urllib.request.Request(url, headers={"User-Agent": "kitden-sdlc-desk"})  # noqa: S310
    with urllib.request.urlopen(request, timeout=FETCH_SECONDS) as response:  # noqa: S310
        return response.read().decode()


# --- Reading one fact ---


def _read(field: str, read: Callable[[], object]):
    """What `read` gives; None, and one warning that names `field`, when it fails. Any error
    counts: a failed call, a cut-off answer from a third party or an oddly shaped one must
    never stop the other reads."""
    try:
        return read()
    except Exception:
        print(f"::warning::desk: could not read {field}")
        return None


def _dicts(items: list) -> list[dict]:
    if not isinstance(items, list) or not all(isinstance(item, dict) for item in items):
        raise TypeError("a list of objects was expected")
    return items


def _count(value: object) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError("a count was expected")
    return value


def _at(text: str) -> datetime:
    when = datetime.fromisoformat(text)
    return when.replace(tzinfo=UTC) if when.tzinfo is None else when


def _issues(api, repo: str) -> list[dict]:
    found = _dicts(api.pages(f"repos/{repo}/issues?state=all&per_page=100"))
    return [item for item in found if "pull_request" not in item]


def _pulls(api, repo: str, now: datetime) -> list[dict]:
    """Every open pull request, however old (one left alone for months still waits), and the
    closed ones updated in the last SINCE_DAYS. The list is newest update first, so an open
    one can come after the cut-off: the open ones are read on their own and merged by number."""
    cutoff = now - timedelta(days=SINCE_DAYS)
    found: dict[int, dict] = {}
    for pull in api.list_pulls(repo):
        if _at(pull["updated_at"]) < cutoff:
            break
        found[pull["number"]] = pull
    for pull in _dicts(api.pages(f"repos/{repo}/pulls?state=open&per_page=100")):
        found[pull["number"]] = pull
    return list(found.values())


def _names(items: list) -> list[str]:
    if not isinstance(items, list) or not all(isinstance(name, str) for name in items):
        raise TypeError("a list of names was expected")
    return items


def _part(value: dict, key: str, empty):
    """`value[key]`; `empty` when the key is missing. Any other shape than `empty`'s is a
    failed read: a null or a string never means "none required"."""
    if not isinstance(value, dict):
        raise TypeError("an object was expected")
    part = value.get(key, empty)
    if not isinstance(part, type(empty)):
        raise TypeError(f"{key} has another shape than expected")
    return part


def _protected(api, repo: str) -> list[str]:
    """The checks branch protection requires; [] when main has no protection or requires none."""
    protection = _part(api.get(f"repos/{repo}/branches/{BRANCH}"), "protection", {})
    checks = _part(protection, "required_status_checks", {})
    return _names(_part(checks, "contexts", []))


def _ruled(api, repo: str) -> list[str]:
    """The checks the rulesets on main require; [] when none does."""
    found = []
    for rule in _dicts(api.pages(f"repos/{repo}/rules/branches/{BRANCH}")):
        if rule.get("type") == "required_status_checks":
            found += [check["context"] for check in rule["parameters"]["required_status_checks"]]
    return _names(found)


def _required(api, repo: str) -> tuple[list[str] | None, bool]:
    """The checks main requires, by branch protection or by a ruleset, each read on its own,
    and whether the list is partial: one of the two reads failed. None when both failed."""
    read = [
        _read("required (branch protection)", lambda: _protected(api, repo)),
        _read("required (rulesets)", lambda: _ruled(api, repo)),
    ]
    if all(names is None for names in read):
        return None, False
    return sorted({name for names in read for name in names or ()}), None in read


def _checks(api, repo: str) -> list[dict]:
    """The check runs of main's newest commit, each with the `event` of the workflow run it
    belongs to: None when that is not known (the runs could not be read, or the check is not
    from Actions)."""
    checks = _dicts(api.pages(f"repos/{repo}/commits/{BRANCH}/check-runs?per_page=100",
                              "check_runs"))
    shas = {check.get("head_sha") for check in checks}
    events: dict[int, str] | None = None
    if len(shas) == 1 and isinstance(sha := shas.pop(), str):
        events = _read("workflow runs of main's newest commit", lambda: _run_events(api, repo, sha))
    return [{**check, "event": (events or {}).get(_run_id(check))} for check in checks]


def _run_events(api, repo: str, sha: str) -> dict[int, str]:
    """The event that started each workflow run of the commit `sha`, by run id."""
    runs = _dicts(api.pages(f"repos/{repo}/actions/runs?head_sha={sha}&per_page=100",
                            "workflow_runs"))
    if not all(isinstance(run.get("id"), int) and isinstance(run.get("event"), str)
               for run in runs):
        raise TypeError("a run without an id or an event")
    return {run["id"]: run["event"] for run in runs}


def _run_id(check: dict) -> int | None:
    url = check.get("details_url")
    found = RUN_ID.search(url) if isinstance(url, str) else None
    return int(found.group(1)) if found else None


def _stars(api, repo: str) -> int:
    return _count(api.get(f"repos/{repo}")["stargazers_count"])


def fetch_downloads(fetch: Fetch) -> int:
    return _count(json.loads(fetch(PYPISTATS))["data"]["last_month"])


def fetch_set_aside(fetch: Fetch, repo: str) -> int:
    """The tests Kitden's tests/set-aside.txt names: its lines that are not blank and not a
    comment. Any other line is a failed read: a page of another shape is never a count."""
    count = 0
    for line in fetch(SET_ASIDE.format(repo=repo)).splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if not line.startswith("tests/") or ".py::" not in line:
            raise ValueError("a line that names no test")
        count += 1
    return count


def _night(api, repo: str, workflow: str) -> dict:
    """The newest finished scheduled run of `workflow` on main, and that run's jobs; both None
    when it has no such run. The run is one call: paging per_page=1 would read every run."""
    address = (f"repos/{repo}/actions/workflows/{workflow}/runs"
               f"?branch={BRANCH}&event=schedule&status=completed&per_page=1")
    runs = _dicts(page_items(api.get(address), "workflow_runs"))
    if not runs:
        return {"workflow": workflow, "name": None, "run": None, "jobs": None}
    run = runs[0]
    if not isinstance(run.get("id"), int) or isinstance(run["id"], bool):
        raise TypeError("a run without an id")
    jobs = _dicts(api.pages(f"repos/{repo}/actions/runs/{run['id']}/jobs?filter=latest"
                            "&per_page=100", "jobs"))
    return {"workflow": workflow, "name": run.get("name"), "run": run, "jobs": jobs}


def _nightly(api, repo: str) -> list[dict]:
    """One entry per workflow of NIGHTLY, each read on its own."""
    found = []
    for workflow, _jobs in NIGHTLY:
        night = _read(f"nightly ({workflow})", lambda w=workflow: _night(api, repo, w))
        found.append(night or {"workflow": workflow, "name": None, "run": None, "jobs": None})
    return found


def _before(path: Path) -> list[dict] | None:
    rows = json.loads(path.read_text()).get("nightly")
    return None if rows is None else _dicts(rows)


def before(out: Path) -> list[dict] | None:
    """The `nightly` rows of the desk.json already in `out`: yesterday's. None when there is no
    such file, or it holds no rows; a file that cannot be read also warns."""
    path = out / "desk.json"
    if not path.is_file():
        return None
    return _read("before", lambda: _before(path))


def _agent_runs(api, roster: dict, now: datetime) -> tuple[dict[str, int | None],
                                                            dict[str, int | None]]:
    """Per agent, its runs that ended well or badly in the last RUN_DAYS, and those of them
    that failed. Agents that share a workflow share its answer, which is read once."""
    since = (now - timedelta(days=RUN_DAYS)).strftime("%Y-%m-%dT%H:%M:%SZ")
    read: dict[tuple[str, str], list[dict] | None] = {}
    counts: dict[str, int | None] = {}
    failed: dict[str, int | None] = {}
    for agent in roster["agents"]:
        pair = (agent["repo"], agent["workflow"])
        if pair not in read:
            who = ", ".join(a["id"] for a in roster["agents"]
                            if (a["repo"], a["workflow"]) == pair)
            address = (f"repos/{pair[0]}/actions/workflows/{pair[1]}/runs"
                       f"?created=>={since}&per_page=100")
            read[pair] = _read(f"runs of {who}", lambda a=address: _dicts(
                api.pages(a, "workflow_runs")))
        runs = read[pair]
        if runs is None:
            counts[agent["id"]] = failed[agent["id"]] = None
            continue
        scheduled = agent["id"] in SCHEDULED_ONLY
        ended = [
            run for run in runs
            if run.get("conclusion") in COUNTED
            and (not scheduled or run.get("event") == "schedule")
        ]
        counts[agent["id"]] = len(ended)
        failed[agent["id"]] = sum(1 for run in ended if run.get("conclusion") == "failure")
    return counts, failed


def _reviews(api, repo: str, now: datetime) -> tuple[list | None, list | None]:
    """The review comments in which a reviewer answered, and those in which neither did."""
    found = _read("reviews", lambda: collect(api, repo, now=now, include_silent=True))
    if found is None:
        return None, None
    return [r for r in found if r.answered], [r for r in found if not r.answered]


def _watch_log(path: Path | None) -> list[dict] | None:
    """The lines of the watcher's log that are JSON objects; None without a readable file."""
    if path is None:
        return None
    lines = []
    for text in path.read_text().splitlines():
        try:
            line = json.loads(text)
        except ValueError:
            continue
        if isinstance(line, dict):
            lines.append(line)
    return lines


class _Unread(Exception):
    """A file the map is checked against could not be read. It is no OSError or ValueError,
    which map_text turns into a line and reads on: this one ends the check at once."""


def _map_stale(api, fetch: Fetch, root: Path) -> list[str]:
    """Each place the workflow map in `root` differs from the workflow files: this checkout's,
    and Kitden's and the tap's on `main`. Their raw files come through `fetch`; their lists of
    files come from the contents API through gh, so with the job's token and not from the
    60 calls an hour GitHub allows without one. A file or a list that was not read is a failed
    read, never a place: a map that could not be checked is not shown as out of date, nor as
    up to date. So is a raw file that is not a workflow, such as an error page. The first
    failed read ends the check, so an offline night does not wait out every timeout."""

    def read(url: str) -> str:
        try:
            text = api.text(url[len(API):]) if url.startswith(API) else fetch(url)
        except Exception as error:
            raise _Unread(url) from error
        if not url.startswith(API) and not WORKFLOW.search(text):
            raise _Unread(url)
        return text

    lines = map_text.differences((root / MAP).read_text(), root, read)
    if any(line.endswith(map_text.NOT_READ) for line in lines):
        raise _Unread("a list of another shape, or a file of this checkout")
    return lines


# --- The bench: history of the nightly runs, main's checks, the stores ---


HISTORY_RUNS = 30  # the newest scheduled runs of each nightly workflow looked at each day
NEW_RUNS = 20  # at most this many runs read in full each day: a first day fills the rest later
RELEASE = "release.yml"  # its build and startup jobs measure the start-up on every release tag
PYPROJECT = "https://raw.githubusercontent.com/{repo}/{sha}/pyproject.toml"
# Kitden's CPU and memory by release, written for this page by its use.yml (measure-use.py).
USE_CHART = "https://raw.githubusercontent.com/{repo}/use-numbers/chart.json"
GLAMA = "https://glama.ai/mcp/servers/KonstantinStarovoytov/kitden"
# Only the latest version: the search lists every version, oldest first, 30 to a page.
REGISTRY_LATEST = release_stores.REGISTRY + "&version=latest"


def _version(fetch: Fetch, repo: str, workflow: str, run: dict) -> str | None:
    """The version the run measured: its tag's on a release, main's pyproject at its commit on a
    nightly."""
    if workflow == RELEASE:
        found = release_stores.TAG.match(run.get("head_branch") or "")
        return found.group(1) if found else None
    sha = run.get("head_sha")
    if not (isinstance(sha, str) and re.fullmatch(r"[0-9a-f]{40}", sha)):
        return None
    return _read(f"version at {sha[:7]}", lambda: desk_bench.version_of(
        fetch(PYPROJECT.format(repo=repo, sha=sha))))


def _read_run(api, fetch: Fetch, repo: str, workflow: str, run: dict, tries: int = 0) -> dict:
    """One run in full: its jobs, the version it measured, and the start-up times the log of
    each job that measures them printed. A log that cannot be read leaves that job without
    times, and the line counts it, so a later day tries again."""
    jobs = _dicts(api.pages(f"repos/{repo}/actions/runs/{run['id']}/jobs?filter=latest"
                            "&per_page=100", "jobs"))
    times, unread = {}, 0
    for job in jobs:
        part, _args = desk_bench.job_parts(job.get("name", ""))
        if part not in desk_bench.MEASURING or not isinstance(job.get("id"), int):
            continue
        if desk_bench._step_state(job, desk_bench.STARTUP_STEP) not in ("green", "red"):
            continue
        log = _read(f"log of {job['name']}",
                    lambda j=job: api.log(f"repos/{repo}/actions/jobs/{j['id']}/logs"))
        if log is None:
            unread += 1
            continue
        found = desk_bench.startup_times(log)
        if found:
            times[job["name"]] = found
    return desk_bench.record(workflow, run, jobs, _version(fetch, repo, workflow, run), times,
                             unread=unread, tries=tries + (1 if unread else 0))


def _runs(api, address: str, field: str) -> list[dict]:
    return _read(field, lambda: _dicts(page_items(api.get(address), "workflow_runs"))) or []


def _again(line: dict | None, run: dict) -> bool:
    """A run read before that is read again: re-run since (a newer attempt), or with a log that
    could not be read, until LOG_TRIES days have tried."""
    if line is None:
        return True
    attempt = run.get("run_attempt")
    if isinstance(attempt, int) and attempt > (line.get("attempt") or 1):
        return True
    return bool(line.get("unread_logs")) and (line.get("tries") or 0) < desk_bench.LOG_TRIES


def update_history(api, fetch: Fetch, repo: str, history: list[dict]) -> list[dict]:
    """The history with the runs it does not hold yet, or must read again (_again): the nightly
    workflows' scheduled runs on main, and release.yml's runs on a release tag. The oldest
    first, at most NEW_RUNS of them; a run that cannot be read is left for the next day."""
    known = {line.get("id"): line for line in history if isinstance(line, dict)}
    waiting = []
    for workflow, _parts in NIGHTLY:
        address = (f"repos/{repo}/actions/workflows/{workflow}/runs?branch={BRANCH}"
                   f"&event=schedule&status=completed&per_page={HISTORY_RUNS}")
        waiting += [(workflow, run) for run in _runs(api, address, f"history ({workflow})")]
    # Each release tag's own build, found by its tag: in the list of all push runs an old tag's
    # run is soon past the first page. Only tags with no line yet, or a log to read again, are
    # looked up.
    have = {line.get("version") for line in history if line.get("workflow") == RELEASE
            and not (line.get("unread_logs") and (line.get("tries") or 0) < desk_bench.LOG_TRIES)}
    tags = _read("tags", lambda: _dicts(api.get(f"repos/{repo}/tags?per_page=100"))) or []
    for tag in tags:
        found = release_stores.TAG.match(tag.get("name") or "")
        if not found or found.group(1) in have:
            continue
        address = (f"repos/{repo}/actions/workflows/{RELEASE}/runs?branch={tag['name']}"
                   "&event=push&status=completed&per_page=1")
        waiting += [(RELEASE, run) for run in _runs(api, address, f"build of {tag['name']}")]
    waiting = [(workflow, run) for workflow, run in waiting
               if isinstance(run.get("id"), int) and _again(known.get(run["id"]), run)]
    new = []
    for workflow, run in sorted(waiting, key=lambda item: item[1].get("created_at") or "")[
            :NEW_RUNS]:
        tries = (known.get(run["id"]) or {}).get("tries") or 0
        line = _read(f"run {run['id']}",
                     lambda w=workflow, r=run, n=tries: _read_run(api, fetch, repo, w, r, n))
        if line is not None:
            new.append(line)
    return desk_bench.merge(history, new)


def read_history(out: Path) -> list[dict]:
    """history.json in `out`, or an empty history: a first day starts one."""
    path = out / "history.json"
    if not path.is_file():
        return []
    found = _read("history.json", lambda: _dicts(json.loads(path.read_text())))
    return found or []


def _gate(api, repo: str, checks: list[dict] | None) -> dict | None:
    """The build jobs of the workflow run that checked main's newest commit on its push."""
    build = next((c for c in checks or [] if isinstance(c, dict) and c.get("event") == "push"
                  and desk_bench.job_parts(c.get("name", ""))[0] == "build"), None)
    run_id = _run_id(build) if build else None
    if run_id is None:
        return None
    run = api.get(f"repos/{repo}/actions/runs/{run_id}")
    jobs = _dicts(api.pages(f"repos/{repo}/actions/runs/{run_id}/jobs?filter=latest"
                            "&per_page=100", "jobs"))
    return desk_bench.gate(jobs, run)


def _newest(api, repo: str) -> dict:
    release = api.get(f"repos/{repo}/releases/latest")
    tag = release["tag_name"]
    found = release_stores.TAG.match(tag)
    if not found:
        raise ValueError("a release tag of another shape")
    return {"version": found.group(1), "at": release.get("published_at"),
            "url": release.get("html_url")}


def _pypi(fetch: Fetch) -> dict:
    data = json.loads(fetch(release_stores.PYPI))
    version = data["info"]["version"]
    files = data.get("releases", {}).get(version) or [{}]
    return {"version": version, "at": files[0].get("upload_time_iso_8601"),
            "url": f"https://pypi.org/project/kitden/{version}/"}


def _homebrew(fetch: Fetch) -> dict:
    text = fetch(release_stores.FORMULA)
    found = re.search(r'^  url "[^"]*/kitden-([^/"]+)\.tar\.gz"', text, re.M)
    if not found:
        raise ValueError("no url in the formula")
    return {"version": found.group(1), "at": None,
            "url": "https://github.com/konstantinstarovoytov/homebrew-tap"}


def _registry(fetch: Fetch) -> dict:
    entries = json.loads(fetch(REGISTRY_LATEST))["servers"]
    latest = [e for e in entries if e["server"]["name"] == release_stores.MCP_NAME
              and e["_meta"][release_stores.OFFICIAL].get("isLatest")]
    if not latest:
        raise ValueError("no latest version")
    meta = latest[0]["_meta"][release_stores.OFFICIAL]
    return {"version": latest[0]["server"]["version"],
            "at": meta.get("updatedAt") or meta.get("publishedAt"),
            "url": "https://registry.modelcontextprotocol.io/v0/servers?search="
                   + release_stores.MCP_NAME}


def _glama(fetch: Fetch) -> dict:
    """Glama lists Kitden from its repository. Its API needs a key, so only the listing page is
    read, to see that it answers; no version is taken from it."""
    fetch(GLAMA)
    return {"version": None, "listed": True, "at": None, "url": GLAMA,
            "note": None}


MCPRUSH = "https://mcprush.com/konstantinstarovoytov/kitden-mcp"
# MCP Rush's pages answer scripts with a challenge; its badge does not, and says the version.
MCPRUSH_CARD = "https://mcprush.com/badge/kitden-mcp/card.svg"
CARD_VERSION = re.compile(r"<desc>[^<]*· v(\d+\.\d+\.\d+) ·")


def _mcprush(fetch: Fetch) -> dict:
    found = CARD_VERSION.search(fetch(MCPRUSH_CARD))
    if not found:
        raise ValueError("no version on the badge")
    return {"version": found.group(1), "at": None, "url": MCPRUSH}


def _watch_days(watch_log: list[dict] | None, now: datetime) -> float | None:
    """Days since the watcher's newest run that read something; None without one."""
    days = [day for day in map(_log_day, [line for line in watch_log or []
                                          if isinstance(line, dict) and _measured(line)])
            if day and day <= now]
    return max(0.0, (now - max(days)).total_seconds() / 86400) if days else None


def read_bench(api, fetch: Fetch, repo: str, facts: Facts, history: list[dict],
               now: datetime) -> dict:
    """desk.json's `bench`: every read on its own, a failed one None."""
    seen = {
        "pypi": _read("PyPI", lambda: _pypi(fetch)),
        "homebrew": _read("Homebrew", lambda: _homebrew(fetch)),
        "registry": _read("MCP Registry", lambda: _registry(fetch)),
        "glama": _read("Glama", lambda: _glama(fetch)),
        "mcprush": _read("MCP Rush", lambda: _mcprush(fetch)),
    }
    return desk_bench.bench(
        history, now,
        gate_read=_read("checks of main's push", lambda: _gate(api, repo, facts.checks)),
        newest=_read("newest release", lambda: _newest(api, repo)),
        seen=seen, issues=facts.issues, watch_days=_watch_days(facts.watch_log, now), repo=repo,
        use_chart=_read("CPU and memory chart",
                        lambda: json.loads(fetch(USE_CHART.format(repo=repo)))))


# --- All the facts ---


def gather(api, repo: str, roster: dict, now: datetime, watch_log: Path | None,
           fetch: Fetch = fetch_url, map_root: Path | None = None) -> Facts:
    """Every fact the desk reads. A read that fails leaves its field None. The workflow map is
    read only with `map_root`, the checkout it is in."""
    required, partial = _required(api, repo)
    reviews, silent = _reviews(api, repo, now)
    runs, failed = _agent_runs(api, roster, now)
    return Facts(
        repo=repo,
        issues=_read("issues", lambda: _issues(api, repo)),
        pulls=_read("pulls", lambda: _pulls(api, repo, now)),
        reviews=reviews,
        silent=silent,
        checks=_read("checks", lambda: _checks(api, repo)),
        required=required,
        required_partial=partial,
        runs=runs,
        failed=failed,
        watch_log=None if watch_log is None else _read("watch_log", lambda: _watch_log(watch_log)),
        stars=_read("stars", lambda: _stars(api, repo)),
        downloads=_read("downloads", lambda: fetch_downloads(fetch)),
        nightly=_nightly(api, repo),
        set_aside=_read("set_aside", lambda: fetch_set_aside(fetch, repo)),
        map_stale=None if map_root is None else _read(
            "map", lambda: _map_stale(api, fetch, map_root)),
    )


def main(argv: list[str], api=None, now: datetime | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=REPO)
    parser.add_argument("--roster", type=Path, default=ROSTER)
    parser.add_argument("--watch-log", type=Path)
    parser.add_argument("--out", type=Path, default=Path())
    args = parser.parse_args(argv)

    now = now or datetime.now(UTC)
    roster = json.loads(args.roster.read_text())
    api = api or GhDeskApi()
    facts = gather(api, args.repo, roster, now, args.watch_log,
                   fetch=lambda url: fetch_url(url), map_root=HERE)
    facts.before = before(args.out)  # read before the new desk.json takes its place
    before_history = read_history(args.out)
    history = _read("history", lambda: update_history(api, fetch_url, args.repo, before_history))
    history = before_history if history is None else history
    desk = build(facts, roster, now)
    desk["bench"] = _read("bench", lambda: read_bench(api, fetch_url, args.repo, facts, history,
                                                      now))
    try:
        args.out.mkdir(parents=True, exist_ok=True)
        (args.out / "history.json").write_text(json.dumps(history, indent=1) + "\n")
        (args.out / "desk.json").write_text(json.dumps(desk, indent=2) + "\n")
        if facts.reviews is not None:
            write_numbers(facts.reviews, args.out, now)
    except OSError:
        print(f"::error::desk: could not write into {args.out}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
