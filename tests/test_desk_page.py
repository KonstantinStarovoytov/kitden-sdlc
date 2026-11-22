"""The desk page (docs/desk): its words match the ci-failure issues', its headline follows the
bench, every text goes in as text, and a link goes only to GitHub or a store Kitden is published in.
view.js runs in Node; without Node those tests are skipped."""
import json
import re
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest

import count_reviews
import desk_bench
import desk_post
from tests.test_desk_bench import night_line, use_chart, use_line, use_point
from tests.test_desk_post import DESK

ROOT = Path(__file__).resolve().parent.parent
VIEW = ROOT / "docs/desk/view.js"
PAGE = (ROOT / "docs/desk/index.html").read_text()
NODE = shutil.which("node")
needs_node = pytest.mark.skipif(NODE is None, reason="Node is not installed")
NOW = datetime(2026, 11, 17, 7, tzinfo=UTC)
ALLOWED = re.compile(r"^https://(github\.com|pypi\.org|registry\.modelcontextprotocol\.io|"
                     r"glama\.ai|mcprush\.com)/")

# Reads {call, desk, now} as JSON on stdin and prints what view.js gives back, as JSON.
RUNNER = """
const m = await import(process.argv[1]);
let text = '';
for await (const chunk of process.stdin) text += chunk;
const input = JSON.parse(text);
// For 'release', `desk` is {url: body} of saved GitHub answers; 404 is a missing file.
const get = async url => {
  if (!Object.hasOwn(input.desk, url)) throw new Error(`no answer for ${url}`);
  const body = input.desk[url];
  return body === 404 ? null : typeof body === 'string' ? body : JSON.stringify(body);
};
const out = input.call === 'consts'
  ? Object.fromEntries(Object.entries(m).filter(([, v]) => typeof v !== 'function'))
  : input.call === 'release'
    ? await m.releaseNow(get, new Date(input.now)).catch(e => ({ error: e.message }))
    : m.view(input.desk, new Date(input.now));
process.stdout.write(JSON.stringify(out));
"""


def node(call: str, desk: dict | None = None, now: datetime = NOW):
    result = subprocess.run(
        [NODE, "--input-type=module", "-e", RUNNER, VIEW.as_uri()],
        input=json.dumps({"call": call, "desk": desk, "now": now.isoformat()}),
        capture_output=True, text=True, check=True, timeout=30,
    )
    return json.loads(result.stdout)


def pieces(value):
    """Every piece in a view, however deep: strings, {code} and {text, href}."""
    if isinstance(value, list):
        for item in value:
            yield from pieces(item)
    elif isinstance(value, dict) and not ({"text", "href"} >= value.keys() or "code" in value):
        for item in value.values():
            yield from pieces(item)
    else:
        yield value


def hrefs(view) -> list[str]:
    found = [p["href"] for p in pieces(view) if isinstance(p, dict) and "href" in p]
    for key in ("url", "run"):
        found += [v for v in _values(view, key) if isinstance(v, str)]
    return found


def _values(value, key):
    if isinstance(value, dict):
        for k, v in value.items():
            if k == key:
                yield v
            yield from _values(v, key)
    elif isinstance(value, list):
        for item in value:
            yield from _values(item, key)


GREEN_LIGHTS = [{"id": i, "name": i.capitalize(), "state": "green", "why": ""}
                for i in ("works", "clients", "bugs", "agents", "queue")]
NEWEST = {"version": "0.9.2", "at": "2026-11-14T17:20:54Z",
          "url": "https://github.com/KonstantinStarovoytov/kitden/releases/tag/v0.9.2"}
SEEN = {"pypi": {"version": "0.9.2", "at": "2026-11-14T17:20:42Z",
                 "url": "https://pypi.org/project/kitden/0.9.2/"},
        "homebrew": {"version": "0.9.2", "at": None,
                     "url": "https://github.com/konstantinstarovoytov/homebrew-tap"},
        "registry": {"version": "0.9.2", "at": "2026-11-14T17:21:14Z",
                     "url": "https://registry.modelcontextprotocol.io/v0/servers?search="
                            "io.github.KonstantinStarovoytov/kitden"},
        "glama": {"version": None, "listed": True, "note": "Listed",
                  "url": "https://glama.ai/mcp/servers/KonstantinStarovoytov/kitden"},
        "mcprush": {"version": "0.9.2", "at": None,
                    "url": "https://mcprush.com/konstantinstarovoytov/kitden-mcp"}}
