import json
import re
import urllib.parse
from datetime import UTC, datetime
from pathlib import Path

import pytest

import release_watch
from release_stores import Row
from release_watch import (
    drift_body,
    gather,
    proposal_body,
    propose,
    run,
    upsert,
)

OWNER = "KonstantinStarovoytov"
NOW = datetime(2026, 11, 12, 12, 0, tzinfo=UTC)


class FakeGh:
    """Open issues by number; records what was done."""

    def __init__(self, open_issues: dict[int, str] | None = None):
        self.open = dict(open_issues or {})
        self.calls: list[tuple] = []

    def find_open(self, title):
        for number, found in self.open.items():
            if found == title:
                return number
        return None

    def create(self, title, body):
        self.calls.append(("create", title, body))

    def edit(self, number, body):
        self.calls.append(("edit", number, body))

    def close(self, number):
        self.calls.append(("close", number))


# propose


def test_propose_needs_user_facing_change():
    changed = {1: ["docs/guide.md"], 2: ["tests/test_a.py", ".github/workflows/x.yml"]}
    assert propose(changed, {}, 30) is None
    changed[3] = ["src/kitden/app.py"]
    assert propose(changed, {}, 30) == [3]
    assert propose({4: ["plugins/kitden/plugin.json"]}, {}, 30) == [4]
    assert propose({5: ["install.sh"]}, {}, 30) == [5]
    assert propose({6: ["docs/install.md"]}, {}, 30) is None


def test_propose_waits_7_days_unless_bug():
    changed = {7: ["src/a.py"], 8: ["src/b.py"]}
    assert release_watch.WAIT_DAYS == 7
    assert propose(changed, {}, 6.9) is None
    assert propose(changed, {}, 7) == [7, 8]
    assert propose(changed, {8: ["bug"]}, 0.5) == [7, 8]
    # A bug fix that changes nothing users get does not call for a release.
    assert propose({9: ["docs/a.md"]}, {9: ["bug"]}, 0.5) is None


def test_propose_no_prs():
    assert propose({}, {}, 100) is None


def test_proposal_has_no_version():
    body = proposal_body([12, 7])
    assert not re.search(r"\d+\.\d+\.\d+|\bv\d", body)
    assert f"https://github.com/{OWNER}/kitden/pull/7" in body
    assert f"https://github.com/{OWNER}/kitden/pull/12" in body
    assert f"https://github.com/{OWNER}/kitden/actions/workflows/release-prep.yml" in body
    # The workflow's own name, as GitHub shows it (examples/release-prep.yml).
    assert "[Release prep](" in body
    prep = (Path(__file__).resolve().parent.parent / "examples/release-prep.yml").read_text()
    assert re.search(r"(?m)^name: Release prep$", prep)
    assert release_watch.PROPOSAL_TITLE == "Time for a release?"


# drift body


def test_drift_body_lists_table_and_what_to_rerun():
    rows = [
        Row("PyPI", "0.8.0", "0.8.0", True),
        Row("MCP Registry", "0.8.0", "latest 0.7.2", False),
        Row("Homebrew formula", "0.8.0", "0.7.2", False),
        Row("Marketplace entry", "release", "none", False),
        Row("Glama", "-", "check by hand", None),
    ]
    late = [rows[1], rows[2], rows[3]]
    body = drift_body("v0.8.0", rows, late)
    assert "| MCP Registry | 0.8.0 | latest 0.7.2 | behind |" in body
    assert "MCP Registry" in body.split("Re-run")[1]
    assert "Homebrew formula" in body.split("Re-run")[1]
    assert "Glama" not in body.split("Re-run")[1]
    # kitden-sdlc's publish jobs run inside the tag's "Checks and release" run.
    assert "`Publish` run" not in body
    assert "`stores / registry` job of the tag's `Checks and release` run" in body
    assert "`stores / homebrew` job of the tag's `Checks and release` run" in body


