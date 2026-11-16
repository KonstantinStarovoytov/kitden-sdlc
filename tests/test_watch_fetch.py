import copy
import hashlib
import json
from datetime import date, timedelta

import pytest

import watch_fetch
from doc_address import load_hosts
from watch_feed import KEEP_DAYS, Entry, page_key
from watch_fetch import (
    DOC_FORMAT,
    FAIL_DAYS,
    FEED_PAGES_MAX,
    FEED_PIECES_MAX,
    HEADING_CHARS,
    HEADINGS_MAX,
    PIECE_CHARS,
    PIECES_MAX,
    TAKEN_MAX,
    WAIT_MAX,
    _moved_item,
    build_input,
    plan_feed,
    plan_moved,
    plan_run,
    read_or_none,
)
from watch_pages import Section, sections

META = {"s": {"client": "codex", "kind": "release", "url": "https://x/s"}}
EMPTY = {"fails": {}, "kept": [], "urgent": {"week": "", "count": 0}, "doc_format": DOC_FORMAT}
DOC_META = {
    "https://d": {"client": "cursor", "kind": "doc", "url": "https://d"},
    "r": {"client": "codex", "kind": "release", "url": "https://x/r"},
}


def old(sources, **extra):
    return {"sources": sources, **EMPTY, **extra}


def test_first_run_fills_and_makes_no_pieces():
    pieces, state = plan_run(None, {"s": [Section("1.0", "t", "h")]}, META)
    assert pieces == [] and state["sources"]["s"] == {"1.0": "h"}
    assert state["summary_week"] == "" and state["tries"] == {}
    assert state["doc_format"] == DOC_FORMAT == 2


def test_source_new_to_memory_makes_no_pieces():
    pieces, state = plan_run(old({"o": {}}), {"s": [Section("1.0", "t", "h")]}, META)
    assert pieces == [] and state["sources"]["s"] == {"1.0": "h"}


def test_new_section_is_a_piece_and_not_yet_seen():
    pieces, state = plan_run(
        old({"s": {"1.0": "h"}}),
        {"s": [Section("1.1", "t2", "h2"), Section("1.0", "t", "h")]},
        META,
    )
    assert [p["id"] for p in pieces] == ["s#1.1"]
    assert pieces[0]["version"] == "1.1" and pieces[0]["client"] == "codex"
    assert "1.1" not in state["sources"]["s"]


def test_changed_hash_is_a_piece_and_text_is_cut():
    long = "x" * (PIECE_CHARS + 5)
    pieces, state = plan_run(old({"s": {"1.0": "h"}}), {"s": [Section("1.0", long, "new")]}, META)
    assert len(pieces) == 1 and len(pieces[0]["text"]) == PIECE_CHARS
    assert state["sources"]["s"]["1.0"] == "h"


def test_vanished_section_stays_in_state():
    got = {"s": [Section("1.0", "t", "h")]}
    _, state = plan_run(old({"s": {"1.0": "h", "0.9": "g"}}), got, META)
    assert state["sources"]["s"] == {"1.0": "h", "0.9": "g"}


def test_pieces_are_capped_releases_first_then_docs():
    meta = {
        "d": {"client": "cursor", "kind": "doc", "url": "https://d"},
        "s": {"client": "codex", "kind": "release", "url": "https://x/s"},
    }
    many = [Section(str(i), "t", "h") for i in range(PIECES_MAX)]
    state = old({"d": {}, "s": {}})
    pieces, _ = plan_run(state, {"d": many[:3], "s": many}, meta)
    assert len(pieces) == PIECES_MAX
    assert all(p["source"] == "s" for p in pieces)
    assert pieces[0]["kind"] == "release"
    doc, _ = plan_run(state, {"d": many[:3], "s": []}, meta)
    assert doc[0]["kind"] == "doc" and doc[0]["version"] == "" and doc[0]["url"] == "https://d"


def test_third_failed_day_is_kept_once():
    _, state = plan_run(old({"s": {}}, fails={"s": 2}), {"s": None}, META)
    assert state["fails"]["s"] == FAIL_DAYS and len(state["kept"]) == 1
    item = state["kept"][0]
    assert item["title"] == "Cannot read s for 3 days"
    assert (item["effect"], item["severity"], item["sure"]) == ("unknown", "medium", True)
    _, again = plan_run(state, {"s": None}, META)
    assert len(again["kept"]) == 1


def test_unreadable_source_does_not_stop_others_and_reset_on_success():
    meta = {**META, "t": {"client": "cursor", "kind": "doc", "url": "https://t"}}
    pieces, state = plan_run(
        old({"s": {}, "t": {}}, fails={"t": 2}),
        {"s": None, "t": [Section("a", "t", "h")]},
        meta,
    )
    assert state["fails"] == {"s": 1, "t": 0} and [p["id"] for p in pieces] == ["t#a"]


