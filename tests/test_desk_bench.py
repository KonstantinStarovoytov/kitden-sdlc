"""The bench: the history of the nightly runs and the release builds, the rows the page shows,
the start-up times by release, main's checks, the stores, the bugs and the upstream changes."""
from datetime import UTC, datetime

import desk_bench
from desk_bench import (
    NIGHTS,
    bugs,
    gate,
    job_parts,
    merge,
    record,
    rows,
    startup,
    startup_times,
    stores,
    upstream,
    version_of,
)

NOW = datetime(2026, 11, 17, 7, tzinfo=UTC)
RUN_URL = "https://github.com/KonstantinStarovoytov/kitden/actions/runs/{}"
JOB_URL = "https://github.com/KonstantinStarovoytov/kitden/actions/runs/{}/job/{}"
STEP = desk_bench.STARTUP_STEP

# What measure-start.py printed in the nightly's log on 2026-11-16, with the log's timestamps
# and the colours its tools print.
LOG = (
    "2026-11-16T10:14:30.9188680Z ##[group]Run uv run python scripts/measure-start.py\n"
    "2026-11-16T10:14:44.1026930Z first usable: 0.8 s (budget 2 s)\n"
    "2026-11-16T10:14:44.1029000Z   the start line then said: Still checking Codex plugins\n"
    "2026-11-16T10:14:44.1030000Z   gateway view: 11 ms\n"
    "2026-11-16T10:14:44.1032060Z \x1b[0mcomplete: 0.9 s (budget 5 s)\n"
    "2026-11-16T10:14:44.1032510Z demo (medium): 0.2 s (budget 2 s)\n"
    "2026-11-16T10:15:00.0000000Z the scan is complete: 12 steps\n"
)


def job(name, conclusion="success", job_id=1, steps=None, run_id=7):
    return {"id": job_id, "name": name, "conclusion": conclusion,
            "html_url": JOB_URL.format(run_id, job_id),
            "steps": steps if steps is not None else [
                {"name": "Run uv run pytest -q", "conclusion": conclusion},
                {"name": STEP, "conclusion": "success"}]}


def run(run_id, night, workflow="nightly.yml", **extra):
    return {"id": run_id, "created_at": f"{night}T02:37:00Z", "head_sha": "a" * 40,
            "html_url": RUN_URL.format(run_id), "head_branch": "main", "run_attempt": 1,
            **extra}


def night_line(run_id, night, states=None, version="0.9.2", times=None):
    """A nightly line: every job green unless `states` names it."""
    states = states or {}
    names = [f"systems ({runner}, {py})" for runner, _, _ in desk_bench.SYSTEMS
             for py in desk_bench.PYTHONS]
    names += ["browser", "clients (macos-latest)", "clients (ubuntu-latest)"]
    names += [f"engines ({leg})" for leg, _ in desk_bench.ENGINES]
    jobs = []
    for i, name in enumerate(names):
        failed = states.get(name) == "failure"
        steps = [{"name": "Run uv run pytest -q", "conclusion": states.get(name, "success")}]
        if name.startswith("systems"):
            steps.append({"name": STEP, "conclusion": "failure" if states.get(name) == "slow"
                          else "success"})
        jobs.append(job(name, "failure" if failed or states.get(name) == "slow"
                        else states.get(name, "success"), i, steps, run_id))
    found = {name: t for name, t in (times or {}).items()}
    return record("nightly.yml", run(run_id, night), jobs, version, found)



def use_line(run_id, night, conclusion="success"):
    """A night of use.yml: its two jobs; only `use` is a part."""
    return record("use.yml", run(run_id, night, workflow="use.yml"),
                  [job("use", conclusion, 1, None, run_id), job("use-store", "success", 2)],
                  "0.9.2", {})

def test_job_names_split_into_part_and_arguments():
    assert job_parts("systems (macos-15-intel, 3.14)") == ("systems", ("macos-15-intel", "3.14"))
    assert job_parts("browser") == ("browser", ())
    assert job_parts("build (ubuntu-latest)") == ("build", ("ubuntu-latest",))


