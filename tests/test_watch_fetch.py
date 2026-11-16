import json

import pytest

import watch_fetch
from watch_fetch import (
    DOC_FORMAT,
    FAIL_DAYS,
    PIECE_CHARS,
    PIECES_MAX,
    _moved_item,
    build_input,
    plan_moved,
    plan_run,
    read_or_none,
)
from watch_pages import Section

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


def fetch_run(tmp_path, monkeypatch, capsys, release_seconds=0, slow_after=None, state=None):
    """main() on a list of five doc pages, every read a fake, with `state` as the memory
    (budget_state() when None). The release read takes `release_seconds`; the clock jumps
    past the budget during doc read number `slow_after`. Gives the output, stderr, the pages
    read, and the meta and fetched plan_run got."""
    clock = Clock()
    (tmp_path / "kitden/docs").mkdir(parents=True, exist_ok=True)
    (tmp_path / "kitden/docs/clients.md").write_text(BUDGET_LIST)
    (tmp_path / "sources.yml").write_text(BUDGET_SOURCES)
    (tmp_path / "titles.json").write_text("[]")
    state = budget_state() if state is None else state
    (tmp_path / "state.json").write_text(json.dumps(state))
    read = []

    def fake_read(source):
        clock.now += release_seconds
        return [Section("1.0", "t", "h")]

    def fake_read_doc(address, hosts):
        read.append(address)
        if len(read) == slow_after:
            clock.now += watch_fetch.PAGES_SECONDS + 1
        return [Section("Install", "t", f"old-{address}")]

    planned = {}

    def spy(state, fetched, meta):
        planned.update(fetched=dict(fetched), meta=dict(meta))
        return plan_run(state, fetched, meta)

    class Done:
        stdout, returncode = "v1", 0

    monkeypatch.setattr(watch_fetch, "_read", fake_read)
    monkeypatch.setattr(watch_fetch, "_read_doc", fake_read_doc)
    monkeypatch.setattr(watch_fetch, "plan_run", spy)
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


def out_of_time(page):
    return f"{page} was not read for {FAIL_DAYS} days: out of time"


def test_the_third_skipped_day_in_a_row_is_kept_once(tmp_path, monkeypatch, capsys):
    # One page a run: DOCS[3] and DOCS[4] are left out of the first three runs.
    done = runs(tmp_path, monkeypatch, capsys, 4, slow_after=1)
    _, third = done[2]
    assert third["skips"] == {DOCS[3]: 3, DOCS[4]: 3, DOCS[0]: 2, DOCS[1]: 1}
    titles = [k["title"] for k in third["kept"]]
    assert titles == [out_of_time(DOCS[3]), out_of_time(DOCS[4])]
    item = third["kept"][0]
    assert (item["effect"], item["severity"], item["sure"]) == ("unknown", "medium", True)
    assert item["client"] == "codex" and item["url"] == DOCS[3]
    _, fourth = done[3]
    # DOCS[4] is on its fourth day: not said again. DOCS[0] reaches its third.
    titles = [k["title"] for k in fourth["kept"]]
    assert titles == [out_of_time(DOCS[3]), out_of_time(DOCS[4]), out_of_time(DOCS[0])]
    assert not [t for t in titles if t.startswith("Cannot read")]
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
    assert [k["title"] for k in new["kept"]] == [out_of_time("https://d/b")]
    assert new["page_start"] == 1


def test_an_out_of_time_title_already_kept_is_not_added_again():
    pages = {"https://d/a": "codex"}
    kept = [{"title": out_of_time("https://d/a")}]
    new = watch_fetch.plan_skips(old({}, skips={"https://d/a": 2}, kept=kept), pages, 0)
    assert new["kept"] == kept and new["skips"] == {"https://d/a": 3}


def test_a_page_that_left_the_list_is_forgotten_from_skips():
    new = watch_fetch.plan_skips(old({}, skips={"https://d/gone": 2}),
                                 {"https://d/a": "codex"}, 1)
    assert new["skips"] == {}


def test_plan_skips_does_not_change_its_input():
    before = old({}, skips={"https://d/a": 2})
    watch_fetch.plan_skips(before, {"https://d/a": "codex"}, 0)
    assert before == old({}, skips={"https://d/a": 2})