def test_every_rerun_names_a_real_job():
    """Every job named in the advice is a job of publish.yml, called as `stores`."""
    publish = (Path(__file__).resolve().parent.parent / ".github/workflows/publish.yml").read_text()
    jobs = set(re.findall(r"(?m)^  ([a-z-]+):$", publish))
    advice = " ".join([*release_watch.RERUN.values(), release_watch.HOMEBREW_DESC])
    named = re.findall(r"`stores / ([a-z-]+)`", advice)
    assert named and set(named) <= jobs


def test_homebrew_desc_only_says_fix_the_tap():
    """A formula at the right version is never bumped again, so re-running cannot fix its desc."""
    desc = Row(
        "Homebrew formula",
        "0.8.0",
        "0.8.0, bottles kitden-0.8.0; desc differs from listing.toml brew",
        False,
    )
    old = Row("Homebrew formula", "0.8.0", "0.7.2, bottles kitden-0.7.2", False)
    body = drift_body("v0.8.0", [desc], [desc]).split("Re-run")[1]
    assert "small PR" in body and "re-running `stores / homebrew` changes nothing" in body
    body = drift_body("v0.8.0", [old], [old]).split("Re-run")[1]
    assert "re-run the `stores / homebrew` job" in body and "small PR" not in body
    assert release_watch.drift_title("v0.8.0") == "Release v0.8.0 is not everywhere"


# upsert


def test_upsert_creates_when_none():
    gh = FakeGh()
    upsert("T", "body", gh)
    assert gh.calls == [("create", "T", "body")]


def test_upsert_edits_existing():
    gh = FakeGh({4: "Other", 5: "T"})
    upsert("T", "new body", gh)
    assert gh.calls == [("edit", 5, "new body")]


def test_upsert_closes_when_green():
    gh = FakeGh({5: "T"})
    upsert("T", "", gh)
    assert gh.calls == [("close", 5)]


def test_upsert_empty_with_no_issue_does_nothing():
    gh = FakeGh()
    upsert("T", "", gh)
    assert gh.calls == []


# gather, with a fake fetch


def api(path: str) -> str:
    return f"https://api.github.com/repos/{OWNER}/kitden/{path}"


def search_url(since: str) -> str:
    query = f"repo:{OWNER}/kitden is:pr is:merged base:main merged:>{since}"
    return "https://api.github.com/search/issues?" + urllib.parse.urlencode(
        {"q": query, "per_page": 100}
    )


def make_fetch(date="2026-11-01T10:00:00Z", prs=None, files=None, tags=None, heads=None):
    prs = prs if prs is not None else {}
    files = files or {}
    heads = heads or {}
    tags = tags if tags is not None else ["v0.7.2", "v0.8.0", "v0.10.0", "v0.9.9", "vnext"]
    seen: list[str] = []

    def fetch(url: str) -> str:
        seen.append(url)
        if url == api("git/matching-refs/tags/v?per_page=100"):
            return json.dumps([{"ref": f"refs/tags/{t}"} for t in tags])
        if url == api("commits/v0.10.0"):
            return json.dumps({"commit": {"committer": {"date": date}}})
        if url == search_url(date):
            items = [
                {"number": n, "labels": [{"name": x} for x in labels]} for n, labels in prs.items()
            ]
            return json.dumps({"items": items})
        for number in prs:
            if url == api(f"pulls/{number}"):
                return json.dumps({"head": {"ref": heads.get(number, f"topic-{number}")}})
        for number, names in files.items():
            if url == api(f"pulls/{number}/files?per_page=100&page=1"):
                return json.dumps([{"filename": name} for name in names])
        raise AssertionError(f"unexpected url {url}")

    fetch.seen = seen  # type: ignore[attr-defined]
    return fetch


def test_gather_picks_newest_tag_and_reads_prs():
    fetch = make_fetch(
        prs={11: ["bug"], 12: []},
        files={11: ["src/a.py"], 12: ["docs/x.md", "install.sh"]},
    )
    data = gather(fetch, NOW)
    assert data is not None
    assert data.tag == "v0.10.0"
    assert data.age_days == pytest.approx(11.0 + 2 / 24)
    assert data.changed == {11: ["src/a.py"], 12: ["docs/x.md", "install.sh"]}
    assert data.labels == {11: ["bug"], 12: []}


