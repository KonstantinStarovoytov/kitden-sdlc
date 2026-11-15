import json

import watch_fetch
from watch_fetch import (
    DOC_FORMAT,
    FAIL_DAYS,
    PIECE_CHARS,
    PIECES_MAX,
    _fetch,
    build_input,
    plan_run,
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

    assert _fetch("https://d", reader, "https://d") is None
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
    assert watch_fetch._fetch(address, lambda u: watch_fetch._read_doc(u, []), address) is None