def test_build_input_reads_files_and_titles(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src/a.py").write_text("hello")
    fake = {"src/a.py": True}
    out = build_input([], tmp_path, "LIST", ["src/a.py", "src/missing.py"],
                      lambda f: fake[f], "v1", ["t1"], {"kept": [{"title": "k"}]})
    assert out["files"] == {"src/a.py": {"text": "hello", "same_in_release": True}}
    assert out["known_titles"] == ["t1", "k"] and out["release"] == "v1"
    json.dumps(out)


def test_failed_source_says_its_id_and_error_type_only(capsys):
    def reader(address):
        raise TimeoutError("secret detail")

    assert read_or_none("https://d", reader, "https://d") is None
    err = capsys.readouterr().err
    assert "https://d" in err and "TimeoutError" in err and "secret detail" not in err


def test_read_passes_the_split_tag_of_a_page_source(monkeypatch):
    html = ("<article><header><h1>A</h1></header>a</article>"
            "<article><header><h1>B</h1></header>b</article>")
    monkeypatch.setattr(watch_fetch, "get", lambda url: (html, "text/html"))
    src = {"id": "c", "kind": "page", "url": "https://c", "level": 2, "split": "article"}
    assert [s.key for s in watch_fetch._read(src)] == ["A", "B"]


def html_era(**extra):
    state = old({
        "https://d": {"Search the docs": "h1", "Suggested": "h2", "Install": "h3"},
        "r": {"1.0": "h"},
    }, **extra)
    del state["doc_format"]
    return state


def test_doc_pages_fill_again_quietly_after_the_switch_to_markdown():
    fetched = {
        "https://d": [Section("Install", "t", "m1"), Section("Remove", "t", "m2")],
        "r": [Section("1.1", "t", "h2"), Section("1.0", "t", "h")],
    }
    pieces, state = plan_run(html_era(), fetched, DOC_META)
    assert [p["id"] for p in pieces] == ["r#1.1"]
    assert state["sources"]["https://d"] == {"Install": "m1", "Remove": "m2"}
    assert state["sources"]["r"] == {"1.0": "h"}
    assert state["fails"]["https://d"] == 0
    assert state["doc_format"] == DOC_FORMAT


def test_a_lower_doc_format_also_fills_again():
    fetched = {"https://d": [Section("Install", "t", "m1")], "r": [Section("1.0", "t", "h")]}
    pieces, state = plan_run(html_era(doc_format=1), fetched, DOC_META)
    assert pieces == [] and state["sources"]["https://d"] == {"Install": "m1"}
    assert state["doc_format"] == DOC_FORMAT


def test_an_unread_doc_page_loses_its_old_hashes_and_fills_on_its_next_read():
    pieces, state = plan_run(html_era(), {"https://d": None, "r": None}, DOC_META)
    assert "https://d" not in state["sources"] and state["sources"]["r"] == {"1.0": "h"}
    assert state["fails"] == {"https://d": 1, "r": 1}
    assert state["doc_format"] == DOC_FORMAT
    pieces, state = plan_run(
        state, {"https://d": [Section("Install", "t", "m1")], "r": None}, DOC_META
    )
    assert pieces == [] and state["sources"]["https://d"] == {"Install": "m1"}


def test_no_html_era_key_survives_for_a_page_that_left_the_list():
    state = html_era()
    state["sources"]["https://gone"] = {"Search the docs": "h9"}
    _, new = plan_run(state, {"https://d": [], "r": []}, DOC_META)
    assert set(new["sources"]) == {"https://d", "r"}


def test_after_the_refill_a_changed_doc_section_is_a_piece_again():
    _, state = plan_run(html_era(), {"https://d": [Section("Install", "t", "m1")]}, DOC_META)
    pieces, _ = plan_run(state, {"https://d": [Section("Install", "t", "m9")]}, DOC_META)
    assert [p["id"] for p in pieces] == ["https://d#Install"]


def test_a_doc_page_is_read_through_get_doc_with_the_given_hosts(monkeypatch):
    seen = []

    def fake_get_doc(address, hosts):
        seen.append((address, hosts))
        return "# Install\nmade-up text\n", "text/markdown", address + ".md"

    monkeypatch.setattr(watch_fetch, "get_doc", fake_get_doc)
    hosts = [("docs.example.com", "/a/")]
    got = watch_fetch._read_doc("https://docs.example.com/a/b", hosts)
    assert [s.key for s in got] == ["Install"]
    assert seen == [("https://docs.example.com/a/b", hosts)]


def test_a_failed_doc_read_counts_as_an_unread_source(monkeypatch):
    def fake_get_doc(address, hosts):
        raise TimeoutError("timed out")

    monkeypatch.setattr(watch_fetch, "get_doc", fake_get_doc)
    address = "https://docs.example.com/a/b"

    def reader(u):
        return watch_fetch._read_doc(u, [])

    assert watch_fetch.read_or_none(address, reader, address) is None


MANIFEST_META = {
    **META,
    "m": {"kind": "manifest", "url": "https://raw.example.com/manifest.json"},
}


def test_a_read_manifest_makes_no_piece_and_no_sources_entry():
    fetched = {"s": [Section("1.0", "t", "h")], "m": {"https://docs.example.com/a/b.md"}}
    pieces, state = plan_run(old({"s": {"1.0": "h"}}, fails={"m": 2}), fetched, MANIFEST_META)
    assert pieces == [] and "m" not in state["sources"]
    assert state["fails"] == {"s": 0, "m": 0}


def test_an_unread_manifest_counts_in_fails_and_its_third_day_has_no_client():
    _, state = plan_run(old({"s": {}}, fails={"m": 2}), {"s": [], "m": None}, MANIFEST_META)
    assert state["fails"]["m"] == FAIL_DAYS and "m" not in state["sources"]
    [item] = state["kept"]
    assert item["title"] == "Cannot read m for 3 days" and item["client"] == ""
    assert item["url"] == "https://raw.example.com/manifest.json"


HOSTS = [("docs.example.com", "/a/")]
WEEK = "2026-W46"
GONE = "https://docs.example.com/a/gone"
LOST = "https://docs.example.com/a/lost"
NEAR = "https://docs.example.com/a/old/near"
HERE = "https://docs.example.com/a/here"
NEW_NEAR = "https://docs.example.com/a/new/near"
PAGES = {GONE: "codex", LOST: "cursor", NEAR: "claude-code",
         "https://docs.example.com/a/kept": "codex"}
MANIFEST = {"https://docs.example.com/a/kept.md", NEW_NEAR + ".md"}


def locate(address):
    return HERE if address == GONE else None


def week_state(**extra):
    return {"kept": [], "fails": {}, "sources": {}, **extra}


def test_a_new_week_puts_each_verdict_into_kept_once():
    state = plan_moved(week_state(), MANIFEST, PAGES, HOSTS, locate, WEEK)
    titles = [k["title"] for k in state["kept"]]
    assert titles == [f"{GONE} moved", f"{LOST} was not found", f"{NEAR} may have moved"]
    for item, client in zip(state["kept"], ["codex", "cursor", "claude-code"], strict=True):
        assert (item["effect"], item["severity"]) == ("outdated", "minor")
        assert item["client"] == client and item["version"] == "" and item["files"] == []
        assert item["url"] in PAGES
        assert "not in Agent Docs" in item["changed"]
    gone, lost, near = state["kept"]
    assert HERE in gone["changed"] and HERE in gone["fix"]
    assert NEW_NEAR in near["changed"] and NEW_NEAR in near["fix"]
    assert state["moved"] == {"week": WEEK, "told": {LOST: "", NEAR: NEW_NEAR}}


def test_each_title_is_under_80_characters_for_a_60_character_address():
    address = "https://docs.example.com/a/" + "x" * 33
    assert len(address) == 60
    for verdict, to in (("moved", HERE), ("maybe", NEW_NEAR), ("absent", "")):
        item = _moved_item({"address": address, "client": "codex", "verdict": verdict,
                            "to": to})
        assert len(item["title"]) < 80 and item["title"].startswith(address)


def test_absent_and_maybe_already_told_are_not_said_again():
    told = {LOST: "", NEAR: NEW_NEAR}
    state = plan_moved(week_state(moved={"week": "2026-W45", "told": told}),
                       MANIFEST, PAGES, HOSTS, locate, WEEK)
    assert [k["title"] for k in state["kept"]] == [f"{GONE} moved"]
    assert state["moved"] == {"week": WEEK, "told": told}


def test_a_maybe_is_said_again_when_its_new_address_differs():
    told = {LOST: "", NEAR: "https://docs.example.com/a/other/near"}
    state = plan_moved(week_state(moved={"week": "2026-W45", "told": told}),
                       MANIFEST, PAGES, HOSTS, locate, WEEK)
    assert [k["url"] for k in state["kept"]] == [GONE, NEAR]
    assert state["moved"]["told"] == {LOST: "", NEAR: NEW_NEAR}


def test_moved_is_said_again_in_a_new_week():
    first = plan_moved(week_state(), MANIFEST, PAGES, HOSTS, locate, "2026-W45")
    again = plan_moved({**first, "kept": []}, MANIFEST, PAGES, HOSTS, locate, WEEK)
    assert [k["url"] for k in again["kept"]] == [GONE]


def test_an_address_that_left_the_list_is_forgotten():
    told = {LOST: "", "https://docs.example.com/a/left": ""}
    state = plan_moved(week_state(moved={"week": "2026-W45", "told": told}),
                       MANIFEST, PAGES, HOSTS, locate, WEEK)
    assert state["moved"]["told"] == {LOST: "", NEAR: NEW_NEAR}


def test_the_same_week_twice_makes_nothing_and_asks_nothing():
    calls = []

    def counting(address):
        calls.append(address)
        return locate(address)

    state = plan_moved(week_state(moved={"week": WEEK, "told": {}}),
                       MANIFEST, PAGES, HOSTS, counting, WEEK)
    assert state["kept"] == [] and calls == []
    assert state["moved"] == {"week": WEEK, "told": {}}


def test_a_title_already_kept_is_not_added_again():
    title = f"{GONE} moved"
    state = plan_moved(week_state(kept=[{"title": title}]), MANIFEST, PAGES, HOSTS, locate, WEEK)
    assert [k["title"] for k in state["kept"]].count(title) == 1


def test_an_unread_manifest_makes_no_moved_items_and_leaves_the_week_open():
    before = {"week": "2026-W45", "told": {LOST: ""}}
    state = plan_moved(week_state(moved=before), None, PAGES, HOSTS, locate, WEEK)
    assert state["kept"] == [] and state["moved"] == before


def test_one_failed_locate_does_not_stop_the_check():
    def broken(address):
        if address == GONE:
            raise TimeoutError("timed out")
        return None

    state = plan_moved(week_state(), MANIFEST, PAGES, HOSTS, broken, WEEK)
    assert len(state["kept"]) == 3
    assert f"{GONE} was not found" in [k["title"] for k in state["kept"]]


def test_plan_moved_does_not_change_its_input():
    before = week_state()
    plan_moved(before, MANIFEST, PAGES, HOSTS, locate, WEEK)
    assert before == week_state()


def test_an_item_of_each_verdict_renders_in_the_summary():
    from datetime import date

    from watch_post import WHAT, render_summary

    state = plan_moved(week_state(), MANIFEST, PAGES, HOSTS, locate, WEEK)
    _, body, rest = render_summary(state["kept"], date(2026, 11, 16))
    assert rest == [] and body.count(WHAT["outdated"]) == 3
    for item in state["kept"]:
        assert item["title"] in body
    assert "Update the row in `docs/clients.md`" in body


def test_the_manifest_is_read_with_get_and_gives_its_addresses(monkeypatch):
    seen = []

    def fake_get(url, limit=None):
        seen.append((url, limit))
        return '{"documents": {"https://docs.example.com/a/b.md": {}}}', "text/plain"

    monkeypatch.setattr(watch_fetch, "get", fake_get)
    src = {"id": "m", "kind": "manifest", "url": "https://raw.example.com/m.json"}
    assert watch_fetch.read_manifest(src) == {"https://docs.example.com/a/b.md"}
    assert seen == [("https://raw.example.com/m.json", watch_fetch.MANIFEST_MAX)]
    assert watch_fetch.MANIFEST_MAX == 5 * 1024 * 1024


def test_a_manifest_of_the_wrong_shape_counts_as_unread(monkeypatch):
    monkeypatch.setattr(watch_fetch, "get", lambda url, limit=None: ("[]", "text/plain"))
    src = {"id": "m", "kind": "manifest", "url": "https://raw.example.com/m.json"}
    assert read_or_none("m", watch_fetch.read_manifest, src) is None


def test_the_config_has_the_manifest_with_no_client():
    from pathlib import Path

    from watch_pages import load_sources

    config = Path(__file__).parents[1] / "config/watch-sources.yml"
    [src] = [s for s in load_sources(config) if s["kind"] == "manifest"]
    assert src == {"id": "agent-docs-manifest", "kind": "manifest", "url": (
        "https://raw.githubusercontent.com/KonstantinStarovoytov/agent-docs/main/"
        "data/manifests/agent_docs_hybrid_v1.json")}


def test_a_manifest_over_the_cap_counts_as_unread(monkeypatch):
    def too_big(url, limit=None):
        raise ValueError(f"the body is over {limit} bytes")

    monkeypatch.setattr(watch_fetch, "get", too_big)
    src = {"id": "m", "kind": "manifest", "url": "https://raw.example.com/m.json"}
    assert read_or_none("m", watch_fetch.read_manifest, src) is None


# One time budget for the doc pages of a run (Review Focus 10)

DOCS = [f"https://docs.example.com/a/page{n}" for n in range(1, 6)]
# Made-up rows: no fact about a real client.
BUDGET_LIST = "## Codex\n\n| What | Kind | Files | Seen in | macOS and Linux | Source |\n" + \
    "|---|---|---|---|---|---|\n" + "".join(
        f"| `zork{n}` | key | `src/a.py` | scan | same | {page} |\n"
        for n, page in enumerate(DOCS, 1))
BUDGET_SOURCES = "- {id: r, client: codex, kind: github-releases, repo: o/r}\n"


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def budget_state():
    return old({"r": {"1.0": "h"}, **{page: {"Install": f"old-{page}"} for page in DOCS}},
               fails={DOCS[4]: 2})


def fetch_run(tmp_path, monkeypatch, capsys, release_seconds=0, slow_after=None, state=None,
              sources=BUDGET_SOURCES, release=None, entries=None, feed_pages=None):
    """main() on a list of five doc pages, every read a fake, with `state` as the memory
    (budget_state() when None). The release read takes `release_seconds` and gives `release`
    (one known section when None); the clock jumps past the budget during page read number
    `slow_after`, doc and feed pages counted together. The feed gives `entries`, or raises it
    when it is an exception; a feed page gives its sections in `feed_pages`. Gives the
    output, stderr, the pages read, and the meta and fetched plan_run got (and the weeks
    plan_moved was called for, under "moved")."""
    clock = Clock()
    (tmp_path / "kitden/docs").mkdir(parents=True, exist_ok=True)
    (tmp_path / "kitden/docs/clients.md").write_text(BUDGET_LIST)
    (tmp_path / "sources.yml").write_text(sources)
    (tmp_path / "titles.json").write_text("[]")
    state = budget_state() if state is None else state
    (tmp_path / "state.json").write_text(json.dumps(state))
    read = []
    feed_pages = feed_pages or {}

    def fake_read(source):
        clock.now += release_seconds
        return [Section("1.0", "t", "h")] if release is None else release

    def fake_read_doc(address, hosts):
        read.append(address)
        if len(read) == slow_after:
            clock.now += watch_fetch.PAGES_SECONDS + 1
        if address in feed_pages:
            return feed_pages[address]
        return [Section("Install", "t", f"old-{address}")]

    def fake_read_feed(source, today):
        planned["feed_day"] = today
        if isinstance(entries, Exception):
            raise entries
        return entries or []

    planned = {"moved": []}

    def spy(state, fetched, meta):
        planned.update(fetched=dict(fetched), meta=dict(meta))
        return plan_run(state, fetched, meta)

    def moved_spy(state, manifest, pages, hosts, locate, week):
        planned["moved"].append(week)
        return plan_moved(state, manifest, pages, hosts, lambda address: None, week)

    class Done:
        stdout, returncode = "v1", 0

    monkeypatch.setattr(watch_fetch, "_read", fake_read)
    monkeypatch.setattr(watch_fetch, "_read_doc", fake_read_doc)
    monkeypatch.setattr(watch_fetch, "read_feed", fake_read_feed)
    monkeypatch.setattr(watch_fetch, "read_manifest", lambda source: set())
    monkeypatch.setattr(watch_fetch, "plan_run", spy)
    monkeypatch.setattr(watch_fetch, "plan_moved", moved_spy)
    monkeypatch.setattr(watch_fetch, "_git", lambda kitden, *args: Done())
    monkeypatch.delenv("GITHUB_OUTPUT", raising=False)
    watch_fetch.main([
        "--sources", str(tmp_path / "sources.yml"), "--kitden", str(tmp_path / "kitden"),
        "--state", str(tmp_path / "state.json"), "--titles", str(tmp_path / "titles.json"),
        "--out", str(tmp_path / "out.json")], clock=clock)
    out = json.loads((tmp_path / "out.json").read_text())
    return out, capsys.readouterr().err, read, planned


def test_the_page_budget_is_seven_minutes():
    assert watch_fetch.PAGES_SECONDS == 420


def test_a_budget_is_left_until_its_seconds_have_passed():
    clock = Clock()
    budget = watch_fetch.Budget(10, clock=clock)
    assert budget.left()
    clock.now += 9.9
    assert budget.left()
    clock.now += 0.1
    assert not budget.left()
    assert not watch_fetch.Budget(0, clock=clock).left()


def test_a_budget_counts_from_when_it_is_made():
    clock = Clock()
    clock.now = 5000.0
    budget = watch_fetch.Budget(10, clock=clock)
    clock.now += 5
    assert budget.left()


def test_on_time_every_doc_page_is_read_and_nothing_is_said(tmp_path, monkeypatch, capsys):
    out, err, read, planned = fetch_run(tmp_path, monkeypatch, capsys)
    assert read == DOCS
    assert set(DOCS) <= set(planned["meta"]) and set(DOCS) <= set(planned["fetched"])
    assert err == ""


def test_pages_after_the_budget_are_not_read_and_keep_their_hashes(
        tmp_path, monkeypatch, capsys):
    out, err, read, planned = fetch_run(tmp_path, monkeypatch, capsys, slow_after=3)
    assert read == DOCS[:3]
    for page in DOCS[3:]:
        assert page not in planned["meta"] and page not in planned["fetched"]
    state = out["state"]
    # Not failed reads: no fail is counted, no "Cannot read" item, the hashes stay.
    assert state["fails"] == {"r": 0, **{page: 0 for page in DOCS[:3]}, DOCS[4]: 2}
    assert not [k for k in state["kept"] if k["title"].startswith("Cannot read")]
    assert state["sources"] == {"r": {"1.0": "h"},
                                **{page: {"Install": f"old-{page}"} for page in DOCS}}
    assert out["pieces"] == []


def test_a_read_already_started_is_not_cut_short(tmp_path, monkeypatch, capsys):
    out, err, read, planned = fetch_run(tmp_path, monkeypatch, capsys, slow_after=3)
    # The clock jumped during the third read: that read still counts.
    assert planned["fetched"][DOCS[2]] == [Section("Install", "t", f"old-{DOCS[2]}")]
    assert out["state"]["fails"][DOCS[2]] == 0


def test_one_line_says_how_many_pages_wait_for_tomorrow(tmp_path, monkeypatch, capsys):
    out, err, read, planned = fetch_run(tmp_path, monkeypatch, capsys, slow_after=3)
    [line] = err.splitlines()
    assert "420 seconds" in line and line.endswith("left for tomorrow: 2.")
    assert not [page for page in DOCS if page in err]


def test_the_budget_starts_at_the_first_doc_page(tmp_path, monkeypatch, capsys):
    seconds = 2 * watch_fetch.PAGES_SECONDS
    out, err, read, planned = fetch_run(tmp_path, monkeypatch, capsys, release_seconds=seconds)
    assert read == DOCS and err == ""


# Where the pages start, and pages left unread for lack of time


def runs(tmp_path, monkeypatch, capsys, count, slow_after):
    """`count` runs of main(), each on the memory the one before wrote."""
    state, done = None, []
    for _ in range(count):
        out, err, read, planned = fetch_run(tmp_path, monkeypatch, capsys,
                                            slow_after=slow_after, state=state)
        state = out["state"]
        done.append((read, state))
    return done


def test_a_run_starts_where_the_last_one_ran_out_of_time(tmp_path, monkeypatch, capsys):
    done = runs(tmp_path, monkeypatch, capsys, 3, slow_after=2)
    assert [read for read, _ in done] == [DOCS[0:2], DOCS[2:4], [DOCS[4], DOCS[0]]]
    assert [state["page_start"] for _, state in done] == [2, 4, 1]
    assert {page for read, _ in done for page in read} == set(DOCS)


def test_on_time_the_start_stays_and_nothing_is_skipped(tmp_path, monkeypatch, capsys):
    out, err, read, planned = fetch_run(tmp_path, monkeypatch, capsys,
                                        state={**budget_state(), "page_start": 3})
    assert read == DOCS[3:] + DOCS[:3]
    assert out["state"]["page_start"] == 3 and out["state"]["skips"] == {}


def test_the_pages_are_read_in_sorted_order_from_the_start():
    pages = {"https://d/b": "codex", "https://d/c": "cursor", "https://d/a": "codex"}
    assert watch_fetch.page_order(None, pages) == ["https://d/a", "https://d/b", "https://d/c"]
    assert watch_fetch.page_order({"page_start": 1}, pages) == [
        "https://d/b", "https://d/c", "https://d/a"]
    assert watch_fetch.page_order({"page_start": 7}, pages)[0] == "https://d/b"  # 7 % 3


@pytest.mark.parametrize("start", ["2", None, 1.5, True, [1]])
def test_a_start_that_is_not_a_whole_number_starts_at_the_first_page(start):
    pages = {"https://d/b": "codex", "https://d/a": "codex"}
    assert watch_fetch.page_order({"page_start": start}, pages)[0] == "https://d/a"


def test_no_doc_page_reads_nothing_and_starts_at_0():
    assert watch_fetch.page_order({"page_start": 4}, {}) == []
    state = watch_fetch.plan_skips(old({}, page_start=4), {}, 0)
    assert state["page_start"] == 0 and state["skips"] == {}


def out_of_time(count):
    pages = "1 doc page was" if count == 1 else f"{count} doc pages were"
    return f"{pages} not read for {FAIL_DAYS} runs: out of time"


def test_the_third_skipped_run_in_a_row_makes_one_item_for_its_pages(
        tmp_path, monkeypatch, capsys):
    # One page a run: DOCS[3] and DOCS[4] are left out of the first three runs.
    done = runs(tmp_path, monkeypatch, capsys, 4, slow_after=1)
    _, third = done[2]
    assert third["skips"] == {DOCS[3]: 3, DOCS[4]: 3, DOCS[0]: 2, DOCS[1]: 1}
    [item] = third["kept"]
    assert item["title"] == out_of_time(2)
    assert (item["effect"], item["severity"], item["sure"]) == ("unknown", "medium", True)
    assert item["client"] == "codex" and item["url"] == ""
    assert f"`{DOCS[3]}`, `{DOCS[4]}`" in item["changed"]
    assert DOCS[0] not in item["changed"]
    _, fourth = done[3]
    # DOCS[4] is on its fourth run: not said again. DOCS[0] reaches its third.
    assert [k["title"] for k in fourth["kept"]] == [out_of_time(2), out_of_time(1)]
    new = fourth["kept"][1]
    assert DOCS[0] in new["changed"] and DOCS[4] not in new["changed"]
    assert all(fourth["fails"].get(page, 0) == 0 for page in DOCS[:4])


def test_a_page_read_resets_its_skips(tmp_path, monkeypatch, capsys):
    out, *_ = fetch_run(tmp_path, monkeypatch, capsys, slow_after=3)
    assert out["state"]["skips"] == {DOCS[3]: 1, DOCS[4]: 1}
    again, *_ = fetch_run(tmp_path, monkeypatch, capsys, state=out["state"])
    assert again["state"]["skips"] == {}


def test_a_page_whose_read_was_started_is_not_skipped_even_if_the_read_failed():
    # `read` counts the reads started; plan_run counts a failed one in `fails`.
    pages = {"https://d/a": "codex", "https://d/b": "codex"}
    state = old({}, skips={"https://d/a": 2, "https://d/b": 2})
    new = watch_fetch.plan_skips(state, pages, 1)
    assert new["skips"] == {"https://d/b": 3}
    [item] = new["kept"]
    assert item["title"] == out_of_time(1) and "https://d/a" not in item["changed"]
    assert new["page_start"] == 1


def test_a_page_past_its_third_run_adds_nothing():
    pages = {"https://d/a": "codex"}
    new = watch_fetch.plan_skips(old({}, skips={"https://d/a": 3}), pages, 0)
    assert new["kept"] == [] and new["skips"] == {"https://d/a": 4}


def test_many_pages_on_their_third_run_make_one_short_item():
    pages = {f"https://docs.example.com/a/{'x' * 40}{n:02d}": "codex" for n in range(19)}
    state = old({}, skips=dict.fromkeys(pages, 2))
    [item] = watch_fetch.plan_skips(state, pages, 0)["kept"]
    assert item["title"] == out_of_time(19) and len(item["title"]) <= 80
    assert all(f"`{page}`" in item["changed"] for page in pages)


def test_pages_of_several_clients_make_an_item_of_no_one_client():
    pages = {"https://d/a": "codex", "https://d/b": "cursor"}
    state = old({}, skips=dict.fromkeys(pages, 2))
    [item] = watch_fetch.plan_skips(state, pages, 0)["kept"]
    assert item["client"] == "" and item["title"] == out_of_time(2)


def test_the_grouped_item_renders_in_the_summary():
    from datetime import date

    from watch_post import render_summary

    pages = {"https://d/a": "codex", "https://d/b": "cursor"}
    state = old({}, skips=dict.fromkeys(pages, 2))
    kept = watch_fetch.plan_skips(state, pages, 0)["kept"]
    _, body, rest = render_summary(kept, date(2026, 11, 16))
    assert rest == [] and out_of_time(2) in body and "`https://d/b`" in body


def test_a_page_that_left_the_list_is_forgotten_from_skips():
    new = watch_fetch.plan_skips(old({}, skips={"https://d/gone": 2}),
                                 {"https://d/a": "codex"}, 1)
    assert new["skips"] == {}


def test_plan_skips_does_not_change_its_input():
    before = old({}, skips={"https://d/a": 2})
    watch_fetch.plan_skips(before, {"https://d/a": "codex"}, 0)
    assert before == old({}, skips={"https://d/a": 2})


def test_the_skip_item_is_built_only_when_a_page_reaches_its_third_run(monkeypatch):
    built = []
    real = watch_fetch._out_of_time

    def counting(addresses, pages):
        built.append(list(addresses))
        return real(addresses, pages)

    monkeypatch.setattr(watch_fetch, "_out_of_time", counting)
    pages = {"https://d/a": "codex", "https://d/b": "codex", "https://d/c": "codex"}
    watch_fetch.plan_skips(old({}, skips={"https://d/c": 3}), pages, 0)
    assert built == []
    new = watch_fetch.plan_skips(old({}, skips={"https://d/b": 2, "https://d/c": 3}), pages, 0)
    assert built == [["https://d/b"]]
    assert [k["title"] for k in new["kept"]] == [out_of_time(1)]


# Feed pieces: a cap, a queue and the page budget (Task 6.5, Review Focus 2 and 10)

FEED_ID = "agent-docs-feed"
FEED_HOSTS = load_hosts()
FEED_TODAY = date(2026, 11, 16)
DAY = "2026-11-15"
LAST = "2026-11-14"
CC = "https://code.claude.com/docs/en/"
CX = "https://learn.chatgpt.com/docs/"
CU = "https://cursor.com/docs/"
PRODUCT = {CC: "claude-code", CX: "codex", CU: "cursor"}
# Made-up list words: no fact about a real client.
FEED_WORDS = {"claude-code": ["zorkSetting"], "codex": [], "cursor": []}


def md(*parts):
    """A made-up markdown page cut as fetch cuts it; each part is (heading, text)."""
    return sections("".join(f"## {h}\n{t}\n" for h, t in parts), "text/markdown")


HOOK_PAGE = md(("Hooks", "A planted hook runs here."))


def at(n, base=CC):
    return f"{base}planted-{n}"


def fentry(n, day=DAY, kind="added", headings=(), base=CC):
    return Entry(day, kind, at(n, base) + ".md", PRODUCT[base], tuple(headings))


def stored(e):
    return {**e._asdict(), "sections": list(e.sections)}


def feed_state(**feed):
    _, state = plan_run(None, {}, {})
    return {**state, "feed": {"day": LAST, "wait": [], "dropped": 0, "held": 0, **feed}}


class Pages:
    """read_page: the page of `pages`, or HOOK_PAGE; raises for an address in `fail`."""

    def __init__(self, pages=None, fail=()):
        self.pages, self.fail, self.read = pages or {}, set(fail), []

    def __call__(self, address):
        self.read.append(address)
        if address in self.fail:
            raise TimeoutError(f"made-up detail {address}")
        return self.pages.get(address, HOOK_PAGE)


def feed_plan(state, entries, reader=None, room=PIECES_MAX, in_time=lambda: True, listed=(),
              today=FEED_TODAY):
    reader = reader or Pages()
    pieces, new = plan_feed(state, entries, set(listed), FEED_HOSTS, reader, FEED_WORDS, today,
                            room, in_time)
    return pieces, new, reader


def judged(state, pieces):
    """The memory after route marked `pieces` judged: sources[<source>][<key>] = hash."""
    new = copy.deepcopy(state)
    for p in pieces:
        new["sources"].setdefault(p["source"], {})[p["key"]] = p["hash"]
    return new


def waiting(state):
    return [w["url"] for w in state["feed"]["wait"]]


def test_feed_constants():
    assert (FEED_PIECES_MAX, FEED_PAGES_MAX) == (5, 10)
    assert WAIT_MAX == FEED_PAGES_MAX * KEEP_DAYS


def test_plan_run_counts_a_failed_feed_read_and_says_so_on_the_third_day():
    meta = {**META, FEED_ID: {"kind": "feed", "url": "https://raw.example.com/feed.json"}}
    _, state = plan_run(old({"s": {}}, fails={FEED_ID: 2}), {"s": [], FEED_ID: None}, meta)
    assert state["fails"][FEED_ID] == FAIL_DAYS and FEED_ID not in state["sources"]
    [item] = state["kept"]
    assert item["title"] == f"Cannot read {FEED_ID} for 3 days" and item["client"] == ""
    assert item["url"] == "https://raw.example.com/feed.json"


def test_plan_run_never_hash_compares_the_feed_and_makes_no_piece_of_it():
    meta = {**META, FEED_ID: {"kind": "feed", "url": "https://raw.example.com/feed.json"}}
    recorded = {"https://code.claude.com/docs/en/a@2026-11-15": "h"}
    state = old({"s": {"1.0": "h"}, FEED_ID: recorded}, fails={FEED_ID: 2})
    pieces, new = plan_run(state, {"s": [Section("1.0", "t", "h")], FEED_ID: [fentry(1)]}, meta)
    assert pieces == [] and new["sources"][FEED_ID] == recorded
    assert new["fails"][FEED_ID] == 0


def test_an_unread_feed_leaves_the_memory_as_it_was_and_reads_no_page():
    state = feed_state(wait=[stored(fentry(1))])
    state["sources"][FEED_ID] = {f"{at(1)}@{DAY}": "h"}
    pieces, new, reader = feed_plan(state, None)
    assert pieces == [] and new == state and reader.read == []


def test_with_no_feed_in_the_memory_the_newest_day_is_taken_and_nothing_is_read():
    _, state = plan_run(None, {}, {})
    pieces, new, reader = feed_plan(state, [fentry(1, day="2026-11-13"), fentry(2)])
    assert pieces == [] and reader.read == []
    assert new["feed"] == {"day": DAY, "wait": [], "dropped": 0, "held": 0,
                           "taken": [page_key(at(2))]}


def test_with_no_feed_in_the_memory_and_an_empty_feed_every_later_day_is_new():
    _, state = plan_run(None, {}, {})
    _, new, _ = feed_plan(state, [])
    assert new["feed"]["day"] == "" and new["feed"]["taken"] == []
    pieces, _, _ = feed_plan(new, [fentry(1)])
    assert [p["url"] for p in pieces] == [at(1)]


@pytest.mark.parametrize("feed", ["x", [], {"wait": []}, {"day": 7}, {"day": "soon"}])
def test_a_feed_memory_of_another_shape_starts_again(feed):
    state = {**feed_state(), "feed": feed}
    pieces, new, reader = feed_plan(state, [fentry(1)])
    assert pieces == [] and reader.read == []
    assert new["feed"] == {"day": DAY, "wait": [], "dropped": 0, "held": 0,
                           "taken": [page_key(at(1))]}


def test_eight_pages_make_five_pieces_and_three_wait_and_come_first_the_next_day():
    eight = [fentry(n) for n in range(8)]
    pieces, state, reader = feed_plan(feed_state(), eight)
    assert len(pieces) == FEED_PIECES_MAX
    assert [p["url"] for p in pieces] == [at(n) for n in range(5)] == reader.read
    # A page made into a piece waits too, until route marks it judged.
    assert waiting(state) == [e.url for e in eight]
    assert state["feed"]["day"] == DAY
    tomorrow = [fentry(n, day="2026-11-16") for n in (8, 9, 10)]
    pieces, state, _ = feed_plan(judged(state, pieces), tomorrow, today=date(2026, 11, 17))
    assert [p["url"] for p in pieces] == [at(n) for n in (5, 6, 7, 8, 9)]
    assert state["feed"]["day"] == "2026-11-16" and FEED_ID not in state["sources"]
    assert waiting(state) == [fentry(n, day="2026-11-16").url for n in (5, 6, 7, 8, 9, 10)]


def test_a_piece_not_judged_is_offered_again_first():
    pieces, state, _ = feed_plan(feed_state(), [fentry(n) for n in range(8)])
    again, _, _ = feed_plan(state, [])
    assert [p["id"] for p in again] == [p["id"] for p in pieces]


def test_only_the_room_left_is_used_and_with_no_room_no_page_is_read():
    eight = [fentry(n) for n in range(8)]
    two, _, reader = feed_plan(feed_state(), eight, room=2)
    assert len(two) == 2 and len(reader.read) == 2
    none, state, reader = feed_plan(feed_state(), eight, room=0)
    assert none == [] and reader.read == []
    assert waiting(state) == [e.url for e in eight]


def test_an_entry_more_than_keep_days_old_is_dropped_and_counted():
    too_old = fentry(1, day=(FEED_TODAY - timedelta(days=KEEP_DAYS + 1)).isoformat())
    oldest = fentry(2, day=(FEED_TODAY - timedelta(days=KEEP_DAYS)).isoformat())
    state = feed_state(wait=[stored(too_old), stored(oldest)], dropped=3)
    pieces, new, reader = feed_plan(state, [])
    assert reader.read == [at(2)] and [p["url"] for p in pieces] == [at(2)]
    assert new["feed"]["dropped"] == 4 and waiting(new) == [oldest.url]


def test_a_page_whose_read_fails_waits_and_is_not_a_failed_read(capsys):
    reader = Pages(fail={at(1)})
    pieces, state, _ = feed_plan(feed_state(), [fentry(1), fentry(2)], reader=reader)
    assert [p["url"] for p in pieces] == [at(2)]
    assert waiting(state) == [fentry(1).url, fentry(2).url]
    assert state["fails"] == {} and state["kept"] == []
    err = capsys.readouterr().err
    assert "TimeoutError" in err and "planted" not in err and "made-up" not in err


def test_a_page_with_no_kept_section_makes_no_piece_and_leaves_the_queue():
    reader = Pages({at(1): md(("Pricing", "It costs money."))})
    pieces, state, _ = feed_plan(feed_state(), [fentry(1), fentry(2)], reader=reader)
    assert [p["url"] for p in pieces] == [at(2)] and waiting(state) == [fentry(2).url]


def test_after_feed_pages_max_reads_the_rest_wait_and_are_not_failed_reads():
    twelve = [fentry(n) for n in range(12)]
    reader = Pages({at(n): md(("Pricing", "None.")) for n in range(12)})
    pieces, state, _ = feed_plan(feed_state(), twelve, reader=reader)
    assert pieces == [] and reader.read == [at(n) for n in range(FEED_PAGES_MAX)]
    assert waiting(state) == [e.url for e in twelve[FEED_PAGES_MAX:]]
    assert state["fails"] == {}


def test_a_failed_read_counts_toward_feed_pages_max():
    twelve = [fentry(n) for n in range(12)]
    reader = Pages(fail={at(n) for n in range(12)})
    _, state, _ = feed_plan(feed_state(), twelve, reader=reader)
    assert len(reader.read) == FEED_PAGES_MAX and waiting(state) == [e.url for e in twelve]


def test_once_the_budget_is_spent_no_page_is_read_and_the_rest_wait():
    reader = Pages()
    five = [fentry(n) for n in range(5)]
    pieces, state, _ = feed_plan(feed_state(), five, reader=reader,
                                 in_time=lambda: len(reader.read) < 2)
    assert reader.read == [at(0), at(1)] and len(pieces) == 2
    assert waiting(state) == [e.url for e in five] and state["fails"] == {}


def test_a_page_found_on_two_days_is_read_once():
    reader = Pages()
    both = [fentry(1, day=LAST), fentry(1)]
    pieces, _, _ = feed_plan(feed_state(day="2026-11-13"), both, reader=reader)
    assert reader.read == [at(1)]
    assert [p["key"] for p in pieces] == [f"{at(1)}@{LAST}", f"{at(1)}@{DAY}"]


def test_an_added_page_offers_every_section_and_a_changed_page_only_its_new_ones():
    page = md(("Hooks", "A hook."), ("Plugins", "A plugin."))
    reader = Pages({at(1): page, at(2): page})
    entries = [fentry(1), fentry(2, kind="changed", headings=["Plugins"])]
    added, changed = feed_plan(feed_state(), entries, reader=reader)[0]
    assert added["text"] == "## Hooks\nA hook.\n\n## Plugins\nA plugin."
    assert changed["text"] == "## Plugins\nA plugin."


def test_a_changed_page_whose_new_section_holds_no_word_makes_no_piece():
    reader = Pages({at(1): md(("Hooks", "A hook."), ("Pricing", "None."))})
    entry = fentry(1, kind="changed", headings=["Pricing"])
    pieces, state, _ = feed_plan(feed_state(), [entry], reader=reader)
    assert pieces == [] and waiting(state) == []


def test_the_text_is_the_kept_sections_in_page_order_cut_to_piece_chars():
    page = md(("Skills", "A skill."), ("Pricing", "None."), ("Hooks", "A hook."))
    [piece], _, _ = feed_plan(feed_state(), [fentry(1)], reader=Pages({at(1): page}))
    assert piece["text"] == "## Skills\nA skill.\n\n## Hooks\nA hook."
    long = md(("Hooks", "a hook " * PIECE_CHARS))
    [piece], _, _ = feed_plan(feed_state(), [fentry(1)], reader=Pages({at(1): long}))
    assert len(piece["text"]) == PIECE_CHARS
    assert piece["hash"] == hashlib.sha256(piece["text"].encode()).hexdigest()


def test_a_feed_piece_has_the_shape_of_a_doc_piece():
    entry = fentry(1, base=CX)
    [piece], _, reader = feed_plan(feed_state(), [entry])
    page = at(1, CX)
    key = f"{page}@{DAY}"
    assert reader.read == [page]  # page_of: no .md, read through read_page (get_doc)
    assert piece == {"id": f"{FEED_ID}#{key}", "kind": "doc", "client": "codex",
                     "version": "", "url": page, "text": HOOK_PAGE[0].text,
                     "source": FEED_ID, "key": key, "hash": piece["hash"]}


def test_the_page_read_is_page_of_the_entry_address():
    entry = Entry(DAY, "added", at(1) + ".md#part", "claude-code", ())
    [piece], _, reader = feed_plan(feed_state(), [entry])
    assert reader.read == [at(1)] and piece["url"] == at(1)


def test_a_list_word_of_the_page_client_keeps_a_section():
    page = md(("New", "Set zorkSetting to true."))
    reader = Pages({at(1): page, at(1, CX): page})
    pieces, _, _ = feed_plan(feed_state(), [fentry(1), fentry(1, base=CX)], reader=reader)
    assert [p["client"] for p in pieces] == ["claude-code"]


def test_no_page_the_feed_should_not_send_is_read():
    # Review Focus 1: a listed page, another host, a query, a page outside the allowed path.
    bad = [Entry(DAY, "added", url, "claude-code", ()) for url in (
        at(1) + ".md", "https://evil.example/docs/en/x.md", at(2) + ".md?x=1",
        "https://code.claude.com/blog/x.md", "http://code.claude.com/docs/en/x.md")]
    state = feed_state(wait=[stored(e) for e in bad])
    pieces, new, reader = feed_plan(state, bad, listed={at(1)})
    assert pieces == [] and reader.read == [] and waiting(new) == []


def test_a_cursor_entry_is_not_read_makes_no_piece_and_is_counted_as_held(capsys):
    entries = [fentry(1, base=CU), fentry(2), fentry(3, base=CU)]
    pieces, state, reader = feed_plan(feed_state(held=4), entries)
    assert reader.read == [at(2)] and [p["url"] for p in pieces] == [at(2)]
    assert waiting(state) == [fentry(2).url] and state["feed"]["held"] == 6
    assert "2 held back (no text for cursor)" in capsys.readouterr().err


def test_a_cursor_entry_is_held_back_even_with_no_room():
    _, state, _ = feed_plan(feed_state(), [fentry(1, base=CU)], room=0)
    assert waiting(state) == [] and state["feed"]["held"] == 1


def test_a_waiting_page_that_joined_the_list_leaves_the_queue_unread():
    state = feed_state(wait=[stored(fentry(1)), stored(fentry(2))])
    pieces, new, reader = feed_plan(state, [], listed={at(1)})
    assert reader.read == [at(2)] and waiting(new) == [fentry(2).url]


def test_a_waiting_entry_of_another_shape_is_skipped():
    bad = [{"day": DAY}, "x", {**stored(fentry(1)), "sections": "Hooks"},
           {**stored(fentry(2)), "day": "soon"}, {**stored(fentry(3)), "kind": "removed"}]
    state = feed_state(wait=[*bad, stored(fentry(4))])
    pieces, new, _ = feed_plan(state, [])
    assert [p["url"] for p in pieces] == [at(4)] and waiting(new) == [fentry(4).url]


def test_the_queue_is_cut_at_wait_max_and_the_rest_counted_as_dropped():
    many = [fentry(n) for n in range(WAIT_MAX + 10)]
    _, state, _ = feed_plan(feed_state(), many, room=0)
    assert waiting(state) == [e.url for e in many[:WAIT_MAX]]
    assert state["feed"]["dropped"] == 10


def test_a_waiting_entry_keeps_the_writer_caps_on_its_headings():
    headings = [f"{n:02d}" + "x" * 300 for n in range(80)]
    _, state, _ = feed_plan(feed_state(), [fentry(1, kind="changed", headings=headings)],
                            room=0)
    [entry] = state["feed"]["wait"]
    assert entry["sections"] == [h[:HEADING_CHARS] for h in headings[:HEADINGS_MAX]]
    assert (HEADINGS_MAX, HEADING_CHARS) == (50, 200)


def test_the_memory_keeps_entries_as_json():
    _, state, _ = feed_plan(feed_state(), [fentry(1, kind="changed", headings=["Hooks"])],
                            room=0)
    assert json.loads(json.dumps(state))["feed"]["wait"] == [
        {"day": DAY, "kind": "changed", "url": fentry(1).url, "product": "claude-code",
         "sections": ["Hooks"]}]


def test_one_line_of_counts_says_what_the_feed_did(capsys):
    too_old = stored(fentry(9, day="2026-10-01"))
    reader = Pages(fail={at(1)})
    feed_plan(feed_state(wait=[too_old]), [fentry(n) for n in range(8)] + [fentry(1, base=CU)],
              reader=reader)
    [line] = capsys.readouterr().err.splitlines()[-1:]
    assert line == ("feed: 5 pieces, 8 waiting, 6 pages read, 1 failed, 1 dropped, "
                    "1 held back (no text for cursor)")


def test_plan_feed_does_not_change_its_input():
    state = feed_state(wait=[stored(fentry(1))])
    state["sources"][FEED_ID] = {f"{at(1)}@{DAY}": "h"}
    before = copy.deepcopy(state)
    feed_plan(state, [fentry(2)])
    assert state == before


def test_list_words_gives_each_client_its_words_once():
    text = ("## Claude Code\n\n| What | Kind | Files | Seen in | Systems | Source |\n"
            "|---|---|---|---|---|---|\n"
            "| `zorkSetting` key | key | `a.py` | 1 | all | install |\n"
            "| `zorkSetting` and `zork-flag` | key | `a.py` | 1 | all | install |\n"
            "## Codex\n\n| What | Kind | Files | Seen in | Systems | Source |\n"
            "|---|---|---|---|---|---|\n"
            "| `zork_codex` | key | `a.py` | 1 | all | install |\n")
    assert watch_fetch.list_words(text) == {"claude-code": ["zorkSetting", "zork-flag"],
                                            "codex": ["zork_codex"]}


# The feed in main()

FEED_URL = "https://raw.example.com/feed.json"
FEED_SOURCES = BUDGET_SOURCES + f"- {{id: {FEED_ID}, kind: feed, url: {FEED_URL}}}\n"
MANIFEST_SOURCES = BUDGET_SOURCES + "- {id: m, kind: manifest, url: https://raw.example.com/m.json}\n"


def days_ago(n):
    return (date.today() - timedelta(days=n)).isoformat()


def main_state(**feed):
    """budget_state() with a feed memory that took the day before yesterday."""
    return {**budget_state(),
            "feed": {"day": days_ago(2), "wait": [], "dropped": 0, "held": 0, **feed}}


def new_releases(n):
    return [Section(f"2.{i}", "t", f"h{i}") for i in range(n)] + [Section("1.0", "t", "h")]


def eight_today():
    return [fentry(n, day=days_ago(1)) for n in range(8)]


HOOK_PAGES = {at(n): HOOK_PAGE for n in range(8)}


def test_main_reads_the_feed_as_a_source_of_kind_feed(tmp_path, monkeypatch, capsys):
    out, err, read, planned = fetch_run(tmp_path, monkeypatch, capsys, sources=FEED_SOURCES,
                                        state=main_state(), entries=eight_today())
    assert planned["meta"][FEED_ID] == {"kind": "feed", "url": FEED_URL}
    assert planned["fetched"][FEED_ID] == eight_today()
    assert planned["feed_day"] == date.today()
    assert out["state"]["fails"][FEED_ID] == 0 and FEED_ID not in out["state"]["sources"]


def test_feed_pieces_come_after_the_releases_and_use_the_room_left(
        tmp_path, monkeypatch, capsys):
    out, err, read, planned = fetch_run(tmp_path, monkeypatch, capsys, sources=FEED_SOURCES,
                                        state=main_state(), release=new_releases(17),
                                        entries=eight_today(), feed_pages=HOOK_PAGES)
    kinds = [p["source"] for p in out["pieces"]]
    assert kinds == ["r"] * 17 + [FEED_ID] * 3
    assert read == DOCS + [at(n) for n in range(3)]
    assert [w["url"] for w in out["state"]["feed"]["wait"]] == [e.url for e in eight_today()]


def test_with_twenty_release_pieces_no_feed_page_is_read_and_the_old_one_is_dropped(
        tmp_path, monkeypatch, capsys):
    # Review Focus 2: no feed piece pushes out a release or a list page.
    state = main_state(wait=[stored(fentry(9, day=days_ago(KEEP_DAYS + 1)))])
    state["sources"][DOCS[0]] = {"Install": "older"}
    out, err, read, planned = fetch_run(tmp_path, monkeypatch, capsys, sources=FEED_SOURCES,
                                        state=state, release=new_releases(19),
                                        entries=eight_today(), feed_pages=HOOK_PAGES)
    assert [p["source"] for p in out["pieces"]] == ["r"] * 19 + [DOCS[0]]
    assert read == DOCS
    feed = out["state"]["feed"]
    assert [w["url"] for w in feed["wait"]] == [e.url for e in eight_today()]
    assert feed["dropped"] == 1 and feed["day"] == days_ago(1)


def test_feed_pages_are_not_read_once_the_page_budget_is_spent(tmp_path, monkeypatch, capsys):
    # Review Focus 10: the list's pages and the feed's share one budget.
    out, err, read, planned = fetch_run(tmp_path, monkeypatch, capsys, sources=FEED_SOURCES,
                                        state=main_state(), entries=eight_today(),
                                        slow_after=3, feed_pages=HOOK_PAGES)
    assert read == DOCS[:3] and out["pieces"] == []
    state = out["state"]
    assert [w["url"] for w in state["feed"]["wait"]] == [e.url for e in eight_today()]
    assert not [sid for sid in state["fails"] if "planted" in sid]
    assert not [k for k in state["kept"] if k["title"].startswith("Cannot read")]


def test_the_feed_stops_reading_when_the_budget_runs_out_in_its_pages(
        tmp_path, monkeypatch, capsys):
    out, err, read, planned = fetch_run(tmp_path, monkeypatch, capsys, sources=FEED_SOURCES,
                                        state=main_state(), entries=eight_today(),
                                        slow_after=len(DOCS) + 2, feed_pages=HOOK_PAGES)
    assert read == DOCS + [at(0), at(1)]
    assert [p["url"] for p in out["pieces"]] == [at(0), at(1)]


def test_an_unreadable_feed_is_a_failed_read_and_the_rest_is_judged(
        tmp_path, monkeypatch, capsys):
    state = main_state(wait=[stored(fentry(1, day=days_ago(1)))])
    state["fails"][FEED_ID] = 2
    out, err, read, planned = fetch_run(tmp_path, monkeypatch, capsys, sources=FEED_SOURCES,
                                        state=state, release=new_releases(2),
                                        entries=TimeoutError("made-up detail"))
    assert [p["source"] for p in out["pieces"]] == ["r", "r"] and read == DOCS
    assert out["state"]["fails"][FEED_ID] == FAIL_DAYS
    assert [k["title"] for k in out["state"]["kept"]] == [f"Cannot read {FEED_ID} for 3 days"]
    assert out["state"]["feed"] == state["feed"]
    assert f"cannot read {FEED_ID}: TimeoutError" in err and "made-up" not in err


def test_a_run_with_no_feed_source_leaves_the_feed_memory_alone(tmp_path, monkeypatch, capsys):
    state = main_state(wait=[stored(fentry(1, day=days_ago(1)))])
    out, err, read, planned = fetch_run(tmp_path, monkeypatch, capsys, state=state)
    assert out["state"]["feed"] == state["feed"] and read == DOCS and err == ""


def test_two_feed_sources_are_refused(tmp_path, monkeypatch, capsys):
    twice = FEED_SOURCES + f"- {{id: other-feed, kind: feed, url: {FEED_URL}}}\n"
    with pytest.raises(ValueError, match="one feed source"):
        fetch_run(tmp_path, monkeypatch, capsys, sources=twice, state=main_state())


def test_the_moved_check_waits_while_the_page_budget_is_spent(tmp_path, monkeypatch, capsys):
    # Carried from Task 6.3's final review.
    out, err, read, planned = fetch_run(tmp_path, monkeypatch, capsys,
                                        sources=MANIFEST_SOURCES, slow_after=3)
    assert planned["moved"] == [] and "moved" not in out["state"]
    assert "the weekly check for moved pages waits for the next run" in err
    again, err, read, planned = fetch_run(tmp_path, monkeypatch, capsys,
                                          sources=MANIFEST_SOURCES, state=out["state"])
    week = watch_fetch.week_of(date.today())
    assert planned["moved"] == [week] and again["state"]["moved"]["week"] == week
    assert "moved pages" not in err


def test_with_time_left_the_moved_check_runs_and_says_nothing(tmp_path, monkeypatch, capsys):
    out, err, read, planned = fetch_run(tmp_path, monkeypatch, capsys, sources=MANIFEST_SOURCES)
    assert planned["moved"] == [watch_fetch.week_of(date.today())] and err == ""


def test_a_spent_budget_says_nothing_of_a_moved_check_already_done_this_week(
        tmp_path, monkeypatch, capsys):
    week = watch_fetch.week_of(date.today())
    state = {**budget_state(), "moved": {"week": week, "told": {}}}
    out, err, read, planned = fetch_run(tmp_path, monkeypatch, capsys, state=state,
                                        sources=MANIFEST_SOURCES, slow_after=3)
    assert planned["moved"] == [] and "moved pages" not in err


def test_the_config_has_the_feed_after_the_manifest_with_no_client():
    from pathlib import Path

    from watch_pages import load_sources

    config = load_sources(Path(__file__).parents[1] / "config/watch-sources.yml")
    ids = [s["id"] for s in config]
    assert ids.index(FEED_ID) == ids.index("agent-docs-manifest") + 1
    [src] = [s for s in config if s["kind"] == "feed"]
    assert src == {"id": FEED_ID, "kind": "feed", "url": (
        "https://raw.githubusercontent.com/KonstantinStarovoytov/agent-docs/main/"
        "reports/docs-changes/feed.json")}


# A day of the feed written twice: `taken` (Task 6.5, ruling follow-up)


def keys(*ns, base=CC):
    return [page_key(at(n, base)) for n in ns]


def test_a_run_between_two_reindex_runs_of_one_day_takes_only_the_second_runs_new_entries():
    first = [fentry(1), fentry(2)]
    pieces, state, reader = feed_plan(feed_state(), first)
    assert reader.read == [at(1), at(2)] and state["feed"]["taken"] == keys(1, 2)
    # Agent Docs merges its second run of the day into that day: 3 is new, 1 and 2 are not.
    merged = [fentry(1), fentry(2), fentry(3)]
    pieces, state, reader = feed_plan(judged(state, pieces), merged)
    assert reader.read == [at(3)] and [p["url"] for p in pieces] == [at(3)]
    assert state["feed"]["day"] == DAY and state["feed"]["taken"] == keys(1, 2, 3)
    pieces, state, reader = feed_plan(judged(state, pieces), merged)
    assert pieces == [] and reader.read == [] and state["feed"]["wait"] == []
    # Every entry of the day has left the queue; the keys stay taken all the same.
    assert state["feed"]["taken"] == keys(1, 2, 3)
    _, _, reader = feed_plan(state, merged)
    assert reader.read == []


def test_a_memory_without_taken_takes_nothing_more_of_its_day():
    state = feed_state(day=DAY)
    pieces, new, reader = feed_plan(state, [fentry(1), fentry(2)])
    assert pieces == [] and reader.read == [] and "taken" not in new["feed"]
    pieces, new, reader = feed_plan(new, [fentry(1), fentry(3, day="2026-11-16")])
    assert reader.read == [at(3)] and new["feed"]["taken"] == keys(3)


@pytest.mark.parametrize("taken", ["x", None, [1], {"a": 1}])
def test_taken_of_another_shape_is_read_as_missing(taken):
    state = feed_state(day=DAY, taken=taken)
    pieces, new, reader = feed_plan(state, [fentry(1)])
    assert pieces == [] and reader.read == [] and "taken" not in new["feed"]


def test_when_the_day_moves_taken_holds_only_the_new_days_keys():
    state = feed_state(day=LAST, taken=keys(7, 8))
    _, new, _ = feed_plan(state, [fentry(1, day=LAST), fentry(2), fentry(3)])
    assert new["feed"]["day"] == DAY and new["feed"]["taken"] == keys(2, 3)


def test_the_first_run_marks_the_newest_days_pages_taken():
    _, state = plan_run(None, {}, {})
    # A changed page with no new section is not wanted, so it is not taken.
    _, new, reader = feed_plan(state, [fentry(1, day=LAST), fentry(2), fentry(4, kind="changed")])
    assert reader.read == [] and new["feed"]["taken"] == keys(2)
    later = [fentry(1, day=LAST), fentry(2), fentry(3),
             fentry(4, kind="changed", headings=["Hooks"])]
    pieces, _, reader = feed_plan(new, later)
    assert reader.read == [at(3), at(4)]


def test_a_held_entry_is_taken_and_not_counted_again():
    entries = [fentry(1, base=CU)]
    _, state, _ = feed_plan(feed_state(), entries)
    assert state["feed"]["held"] == 1 and state["feed"]["taken"] == keys(1, base=CU)
    _, state, _ = feed_plan(state, entries)
    assert state["feed"]["held"] == 1


def test_a_changed_page_that_gains_new_sections_later_that_day_is_taken_then():
    bare = fentry(1, kind="changed")
    pieces, state, reader = feed_plan(feed_state(), [bare, fentry(2)])
    assert reader.read == [at(2)] and state["feed"]["taken"] == keys(2)
    merged = [fentry(1, kind="changed", headings=["Hooks"]), fentry(2)]
    pieces, _, reader = feed_plan(judged(state, pieces), merged)
    assert reader.read == [at(1)] and [p["url"] for p in pieces] == [at(1)]


def test_a_page_key_matches_any_spelling_of_the_page():
    state = feed_state(day=DAY, taken=keys(1))
    spelled = Entry(DAY, "added", at(1).replace("code.claude.com", "CODE.claude.com") + "/",
                    "claude-code", ())
    _, _, reader = feed_plan(state, [spelled])
    assert reader.read == []


def test_taken_is_cut_at_taken_max():
    many = [fentry(n) for n in range(TAKEN_MAX + 10)]
    _, state, _ = feed_plan(feed_state(), many, room=0)
    assert state["feed"]["taken"] == keys(*range(TAKEN_MAX))