def test_gather_leaves_out_release_prep_prs():
    """Release prep's own PR bumps the version in src/, which is not a reason to release."""
    fetch = make_fetch(
        prs={20: [], 21: []},
        files={20: ["src/kitden/__init__.py", "docs/releases/v0.10.0.md"], 21: ["src/a.py"]},
        heads={20: "prepare-v0.10.0", 21: "prepare-docs"},
    )
    data = gather(fetch, NOW)
    assert data is not None
    assert data.changed == {21: ["src/a.py"]}
    assert data.labels == {21: []}
    assert api("pulls/20/files?per_page=100&page=1") not in fetch.seen  # type: ignore[attr-defined]


def test_gather_without_a_tag():
    assert gather(make_fetch(tags=[]), NOW) is None


def test_gather_pages_through_files():
    first = [{"filename": f"docs/{i}.md"} for i in range(100)]
    second = [{"filename": "src/late.py"}]
    base = make_fetch(prs={3: []})

    def fetch(url):
        if url == api("pulls/3/files?per_page=100&page=1"):
            return json.dumps(first)
        if url == api("pulls/3/files?per_page=100&page=2"):
            return json.dumps(second)
        return base(url)

    data = gather(fetch, NOW)
    assert data is not None
    assert data.changed[3][-1] == "src/late.py"
    assert len(data.changed[3]) == 101


# run


def test_run_opens_proposal_and_closes_green_drift(monkeypatch):
    drift_title = release_watch.drift_title("v0.10.0")
    gh = FakeGh({9: drift_title})
    monkeypatch.setattr(release_watch, "read_all", lambda tag, fetch: [Row("PyPI", "1", "1", True)])
    fetch = make_fetch(prs={11: []}, files={11: ["src/a.py"]})
    run(fetch, gh, NOW)
    assert ("create", release_watch.PROPOSAL_TITLE, proposal_body([11])) in gh.calls
    assert ("close", 9) in gh.calls


def test_run_reports_drift_and_closes_stale_proposal(monkeypatch):
    rows = [Row("PyPI", "0.10.0", "0.9.9", False)]
    monkeypatch.setattr(release_watch, "read_all", lambda tag, fetch: rows)
    gh = FakeGh({2: release_watch.PROPOSAL_TITLE})
    run(make_fetch(), gh, NOW)
    assert ("close", 2) in gh.calls
    created = [c for c in gh.calls if c[0] == "create"]
    assert created[0][1] == "Release v0.10.0 is not everywhere"
    assert "0.9.9" in created[0][2]


def test_homebrew_waits_48_hours(monkeypatch):
    rows = [Row("Homebrew formula", "0.10.0", "0.9.9", False)]
    monkeypatch.setattr(release_watch, "read_all", lambda tag, fetch: rows)
    gh = FakeGh()
    run(make_fetch(date="2026-11-11T12:00:00Z"), gh, NOW)  # 24 hours old
    assert gh.calls == []


def test_run_without_a_tag_does_nothing():
    gh = FakeGh()
    run(make_fetch(tags=[]), gh, NOW)
    assert gh.calls == []


# the gh CLI


def test_gh_cli_commands(monkeypatch):
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append((cmd, kwargs))

        class Result:
            stdout = json.dumps([{"number": 3, "title": "T x"}, {"number": 4, "title": "T"}])

        return Result()

    monkeypatch.setattr(release_watch.subprocess, "run", fake_run)
    gh = release_watch.GhCli()
    assert gh.find_open("T") == 4
    gh.create("T", "b")
    gh.edit(4, "c")
    gh.close(4)
    commands = [c[0] for c in calls]
    assert all(f"{OWNER}/kitden" in cmd for cmd in commands)
    assert commands[1][:3] == ["gh", "issue", "create"]
    assert commands[2][:4] == ["gh", "issue", "edit", "4"]
    assert commands[3][:4] == ["gh", "issue", "close", "4"]
    assert all(kw.get("check") is True for _, kw in calls)