def test_the_start_up_times_come_from_the_log_and_nothing_else():
    assert startup_times(LOG) == {"first": 0.8, "complete": 0.9, "demo": 0.2}
    assert startup_times("complete: 9 s (budget 5 s)\nno times here") is None  # no timestamp
    assert startup_times("") is None


def test_the_version_is_the_one_pyproject_names():
    assert version_of('[project]\nname = "kitden"\nversion = "0.9.2"\n') == "0.9.2"
    assert version_of('version = "dev"\n') is None


def test_a_record_holds_each_jobs_state_failed_step_and_times():
    jobs = [job("systems (macos-latest, 3.14)", "failure", 1,
                [{"name": "Run uv run pytest -q", "conclusion": "failure"},
                 {"name": STEP, "conclusion": "skipped"}]),
            job("browser", "cancelled", 2)]
    line = record("nightly.yml", run(7, "2026-11-16"), jobs, "0.9.2",
                  {"browser": {"first": 0.5}})
    first, second = line["jobs"]
    assert line["night"] == "2026-11-16" and line["version"] == "0.9.2"
    assert first["state"] == "red" and first["failed_step"] == "Run uv run pytest -q"
    assert first["startup"] == "grey"  # skipped: no start-up time that night
    assert second["state"] == "grey" and second["times"] == {"first": 0.5}


def test_merge_keeps_every_release_and_the_newest_nightly_runs():
    releases = [record("release.yml", run(100 + i, f"2026-10-{10 + i:02}"), [], f"0.{i}.0", {})
                for i in range(3)]
    nights = [night_line(i, f"2026-11-{i:02}") for i in range(1, 11)]
    merged = merge(releases, nights, keep=4)
    assert [line["id"] for line in merged if line["workflow"] == "release.yml"] == [100, 101, 102]
    assert [line["id"] for line in merged if line["workflow"] == "nightly.yml"] == [7, 8, 9, 10]
    again = merge(merged, [night_line(10, "2026-11-10", {"browser": "failure"})], keep=4)
    assert len(again) == len(merged)  # one line per run id: the newer read wins
    assert next(j for j in again[-1]["jobs"] if j["name"] == "browser")["state"] == "red"


def test_rows_follow_the_page_and_show_the_last_nights():
    history = [night_line(i, f"2026-11-{i:02}") for i in range(1, 17)]
    found = rows(history, NOW)
    assert [r["name"] for r in found] == [
        "macOS · arm64",
        "macOS · x86_64 (Intel)",
        "Linux · x86_64",
        "Linux · arm64",
        "End-to-end in Chromium",
        "End-to-end in three browsers",
        "Start-up time",
        "CPU and memory",
        "Claude Code and Codex, newest",
        "Newest dependencies",
    ]
    mac = found[0]
    assert mac["state"] == "green" and [c["label"] for c in mac["cells"]] == [
        "Python 3.13", "Python 3.14"]
    assert len(mac["nights"]) == NIGHTS and mac["nights"][-1]["night"] == "2026-11-16"
    assert found[-1]["state"] == "grey"  # no newest-dependencies run in this history


def test_a_red_row_says_since_when_and_which_job_failed():
    red = "systems (ubuntu-24.04-arm, 3.14)"
    history = [night_line(1, "2026-11-14"), night_line(2, "2026-11-15", {red: "failure"}),
               night_line(3, "2026-11-16", {red: "failure"})]
    arm = next(r for r in rows(history, NOW) if r["name"] == "Linux · arm64")
    assert arm["state"] == "red" and arm["since"] == "2026-11-15"
    assert [c["state"] for c in arm["cells"]] == ["green", "red"]
    assert arm["failed"] == [{"job": red, "step": "Run uv run pytest -q",
                              "url": JOB_URL.format(3, 7)}]
    assert [n["state"] for n in arm["nights"]] == ["green", "red", "red"]


