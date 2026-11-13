"""Read the desk's facts from GitHub and from files, and write desk.json.

Each fact is read on its own. One that cannot be read is None, never a default that looks like
good news: it prints one `::warning::` line naming the field (never a token or an answer's text),
the other reads still run, and desk.py shows what needs the missing fact as grey. The command
exits 0 whatever could not be read; it fails only when it cannot write desk.json.
"""

import argparse
import json
import re
import sys
import urllib.request
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

from count_reviews import REPO, SINCE_DAYS, GhNumbersApi, collect
from desk import Facts, build

Fetch = Callable[[str], str]

PYPISTATS = "https://pypistats.org/api/packages/kitden/recent"
FETCH_SECONDS = 10
RUN_DAYS = 7
BRANCH = "main"
SCHEDULED_ONLY = ("watcher",)  # watch.yml also has an eval started by hand: it is not a watch
COUNTED = ("success", "failure")  # a skipped, cancelled or unfinished run is not a run
ROSTER = Path(__file__).resolve().parent.parent / "config" / "agents.json"
RUN_ID = re.compile(r"/actions/runs/(\d+)/")  # in a check run's details_url


# --- Talking to GitHub ---


class GhDeskApi(GhNumbersApi):
    """GhNumbersApi, and the two reads the desk adds. Only reads."""

    def get(self, address: str):
        return json.loads(self._run(address))

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


def _agent_runs(api, roster: dict, now: datetime) -> dict[str, int | None]:
    """Runs that ended well or badly in the last RUN_DAYS, per agent. Agents that share a
    workflow share its answer, which is read once."""
    since = (now - timedelta(days=RUN_DAYS)).strftime("%Y-%m-%dT%H:%M:%SZ")
    read: dict[tuple[str, str], list[dict] | None] = {}
    counts: dict[str, int | None] = {}
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
            counts[agent["id"]] = None
            continue
        scheduled = agent["id"] in SCHEDULED_ONLY
        counts[agent["id"]] = sum(
            1 for run in runs
            if run.get("conclusion") in COUNTED
            and (not scheduled or run.get("event") == "schedule")
        )
    return counts


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


# --- All the facts ---


def gather(api, repo: str, roster: dict, now: datetime, watch_log: Path | None,
           fetch: Fetch = fetch_url) -> Facts:
    """Every fact the desk reads. A read that fails leaves its field None."""
    required, partial = _required(api, repo)
    return Facts(
        repo=repo,
        issues=_read("issues", lambda: _issues(api, repo)),
        pulls=_read("pulls", lambda: _pulls(api, repo, now)),
        reviews=_read("reviews", lambda: collect(api, repo, now=now)),
        checks=_read("checks", lambda: _checks(api, repo)),
        required=required,
        required_partial=partial,
        runs=_agent_runs(api, roster, now),
        watch_log=None if watch_log is None else _read("watch_log", lambda: _watch_log(watch_log)),
        stars=_read("stars", lambda: _stars(api, repo)),
        downloads=_read("downloads", lambda: fetch_downloads(fetch)),
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
    facts = gather(api or GhDeskApi(), args.repo, roster, now, args.watch_log,
                   fetch=lambda url: fetch_url(url))
    try:
        args.out.mkdir(parents=True, exist_ok=True)
        (args.out / "desk.json").write_text(json.dumps(build(facts, roster, now), indent=2) + "\n")
    except OSError:
        print(f"::error::desk: could not write {args.out / 'desk.json'}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