GATE = {"sha": "f" * 40, "at": "2026-11-16T18:29:27Z", "state": "green",
        "url": "https://github.com/KonstantinStarovoytov/kitden/actions/runs/5",
        "steps": [{"name": "Lint", "state": "green", "url": None}]}
MAC = "systems (macos-latest, 3.14)"


def desk(history=None, lights=GREEN_LIGHTS, seen=SEEN, gate=GATE, use_chart=None, **changes):
    """A desk.json the way desk_gather writes it, with a bench from `history`."""
    history = history if history is not None else [night_line(1, "2026-11-16"),
                                                   use_line(2, "2026-11-16")]
    bench = desk_bench.bench(history, NOW, gate_read=gate, newest=NEWEST, seen=seen,
                             issues=[], watch_days=0.5, repo="KonstantinStarovoytov/kitden",
                             use_chart=use_chart)
    return {**DESK, "updated": "2026-11-17T06:41:00Z", "lights": lights, "waiting": [],
            "bench": bench, **changes}


@needs_node
def test_the_page_says_what_the_ci_failure_issues_say():
    consts = node("consts")
    assert consts["MEANS"] == desk_post.MEANS and consts["MEANS_ELSE"] == desk_post.MEANS_ELSE
    assert consts["REPO"] == count_reviews.REPO and consts["NIGHTS"] == desk_bench.NIGHTS
    assert "CHECKS" not in consts and "OVERALL" not in consts  # the issue's, gone with it


@needs_node
def test_all_green_reads_all_good_and_every_store_has_the_release():
    view = node("view", desk())
    assert view["head"] == {"state": "green", "text": "All good."}
    assert view["says"] == "Kitden 0.9.2 is the newest release, and every store has it."
    assert [t["name"] for t in view["stores"]["tiles"]] == [
        "PyPI", "Homebrew", "MCP Registry", "Glama", "MCP Rush", "Claude plugin"]
    assert [t["version"] for t in view["stores"]["tiles"][3:]] == ["Listed", "0.9.2", "Planned"]
    assert view["updated"] == "Updated 19 minutes ago"


@needs_node
def test_a_red_platform_blocks_and_says_which():
    red = "systems (ubuntu-24.04-arm, 3.14)"
    view = node("view", desk([night_line(1, "2026-11-15", {red: "failure"}),
                              night_line(2, "2026-11-16", {red: "failure"})]))
    assert view["head"] == {"state": "red", "text": "Blocked: Linux · arm64 is red."}
    arm = next(r for r in view["bench"]["platforms"] if r["name"] == "Linux · arm64")
    assert arm["since"] == "Red since 15 Nov" and arm["means"] == desk_post.MEANS["systems"]
    assert arm["failed"][0]["step"] == 'the step "Run uv run pytest -q" failed'


@needs_node
def test_a_red_browser_engine_blocks_and_says_what_it_means():
    view = node("view", desk([night_line(1, "2026-11-16", {"engines (firefox)": "failure"})]))
    assert view["head"] == {"state": "red", "text": "Blocked: End-to-end in three browsers is red."}
    row = next(r for r in view["bench"]["platforms"] if r["name"] == "End-to-end in three browsers")
    assert [c["label"] for c in row["cells"]] == ["Chrome", "Firefox", "WebKit"]
    assert row["means"] == desk_post.MEANS["engines"]


@needs_node
def test_a_failed_check_on_main_blocks():
    view = node("view", desk(gate={**GATE, "state": "red"}))
    assert view["head"] == {"state": "red", "text": "A check on main failed."}


@needs_node
def test_a_red_cpu_and_memory_night_blocks_and_says_what_it_means():
    view = node("view", desk([night_line(1, "2026-11-16"), use_line(2, "2026-11-16", "failure")]))
    assert view["head"] == {"state": "red", "text": "Blocked: CPU and memory is red."}
    row = next(r for r in view["bench"]["platforms"] if r["name"] == "CPU and memory")
    assert row["means"] == desk_post.MEANS["use"]


@needs_node
def test_compatibility_and_a_store_behind_only_need_a_look():
    red = "clients (ubuntu-latest)"
    view = node("view", desk([night_line(1, "2026-11-16", {red: "failure"})]))
    assert view["head"]["state"] == "amber"
    behind = node("view", desk(seen={**SEEN, "homebrew": {**SEEN["homebrew"], "version": "0.9.1"}}))
    assert behind["head"]["state"] == "amber"
    assert behind["says"] == "Kitden 0.9.2 is the newest release; Homebrew is on 0.9.1."


