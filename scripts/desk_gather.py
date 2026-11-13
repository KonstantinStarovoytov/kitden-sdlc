"""Read the desk's facts from GitHub and from files, and write desk.json.

Each fact is read on its own. One that cannot be read is None, never a default that looks like
good news: it prints one `::warning::` line naming the field (never a token or an answer's text),
the other reads still run, and desk.py shows what needs the missing fact as grey. The command
exits 0 whatever could not be read; it fails only when it cannot write desk.json.
"""

import argparse
import json
import subprocess
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
# What a failed or oddly shaped answer raises. Anything else is a bug and shows as one.
READ_ERRORS = (subprocess.CalledProcessError, OSError, ValueError, KeyError, TypeError,
               AttributeError, IndexError)


# --- Talking to GitHub ---


class GhDeskApi(GhNumbersApi):
    """GhNumbersApi, and the two reads the desk adds. Only reads."""

    def get(self, address: str):
        return json.loads(self._run(address))

    def pages(self, address: str, key: str | None = None) -> list:
        """Every page of `address`: the items of each list, or of each object's `key`."""
        text = self._run(address, "--paginate")  # one JSON value per page, one after another
        decoder, items, index = json.JSONDecoder(), [], 0
        while index < len(text):
            if text[index].isspace():
                index += 1
                continue
            page, index = decoder.raw_decode(text, index)
            items += page[key] if key else page
        return items


def fetch_url(url: str) -> str:
    """The text at an https address. No token goes along: this only reads public pages."""
    if not url.startswith("https://"):
        raise ValueError("only https addresses")
    request = urllib.request.Request(url, headers={"User-Agent": "kitden-sdlc-desk"})  # noqa: S310
    with urllib.request.urlopen(request, timeout=FETCH_SECONDS) as response:  # noqa: S310
        return response.read().decode()


# --- Reading one fact ---


def _read(field: str, read: Callable[[], object]):
    """What `read` gives; None, and one warning that names `field`, when it fails."""
    try:
        return read()
    except READ_ERRORS:
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


def _required(api, repo: str) -> list[str]:
    """The checks main requires; [] when it has no protection or requires none."""
    protection = api.get(f"repos/{repo}/branches/{BRANCH}").get("protection") or {}
    checks = protection.get("required_status_checks") or {}
    contexts = checks.get("contexts") or []
    if not isinstance(contexts, list) or not all(isinstance(name, str) for name in contexts):
        raise TypeError("a list of names was expected")
    return contexts


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
    return Facts(
        issues=_read("issues", lambda: _issues(api, repo)),
        pulls=_read("pulls", lambda: _pulls(api, repo, now)),
        reviews=_read("reviews", lambda: collect(api, repo, now=now)),
        checks=_read("checks", lambda: _dicts(
            api.pages(f"repos/{repo}/commits/{BRANCH}/check-runs?per_page=100", "check_runs"))),
        required=_read("required", lambda: _required(api, repo)),
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
