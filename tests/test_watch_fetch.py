import json

import watch_fetch
from watch_fetch import FAIL_DAYS, PIECE_CHARS, PIECES_MAX, _fetch, build_input, plan_run
from watch_pages import Section

META = {"s": {"client": "codex", "kind": "release", "url": "https://x/s"}}
EMPTY = {"fails": {}, "kept": [], "urgent": {"week": "", "count": 0}}


def old(sources, **extra):
    return {"sources": sources, **EMPTY, **extra}


def test_first_run_fills_and_makes_no_pieces():
    pieces, state = plan_run(None, {"s": [Section("1.0", "t", "h")]}, META)
    assert pieces == [] and state["sources"]["s"] == {"1.0": "h"}
    assert state["summary_week"] == "" and state["tries"] == {}


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