@needs_node
def test_without_a_bench_the_page_says_parts_were_not_read():
    view = node("view", {**DESK, "lights": GREEN_LIGHTS})
    assert view["head"]["state"] == "grey" and view["bench"] is None and view["gate"] is None


@needs_node
def test_every_strip_has_the_same_length():
    view = node("view", desk())
    strips = [r["nights"] for r in view["bench"]["platforms"] + view["bench"]["compatibility"]]
    assert {len(s) for s in strips} == {desk_bench.NIGHTS}
    assert strips[0][-1]["state"] == "green" and strips[0][0]["state"] == "empty"


def release(run_id, version, first, complete):
    return desk_bench.record(
        "release.yml", {"id": run_id, "created_at": "2026-11-10T00:00:00Z",
                        "head_branch": f"v{version}", "head_sha": f"{run_id:040d}"},
        [{"name": "build (macos-latest)"}], version,
        {"build (macos-latest)": {"first": first, "complete": complete}})


@needs_node
def test_start_up_marks_a_point_only_when_it_is_clearly_slower():
    linux = {"systems (ubuntu-latest, 3.14)": {"first": 0.35, "complete": 0.4}}
    history = [release(1, "0.9.0", 0.5, 0.5), release(2, "0.9.1", 0.5, 0.5),
               release(3, "0.9.2", 0.7, 0.6),
               night_line(9, "2026-11-16", times=linux, version="0.9.2")]
    view = node("view", desk(history))
    s = view["startup"]
    assert s["versions"] == ["0.9.0", "0.9.1", "0.9.2", "main"] and s["newest"] == "main"
    assert s["mainNight"] == "16 Nov"
    mac, intel, lin, _arm = s["rows"]
    assert mac["first"] == "—"  # main's night measured only Linux
    assert lin["first"] == "350 ms" and lin["fastest"] == "fastest"
    assert intel["slower"] is False
    releases = node("view", desk([release(1, "0.9.1", 0.5, 0.5), release(2, "0.9.2", 0.7, 0.6)]))
    first = releases["startup"]["rows"][0]
    assert first["slower"] is True and first["change"] == "+40% vs 0.9.1"  # 0.2 s and 40%
    noise = node("view", desk([release(1, "0.9.1", 0.5, 0.5), release(2, "0.9.2", 0.6, 0.5)]))
    assert noise["startup"]["rows"][0]["slower"] is False  # 0.1 s is within one run's noise
    slow = node("view", desk([release(1, "0.9.1", 3.0, 3.0), release(2, "0.9.2", 3.3, 3.3)]))
    assert slow["startup"]["rows"][0]["slower"] is False  # 0.3 s, but only 10%


@needs_node
def test_the_cpu_and_memory_charts_show_one_backfill_run_and_say_where():
    chart = use_chart(use_point("0.9.1"), use_point("0.9.2"), use_point("main", "abc1234"))
    use = node("view", desk(use_chart=chart))["use"]
    assert use["versions"] == ["0.9.1", "0.9.2", "main"]
    cpu, memory = use["charts"]
    assert (cpu["title"], memory["title"]) == ("CPU to ready by release", "Peak memory by release")
    assert cpu["points"][-1] == {"median": 0.7, "text": "700 ms", "range": "660 ms–770 ms"}
    assert memory["points"][0] == {"median": 58, "text": "58 MB", "range": "57.4 MB–58.9 MB"}
    assert memory["change"] == "0% vs 0.9.2"
    assert use["note"] == (
        "Measured 19 Nov on AMD EPYC 7763; main = abc1234. Each dot is the median of 5 runs; "
        "point at a dot for its lowest and highest run.")
    assert node("view", desk())["use"] is None


@needs_node
def test_a_red_light_that_does_not_block_needs_a_look_and_a_red_works_blocks():
    lights = [dict(light) for light in GREEN_LIGHTS]
    lights[1] = {**lights[1], "state": "red", "why": "The client tests are red."}
    assert node("view", desk(lights=lights))["head"]["state"] == "amber"
    lights = [dict(light) for light in GREEN_LIGHTS]
    lights[0] = {**lights[0], "state": "red", "why": "A required check failed."}
    assert node("view", desk(lights=lights))["head"] == {"state": "red",
                                                         "text": "A check on main failed."}