def test_a_grey_night_keeps_the_red_and_a_green_one_ends_it():
    red = "systems (ubuntu-24.04-arm, 3.14)"
    history = [night_line(1, "2026-11-12", {red: "failure"}), night_line(2, "2026-11-13"),
               night_line(3, "2026-11-14", {red: "failure"}),
               night_line(4, "2026-11-15", {red: "cancelled"}),
               night_line(5, "2026-11-16", {red: "failure"})]
    arm = next(r for r in rows(history, NOW) if r["name"] == "Linux · arm64")
    assert arm["since"] == "2026-11-14"


def test_a_newest_night_without_the_rows_job_is_grey_not_green():
    line = night_line(1, "2026-11-16")
    line["jobs"] = [j for j in line["jobs"] if j["name"] != "browser"]
    e2e = next(r for r in rows([line], NOW) if r["name"] == "End-to-end in Chromium")
    assert e2e["state"] == "grey"


def test_a_newest_night_without_one_engines_leg_is_grey_not_green():
    line = night_line(1, "2026-11-16")
    line["jobs"] = [j for j in line["jobs"] if j["name"] != "engines (firefox)"]
    row = next(r for r in rows([line], NOW) if r["name"] == "End-to-end in three browsers")
    assert row["state"] == "grey"
    assert [(c["label"], c["state"]) for c in row["cells"]] == [
        ("Chrome", "green"), ("Firefox", "grey"), ("WebKit", "green")]


def test_the_engines_row_shows_each_browser_and_names_the_red_one():
    red = "engines (webkit)"
    history = [night_line(1, "2026-11-15"), night_line(2, "2026-11-16", {red: "failure"})]
    row = next(r for r in rows(history, NOW) if r["name"] == "End-to-end in three browsers")
    assert row["group"] == "platforms" and row["state"] == "red" and row["since"] == "2026-11-16"
    assert [(c["label"], c["state"]) for c in row["cells"]] == [
        ("Chrome", "green"), ("Firefox", "green"), ("WebKit", "red")]
    assert [f["job"] for f in row["failed"]] == [red]
    assert [n["state"] for n in row["nights"]] == ["green", "red"]


def test_a_skipped_night_turns_the_rows_grey_as_in_the_issue():
    assert rows([night_line(1, "2026-11-16")], NOW)[0]["state"] == "green"  # yesterday
    assert rows([night_line(1, "2026-11-15")], NOW)[0]["state"] == "grey"  # two days ago
    assert desk_bench.NIGHT_DAYS == __import__("desk").NIGHT_DAYS


def test_a_missed_budget_turns_the_start_up_row_red_not_the_platform():
    slow = "systems (macos-15-intel, 3.13)"
    found = rows([night_line(1, "2026-11-16", {slow: "slow"})], NOW)
    start = next(r for r in found if r["name"] == "Start-up time")
    assert start["state"] == "red"
    assert [c["state"] for c in start["cells"]] == ["green", "red", "green", "green"]


def test_the_cpu_and_memory_row_reads_only_the_use_job_of_use_yml():
    history = [night_line(1, "2026-11-16"), use_line(2, "2026-11-15"),
               use_line(3, "2026-11-16", "failure")]
    row = next(r for r in rows(history, NOW) if r["name"] == "CPU and memory")
    assert row["group"] == "platforms" and row["state"] == "red" and row["since"] == "2026-11-16"
    assert [(c["label"], c["state"]) for c in row["cells"]] == [("Linux · x86_64", "red")]
    assert [f["job"] for f in row["failed"]] == ["use"]  # use-store is no part
    assert [n["state"] for n in row["nights"]] == ["green", "red"]
    assert row["url"] == RUN_URL.format(3)


def test_an_old_newest_run_is_grey():
    found = rows([night_line(1, "2026-11-10")], NOW)
    assert {r["state"] for r in found[:-1]} == {"grey"}


