"""The desk page (docs/desk) says what the desk issue says, puts every text in as text, and links
only where the issue would. view.js runs in Node; without Node those tests are skipped."""
import json
import re
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest

import desk_post
from desk import Facts, build
from tests.test_desk import FACTS, NOW, ROSTER
from tests.test_desk_post import DESK

ROOT = Path(__file__).resolve().parent.parent
VIEW = ROOT / "docs/desk/view.js"
PAGE = (ROOT / "docs/desk/index.html").read_text()
NODE = shutil.which("node")
needs_node = pytest.mark.skipif(NODE is None, reason="Node is not installed")
GITHUB = "https://github.com/"

# Reads {call, args} as JSON on stdin and prints what view.js gives back, as JSON.
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
    return [p["href"] for p in pieces(view) if isinstance(p, dict) and "href" in p]


@needs_node
def test_the_page_shares_the_issues_words():
    consts = node("consts")
    assert consts["CHECKS"] == desk_post.CHECKS
    assert consts["OVERALL"] == desk_post.OVERALL
    assert consts["KINDS"] == desk_post.KINDS
    assert consts["MEANS"] == desk_post.MEANS and consts["MEANS_ELSE"] == desk_post.MEANS_ELSE
    assert tuple(consts["SUMMARIES"]) in desk_post.SEARCHES
    assert consts["NOT_MEASURED_YET"] == desk_post.NOT_MEASURED_YET
    assert consts["GREY_SHOWN"] == desk_post.GREY_SHOWN
    assert consts["DATA_PAGE"] == desk_post.DATA and consts["HOW_TO"] == desk_post.HOW_TO
    assert consts["REPO"] == desk_post.REPO


@needs_node
def test_a_desk_the_desk_builds_is_shown_whole():
    for desk in (build(FACTS, ROSTER, NOW), build(Facts(), ROSTER, NOW), DESK):
        view = node("view", desk)
        assert view["lead"] == desk_post.OVERALL[desk["overall"]]
        assert [lt["id"] for lt in view["lights"]] == [lt["id"] for lt in desk["lights"]]
        assert all(href.startswith(GITHUB) for href in hrefs(view))


@needs_node
def test_text_from_a_person_or_a_model_stays_text_and_links_only_to_github():
    desk = {
        **DESK,
        "lights": [
            {"id": "works", "name": "Works", "state": "red", "why": "<img src=x onerror=alert(1)>",
             "url": "https://evil.example/x"},
            {"id": "bugs", "name": "Bugs", "state": "amber", "why": "Issue #12",
             "url": "javascript:alert(1)"},
            {"id": "queue", "name": "Queue", "state": "amber", "why": "Look",
             "url": "https://github.com/KonstantinStarovoytov/kitden/issues/3\"><b>"},
        ],
        "waiting": [{"kind": "<b>new</b>", "title": "[x](https://evil.example)", "url":
                     "https://github.com/KonstantinStarovoytov/kitden/pull/1", "do": "Do it."}],
    }
    view = node("view", desk)
    works, bugs, queue = view["lights"]
    assert works["why"] == "<img src=x onerror=alert(1)>" and works["open"] is None
    assert bugs["why"] == "Issue #12" and bugs["open"] is None
    assert queue["why"] == "Look" and queue["open"] is None
    assert view["waiting"][0]["kind"] == "<b>new</b>"
    assert view["waiting"][0]["title"] == [{
        "text": "[x](https://evil.example)",
        "href": "https://github.com/KonstantinStarovoytov/kitden/pull/1"}]
    assert all(href.startswith(GITHUB) for href in hrefs(view))