@needs_node
def test_an_unfinished_gate_or_a_missing_platform_job_is_grey_not_green():
    assert node("view", desk(gate={**GATE, "state": "grey"}))["head"]["state"] == "grey"
    line = night_line(1, "2026-11-16")
    line["jobs"] = [j for j in line["jobs"] if j["name"] != "browser"]
    assert node("view", desk([line]))["head"]["state"] == "grey"


@needs_node
def test_text_stays_text_and_links_go_only_to_github_or_a_store():
    hostile = desk(waiting=[{"kind": "<b>x</b>", "title": "[x](https://evil.example)",
                             "url": "javascript:alert(1)", "do": "Do it."}],
                   seen={**SEEN, "pypi": {**SEEN["pypi"], "url": "https://evil.example/p"}},
                   gate={**GATE, "url": "https://evil.example/run"})
    hostile["bench"]["rows"][0]["url"] = "https://evil.example/r"
    view = node("view", hostile)
    assert view["waiting"][0]["kind"] == "<b>x</b>"
    assert view["waiting"][0]["title"] == ["[x](https://evil.example)"]  # text, no link
    assert view["stores"]["tiles"][0]["url"] is None and view["gate"]["url"] is None
    assert view["bench"]["platforms"][0]["run"] is None
    assert all(ALLOWED.match(h) for h in hrefs(view) if h)


@needs_node
def test_a_key_from_the_data_never_reaches_an_objects_own_properties():
    view = node("view", desk(waiting=[{"kind": "constructor", "title": "t"}]))
    assert view["waiting"][0]["kind"] == "constructor"


def test_the_page_puts_no_text_in_as_html_and_reads_only_desk_json_and_kitdens_runs():
    script = PAGE.split('<script type="module" blocking="render">', 1)[1]
    assert not re.search(r"innerHTML|outerHTML|insertAdjacentHTML|document\.write|eval\(", script)
    assert "connect-src https://raw.githubusercontent.com https://api.github.com;" in PAGE
    view = VIEW.read_text()
    assert re.findall(r"https://raw\.githubusercontent\.com/[^'`]+", view) == [
        "https://raw.githubusercontent.com/KonstantinStarovoytov/kitden-sdlc/numbers/desk.json",
        "https://raw.githubusercontent.com/${REPO}/",
    ]
    assert re.findall(r"https://api\.github\.com/[^'`]+", view) == ["https://api.github.com/repos/${REPO}"]


def test_the_page_loads_this_view_js_and_says_so_when_it_cannot_start():
    import hashlib

    digest = hashlib.sha256(VIEW.read_bytes()).hexdigest()[:12]
    assert f"from './view.js?v={digest}';" in PAGE, "after a change to view.js, set the new ?v="
    assert "document.documentElement.dataset.started = 'yes';" in PAGE
    assert "The page could not start. Reload it." in PAGE


# --- The release strip: GitHub's answers as they were on 14 and 17 Nov, trimmed ---

FIXTURES = ROOT / "tests/fixtures/desk_release"


def release_of(case: str, now: str | None = None):
    saved = json.loads((FIXTURES / f"{case}.json").read_text())
    when = datetime.fromisoformat(now or saved["now"])
    return node("release", saved["answers"], when)


def marks(strip):
    return [(s["name"], s["state"]) for s in strip["steps"]]


def states(strip):
    """The steps' states, after checking the steps are all there, in order."""
    assert [s["name"] for s in strip["steps"]] == STEPS
    return [s["state"] for s in strip["steps"]]


def note(step):
    return "".join(p if isinstance(p, str) else p["text"] for p in step["note"])


STEPS = ["Pull request", "Checks on main", "Tag", "Build", "PyPI", "GitHub release", "Stores"]
RUN = "https://github.com/KonstantinStarovoytov/kitden/actions/runs/44126374060"


@needs_node
def test_a_job_without_a_machine_says_which_machine_it_waits_for_and_how_long():
    strip = release_of("queued")
    assert strip["version"] == "0.10.0" and strip["url"] == RUN
    assert states(strip) == ["done", "done", "done", "now", "ahead", "ahead", "ahead"]
    assert note(strip["steps"][3]) == "waiting for a macOS machine · 12 min"
    assert [note(s) for s in strip["steps"] if s["state"] != "now"] == [""] * 6


