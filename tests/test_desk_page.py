"""The desk page (docs/desk): its words match the desk issue's, its headline follows the bench,
every text goes in as text, and a link goes only to GitHub or a store Kitden is published in.
view.js runs in Node; without Node those tests are skipped."""
import json
import re
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest

import desk_bench
import desk_post
from tests.test_desk_bench import night_line
from tests.test_desk_post import DESK

ROOT = Path(__file__).resolve().parent.parent
VIEW = ROOT / "docs/desk/view.js"
PAGE = (ROOT / "docs/desk/index.html").read_text()
NODE = shutil.which("node")
needs_node = pytest.mark.skipif(NODE is None, reason="Node is not installed")
NOW = datetime(2026, 11, 17, 7, tzinfo=UTC)
ALLOWED = re.compile(r"^https://(github\.com|pypi\.org|registry\.modelcontextprotocol\.io|"
                     r"glama\.ai)/")

# Reads {call, desk, now} as JSON on stdin and prints what view.js gives back, as JSON.
RUNNER = """
const m = await import(process.argv[1]);
let text = '';
for await (const chunk of process.stdin) text += chunk;
const input = JSON.parse(text);
const out = input.call === 'consts'
  ? Object.fromEntries(Object.entries(m).filter(([, v]) => typeof v !== 'function'))
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
                  "url": "https://glama.ai/mcp/servers/KonstantinStarovoytov/kitden"}}
GATE = {"sha": "f" * 40, "at": "2026-11-16T18:29:27Z", "state": "green",
        "url": "https://github.com/KonstantinStarovoytov/kitden/actions/runs/5",
        "steps": [{"name": "Lint", "state": "green", "url": None}]}
MAC = "systems (macos-latest, 3.14)"


def desk(history=None, lights=GREEN_LIGHTS, seen=SEEN, gate=GATE, **changes):
    """A desk.json the way desk_gather writes it, with a bench from `history`."""
    history = history if history is not None else [night_line(1, "2026-11-16")]
    bench = desk_bench.bench(history, NOW, gate_read=gate, newest=NEWEST, seen=seen,
                             issues=[], watch_days=0.5, repo="KonstantinStarovoytov/kitden")
    return {**DESK, "updated": "2026-11-17T06:41:00Z", "lights": lights, "waiting": [],
            "bench": bench, **changes}


@needs_node
def test_the_page_shares_the_issues_words():
    consts = node("consts")
    assert consts["CHECKS"] == desk_post.CHECKS
    assert consts["OVERALL"] == desk_post.OVERALL
    assert consts["KINDS"] == desk_post.KINDS
    assert consts["MEANS"] == desk_post.MEANS and consts["MEANS_ELSE"] == desk_post.MEANS_ELSE
    assert tuple(consts["SUMMARIES"]) in desk_post.SEARCHES
    assert consts["NOT_MEASURED_YET"] == desk_post.NOT_MEASURED_YET
    assert consts["DATA_PAGE"] == desk_post.DATA and consts["HOW_TO"] == desk_post.HOW_TO
    assert consts["REPO"] == desk_post.REPO and consts["NIGHTS"] == desk_bench.NIGHTS


@needs_node
def test_all_green_reads_all_good_and_every_store_has_the_release():
    view = node("view", desk())
    assert view["head"] == {"state": "green", "text": "All good."}
    assert view["says"] == "Kitden 0.9.2 is the newest release, and every store has it."
    assert [t["name"] for t in view["stores"]["tiles"]] == [
        "PyPI", "Homebrew", "MCP Registry", "Glama", "Claude plugin"]
    assert view["stores"]["tiles"][3]["version"] == "Listed"
    assert view["stores"]["tiles"][4]["version"] == "Planned"
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
def test_a_failed_check_on_main_blocks():
    view = node("view", desk(gate={**GATE, "state": "red"}))
    assert view["head"] == {"state": "red", "text": "A check on main failed."}


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


def test_the_page_puts_no_text_in_as_html_and_reads_only_desk_json():
    script = PAGE.split('<script type="module">', 1)[1]
    assert not re.search(r"innerHTML|outerHTML|insertAdjacentHTML|document\.write|eval\(", script)
    assert "connect-src https://raw.githubusercontent.com;" in PAGE
    view = VIEW.read_text()
    assert re.findall(r"https://raw\.githubusercontent\.com/[^']+", view) == [
        "https://raw.githubusercontent.com/KonstantinStarovoytov/kitden-sdlc/numbers/desk.json",
    ]


def test_the_issue_links_the_page():
    assert desk_post.PAGE in desk_post.render(DESK)