@needs_node
def test_an_old_desk_says_so_and_a_missing_part_is_not_measured():
    old = node("view", {**DESK, "updated": "2026-11-14T06:41:00Z"},
               now=datetime(2026, 11, 16, 7, tzinfo=UTC))
    assert old["old"] is True
    fresh = node("view", DESK, now=datetime(2026, 11, 16, 12, tzinfo=UTC))
    assert fresh["old"] is False
    bare = node("view", {"overall": "nonsense"})
    assert bare["overall"] == "grey" and bare["old"] is True
    assert bare["waiting"] is None and bare["nightly"] is None and bare["lights"] == []
    assert bare["updated"] == "Updated at an unknown time"
    assert fresh["updated"] == "Updated 5 hours ago"
    assert fresh["updatedAt"] == "16 Nov 2026, 06:41 UTC"


@needs_node
def test_a_red_and_a_grey_nightly_part_say_since_when():
    rows = [
        {"part": "systems", "state": "red", "since": "2026-11-14", "night": "2026-11-16",
         "run": "https://github.com/o/r/actions/runs/1",
         "failed": [{"job": "test", "step": "pytest", "url": "https://evil.example"}]},
        {"part": "browser", "state": "grey", "grey_since": "2026-11-13", "grey_nights": 3},
        {"part": "clients", "state": "grey", "grey_since": "2026-11-15", "grey_nights": 1,
         "why": "no run"},
    ]
    nightly = node("view", {**DESK, "nightly": rows})["nightly"]
    red, grey, new = nightly["parts"]
    assert nightly["mixed"] is True and nightly["night"] is None
    assert red["note"] == "Red since 14 Nov" and red["means"] == desk_post.MEANS["systems"]
    assert red["failed"] == [{"job": ["test"], "step": 'the step "pytest" failed'}]
    assert grey["note"] == "No finished run since 13 Nov" and grey["run"] is None
    assert new["note"] == "no run" and new["night"] is None


@needs_node
def test_one_night_is_named_once():
    rows = [{"part": p, "state": "green", "night": "2026-11-16"} for p in ("systems", "test")]
    nightly = node("view", {**DESK, "nightly": rows})["nightly"]
    assert nightly["night"] == "16 Nov" and nightly["mixed"] is False


@needs_node
def test_the_page_drops_what_the_owner_does_not_want_shown():
    view = node("view", DESK)
    assert set(view) == {"overall", "lead", "updated", "updatedAt", "old", "lights", "waiting",
                         "nightly", "map", "summaries"}
    assert view["summaries"]["text"] == "The watcher's weekly summaries"
    assert view["summaries"]["href"].startswith(GITHUB + "KonstantinStarovoytov/kitden/issues?q=")


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


@needs_node
def test_a_key_from_the_data_never_reaches_an_objects_own_properties():
    desk = {**DESK, "lights": [{"id": "constructor", "name": "X", "state": "red", "why": "y"}],
            "waiting": [{"kind": "constructor", "title": "t"}],
            "nightly": [{"part": "constructor", "state": "red"}]}
    view = node("view", desk)
    assert view["lights"][0]["checks"] == []
    assert view["waiting"][0]["kind"] == "constructor"
    assert view["nightly"]["parts"][0]["means"] == desk_post.MEANS_ELSE


@needs_node
def test_no_light_read_is_no_green_headline_and_short_waits_are_hours():
    view = node("view", {**DESK, "overall": "green", "lights": [],
                         "waiting": [{"kind": "pull", "title": "t", "days": 0.3}]})
    assert view["overall"] == "grey" and view["lead"] == desk_post.OVERALL["grey"]
    assert view["waiting"][0]["days"] == "Waiting 7 hours."


@needs_node
def test_the_workflow_most_parts_share_is_said_once():
    rows = [{"part": p, "state": "green", "name": "Nightly tests"} for p in ("a", "b")]
    rows.append({"part": "test", "state": "green", "name": "Newest dependencies"})
    nightly = node("view", {**DESK, "nightly": rows})["nightly"]
    assert nightly["common"] == "Nightly tests"
    assert [p["of"] for p in nightly["parts"]] == ["", "", "Newest dependencies"]