@needs_node
def test_a_rerun_is_read_by_its_newest_attempt_and_a_later_step_can_wait_too():
    # Attempt 2: the Ubuntu build was carried from attempt 1, the macOS build passed, PyPI is
    # done and the GitHub release waits for an Ubuntu machine. A main push after the tag, with
    # the same version, carries no release.
    strip = release_of("running")
    assert states(strip) == ["done", "done", "done", "done", "done", "now", "ahead"]
    assert note(strip["steps"][5]) == "waiting for an Ubuntu machine · 4 min"


@needs_node
def test_a_failed_release_says_why_and_links_to_its_run():
    strip = release_of("failed")
    assert states(strip) == ["done", "done", "done", "failed", "ahead", "ahead", "ahead"]
    build = strip["steps"][3]
    assert note(build) == "the macOS build was cancelled: no machine came in 15 min · Open the run"
    assert build["note"][-1] == {"text": "Open the run", "href": RUN}
    stores = release_of("failed_stores")
    assert stores["version"] == "0.9.2"
    assert marks(stores)[-1] == ("Stores", "failed") and marks(stores)[-2][1] == "done"
    assert note(stores["steps"][-1]).startswith('stores / summary failed at "Write the summary"')


@needs_node
def test_a_release_that_is_out_shows_no_strip():
    assert release_of("released") is None


@needs_node
def test_a_push_to_main_with_a_new_version_shows_the_checks_before_the_tag():
    strip = release_of("main_release")
    assert strip["version"] == "0.10.0"
    assert states(strip) == ["done", "now", "ahead", "ahead", "ahead", "ahead", "ahead"]
    assert note(strip["steps"][1]) == "running on macOS · 6 min"


@needs_node
def test_without_an_answer_there_is_no_strip_and_odd_data_stays_text():
    assert "error" in node("release", {}, NOW)
    saved = json.loads((FIXTURES / "failed.json").read_text())
    answers = saved["answers"]
    runs = answers[next(u for u in answers if u.endswith("per_page=30"))]["workflow_runs"]
    tag = next(r for r in runs if r["head_branch"] == "v0.10.0")
    tag.update(html_url="https://evil.example/run", head_branch="v0.10.0<b>")
    strip = node("release", answers, datetime.fromisoformat(saved["now"]))
    assert strip["url"] is None and strip["version"] == "0.10.0<b>"
    assert all(ALLOWED.match(h) for h in hrefs(strip) if h)


PR = "https://github.com/KonstantinStarovoytov/kitden/pull/136"
AHEAD = ["ahead"] * 6


@needs_node
def test_an_open_release_pull_request_shows_its_checks_then_waits_for_the_merge():
    strip = release_of("pr_checks")
    assert strip["version"] == "0.10.1" and strip["url"] == PR
    assert states(strip) == ["now", *AHEAD]
    assert note(strip["steps"][0]) == "checks running · 4 min"
    ready = release_of("pr_ready")["steps"][0]
    assert ready["state"] == "now"
    assert note(ready) == "waiting for your merge · Open the pull request"
    assert ready["note"][-1] == {"text": "Open the pull request", "href": PR}
    draft = release_of("pr_draft")["steps"][0]
    assert note(draft) == "a draft: finish what its body lists · Open the pull request"


@needs_node
def test_a_release_pull_request_whose_checks_failed_says_so_and_a_closed_one_shows_nothing():
    failed = release_of("pr_failed")["steps"][0]
    assert failed["state"] == "failed" and note(failed) == "a check failed · Open the run"
    assert failed["note"][-1]["href"].startswith(
        "https://github.com/KonstantinStarovoytov/kitden/actions/runs/44186760536")
    assert release_of("pr_closed") is None


@needs_node
def test_only_a_strip_where_something_runs_asks_github_every_minute():
    # Checks, a build or a job waiting for a machine change by the minute; a failed release,
    # a draft or a pull request waiting for the merge waits for a person: the page asks every
    # five minutes then, and with no strip at all.
    running = ["queued", "running", "main_release", "pr_checks"]
    waiting = ["failed", "failed_stores", "pr_ready", "pr_draft", "pr_failed"]
    assert [release_of(c)["live"] for c in running] == [True] * len(running)
    assert [release_of(c)["live"] for c in waiting] == [False] * len(waiting)