def tagged(run_id, version, night, sha, first, complete):
    return record("release.yml", run(run_id, night, head_branch=f"v{version}", head_sha=sha),
                  [job("build (macos-latest)", job_id=run_id)], version,
                  {"build (macos-latest)": {"first": first, "complete": complete}})


def on(line, sha):
    return {**line, "sha": sha}


def test_start_up_is_per_release_on_its_own_commit_and_main_comes_last():
    mac, arm = "systems (macos-latest, 3.14)", "systems (ubuntu-24.04-arm, 3.13)"
    history = [
        tagged(40, "0.10.0", "2026-11-10", "c" * 40, 0.5, 0.6),
        tagged(50, "0.9.2", "2026-11-09", "b" * 40, 0.6, 0.7),
        # A night on 0.9.2's own commit counts for 0.9.2, on every system.
        on(night_line(1, "2026-11-11", times={mac: {"first": 1.0, "complete": 0.9},
                                              arm: {"first": 1.0, "complete": 1.1}}), "b" * 40),
        # Nights on later commits belong to no release; the newest of them is "main".
        on(night_line(2, "2026-11-15", times={mac: {"first": 2.0, "complete": 2.0}}), "d" * 40),
        on(night_line(3, "2026-11-16", times={mac: {"first": 0.9, "complete": 1.0}}), "e" * 40),
    ]
    found = startup(history)
    assert found["versions"] == ["0.9.2", "0.10.0", "main"]  # by number, then main
    mac_line, intel, _linux, arm_line = found["systems"]
    assert mac_line["first"] == [0.8, 0.5, 0.9] and mac_line["runs"] == [2, 1, 1]
    assert intel["first"] == [None, None, None]
    assert arm_line["first"] == [1.0, None, None]
    assert found["main_night"] == "2026-11-16"
    assert found["budgets"] == {"first": 2.0, "complete": 5.0}
    assert startup([night_line(1, "2026-11-16")]) is None


def test_a_night_on_a_release_commit_is_not_main():
    history = [tagged(50, "0.9.2", "2026-11-09", "b" * 40, 0.6, 0.7),
               on(night_line(1, "2026-11-11", times={"systems (macos-latest, 3.14)": {
                   "first": 1.0, "complete": 0.9}}), "b" * 40)]
    assert startup(history)["versions"] == ["0.9.2"]


def test_gate_shows_each_step_once_worst_over_both_systems():
    steps = lambda lint, audit: [  # noqa: E731
        {"name": "Run uv run ruff check .", "conclusion": lint},
        {"name": "Run uv run ruff format --check .", "conclusion": "success"},
        {"name": "The real keyring (Ubuntu)", "conclusion": "skipped"},
        {"name": "Run uv run --with pip-audit==2.10.1 pip-audit", "conclusion": audit},
        {"name": "Run uv build", "conclusion": "success"},
        {"name": "Post Run actions/checkout", "conclusion": "success"}]
    jobs = [job("build (macos-latest)", job_id=1, steps=steps("success", "success")),
            job("build (ubuntu-latest)", job_id=2, steps=steps("failure", "success")),
            job("autotag", job_id=3, steps=[{"name": "Run uv build", "conclusion": "failure"}])]
    found = gate(jobs, {"head_sha": "f" * 40, "updated_at": "2026-11-16T18:29:27Z",
                        "html_url": RUN_URL.format(5)})
    assert [(s["name"], s["state"]) for s in found["steps"]] == [
        ("Lint", "red"), ("Dependency audit", "green"), ("Package", "green")]
    assert found["state"] == "red" and found["sha"] == "f" * 40
    assert found["steps"][0]["url"] == JOB_URL.format(7, 2)  # the job where it is worst
    assert gate(None, {}) is None


def test_a_build_job_red_on_a_step_the_gate_does_not_name_is_not_green():
    steps = [{"name": "A keyring on the session bus (Ubuntu)", "conclusion": "failure"},
             {"name": "Run uv run pyright", "conclusion": "skipped"}]
    jobs = [job("build (macos-latest)", job_id=1,
                steps=[{"name": "Run uv run pyright", "conclusion": "success"}]),
            job("build (ubuntu-latest)", "failure", 2, steps)]
    found = gate(jobs, {"head_sha": "f" * 40})
    assert found["state"] == "red"
    assert ("Other: A keyring on the session bus (Ubuntu)", "red") in [
        (s["name"], s["state"]) for s in found["steps"]]
    running = gate([job("build (macos-latest)", None, 1, [])], {"head_sha": "f" * 40})
    assert running["state"] == "grey"  # not finished: neither passed nor failed


def issue(number, *labels, state="open"):
    return {"number": number, "state": state, "labels": [{"name": n} for n in labels]}


def test_bugs_and_upstream_count_open_issues_by_label():
    issues = [issue(1, "bug"), issue(2, "bug", state="closed"), issue(3, "bug", "automated"),
              issue(4, "client-change", "confirmed"), issue(5, "client-change"),
              issue(6, "client-change", "summary"), issue(7, "client-change", "confirmed",
                                                         state="closed")]
    assert bugs(issues, "o/r")["open"] == 2
    up = upstream(issues, 1.04, "o/r")
    assert (up["confirmed"], up["unconfirmed"], up["watcher_days"]) == (1, 1, 1.0)
    assert bugs(None, "o/r") is None and upstream(None, None, "o/r") is None


def test_stores_compare_with_the_newest_release():
    newest = {"version": "0.9.2", "at": "2026-11-14T17:20:54Z", "url": "u"}
    seen = {"pypi": {"version": "0.9.2", "at": "t", "url": "p"},
            "homebrew": {"version": "0.9.1", "at": None, "url": "h"},
            "registry": None,
            "glama": {"version": None, "listed": True, "url": "g", "note": "Listed"}}
    found = {s["id"]: s for s in stores(newest, seen)["stores"]}
    assert found["pypi"]["state"] == "green" and found["homebrew"]["state"] == "amber"
    assert found["registry"]["state"] == "grey" and found["glama"]["state"] == "green"
    assert found["claude-plugin"]["state"] == "planned"
    assert found["mcprush"]["state"] == "grey"  # not read in this test
    assert stores(None, seen)["stores"][0]["state"] == "grey"  # nothing to match it against


def test_the_tag_s_startup_jobs_and_the_one_off_history_fill_the_other_systems():
    release = record("release.yml",
                     run(60, "2026-11-17", head_branch="v0.10.1", head_sha="f" * 40),
                     [job("startup (ubuntu-24.04-arm)", job_id=61)], "0.10.1",
                     {"startup (ubuntu-24.04-arm)": {"first": 0.7, "complete": 0.8}})
    history = record("startup-history.yml", run(70, "2026-11-19", head_branch="main"),
                     [job("startup (macos-15-intel, v0.9.1)", job_id=71),
                      job("startup (macos-15-intel, v0.10.1)", job_id=72),
                      job("startup (ubuntu-24.04-arm, nonsense)", job_id=73)], None,
                     {"startup (macos-15-intel, v0.9.1)": {"first": 1.6, "complete": 2.0},
                      "startup (macos-15-intel, v0.10.1)": {"first": 1.5, "complete": 1.9},
                      "startup (ubuntu-24.04-arm, nonsense)": {"first": 9.0, "complete": 9.0}})
    found = startup([release, history])
    assert found["versions"] == ["0.9.1", "0.10.1"]
    _mac, intel, _linux, arm = found["systems"]
    assert intel["first"] == [1.6, 1.5] and arm["first"] == [None, 0.7]  # no tag: not counted
    nights = [night_line(i, f"2026-11-{i:02}") for i in range(1, 11)]
    assert 70 in [line["id"] for line in merge([history], nights, keep=2)]  # kept for good
