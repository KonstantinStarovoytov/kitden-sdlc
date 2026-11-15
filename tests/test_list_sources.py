"""The check of a pull request that changes Kitden's list. Every page here is a fake: no network.

The rows are made up: no fact about a real client, and no text of a real page.
"""

import http.client
import re

import pytest

import list_sources
from doc_address import load_hosts
from list_sources import (
    CANNOT,
    GUESS,
    HELD,
    MISSING,
    NO_CHECK,
    NOT_ADDRESS,
    NOT_CHECKED,
    PAGES_MAX,
    SLOW,
    TIME_MAX,
    TOO_MANY,
    UNREAD,
    WORDS_MAX,
    Line,
    changed_rows,
    check,
    main,
    render,
)
from watch_list import held

HOSTS = load_hosts()
HEADER = "| What | Kind | Files | Seen in | macOS and Linux | Source |\n|---|---|---|---|---|---|\n"
# Lines 1 to 6 hold the title, the client and the table's head: row n is on line 6 + n.
TOP = "# The list\n\n## Claude Code\n\n" + HEADER


def doc(name: str) -> str:
    return f"https://code.claude.com/docs/en/{name}"


def row(what: str, source: str) -> str:
    return f"| {what} | key | `src/a.py` | scan | same | {source} |\n"


def make_list(rows: list[tuple[str, str]], codex: list[tuple[str, str]] = ()) -> str:
    text = TOP + "".join(row(what, source) for what, source in rows)
    if codex:
        text += "\n## Codex\n\n" + HEADER + "".join(row(w, s) for w, s in codex)
    return text


def filler(count: int) -> list[tuple[str, str]]:
    return [(f"Filler fact {n}", "help") for n in range(1, count + 1)]


class FakeReader:
    """Answers with the given pages: address -> body, or an exception to raise."""

    def __init__(self, pages=None, kind="text/markdown"):
        self.pages = pages or {}
        self.kind = kind
        self.calls: list[str] = []

    def __call__(self, address):
        self.calls.append(address)
        page = self.pages.get(address, OSError("HTTP Error 404"))
        if isinstance(page, BaseException):
            raise page
        return page, self.kind, address + ".md"


def run(rows, ids, pages=None, kind="text/markdown"):
    reader = FakeReader(pages, kind)
    lines = check(make_list(rows), ids, HOSTS, reader)
    return lines, reader


def warnings(lines) -> list[str]:
    return render(lines)[0]


def texts(lines) -> list[str]:
    """The warnings without their workflow command head."""
    return [w.split("::", 2)[2] for w in warnings(lines)]


# Step 1: which rows are checked, and what each verdict says.


def test_changed_rows_gives_an_added_row_and_a_row_with_a_changed_source():
    base = make_list([("`zork` one", doc("a")), ("`zork` two", doc("b")), ("`zork` three", "help")])
    head = make_list([("`zork` one", doc("a")), ("`zork` two", doc("c")), ("`zork` three", "help"),
                      ("`zork` four", "guess")])
    assert changed_rows(base, head) == ["CC-02", "CC-04"]


def test_changed_rows_goes_by_row_text_not_by_place():
    base = make_list([("`zork` one", doc("a")), ("`zork` two", doc("b"))])
    head = make_list([("`zork` new", doc("a")), ("`zork` one", doc("a")), ("`zork` two", doc("b"))])
    assert changed_rows(base, head) == ["CC-01"]


def test_changed_rows_counts_a_row_moved_to_another_client():
    base = make_list([("`zork` one", doc("a"))])
    head = make_list([], codex=[("`zork` one", doc("a"))])
    assert changed_rows(base, head) == ["CX-01"]


def edit(text: str, old: str, new: str) -> str:
    assert old in text
    return text.replace(old, new)


def test_changed_rows_skips_an_edit_of_files_seen_in_or_systems_only():
    base = make_list([("`zork` one", doc("a")), ("`zork` two", doc("b")),
                      ("`zork` three", doc("c"))])
    head = edit(base, "| `zork` one | key | `src/a.py` |",
                "| `zork` one | key | `src/moved/a.py` |")
    head = edit(head, "| `zork` two | key | `src/a.py` | scan |",
                "| `zork` two | key | `src/a.py` | a scan |")
    head = edit(head, "| scan | same | " + doc("c"), "| scan | macOS only | " + doc("c"))
    head = edit(head, "| `zork` three | key |", "| `zork` three | path |")
    assert changed_rows(base, head) == []


def test_changed_rows_takes_an_edit_of_what_or_source():
    base = make_list([("`zork` one", doc("a")), ("`zork` two", doc("b"))])
    head = edit(base, "`zork` one", "`zork` uno")
    head = edit(head, "| same | " + doc("b"), "| same | " + doc("bb"))
    assert changed_rows(base, head) == ["CC-01", "CC-02"]


@pytest.mark.parametrize(("old", "new"), [
    ("`zork` one (2026-10-01)", "`zork` one (2026-11-15)"),
    ("`zork` one (2026-10-19, version 2.1.283)", "`zork` one (2026-11-15, version 2.1.325)"),
    ("`zork` one (version 0.169.0)", "`zork` one (version 0.170.0)"),
    ("`zork` one", "`zork` one (2026-11-15)"),
])
def test_changed_rows_skips_a_new_date_or_version_note_in_what(old, new):
    # The same bracket groups the by-hand table's search question drops (watch_sources).
    base = make_list([(old, doc("a"))])
    assert changed_rows(base, edit(base, old, new)) == []


def test_changed_rows_takes_a_new_word_next_to_a_date():
    base = make_list([("`zork` one (2026-10-01)", doc("a"))])
    head = edit(base, "`zork` one (2026-10-01)", "`zork` `frob` one (2026-11-15)")
    assert changed_rows(base, head) == ["CC-01"]


def test_rows_whose_what_reads_the_same_without_backticks_keep_their_own_words():
    rows = [("`zork frob` x", doc("a")), ("`zork` frob x", doc("a"))]
    lines, _ = run(rows, ["CC-01", "CC-02"], {doc("a"): "zork\n"})
    assert lines == [Line("CC-01", 7, MISSING, ["frob"], 2), Line("CC-02", 8, HELD, [], 1)]


def test_changed_rows_is_empty_when_nothing_changed():
    text = make_list([("`zork` one", doc("a"))])
    assert changed_rows(text, text) == []


def test_changed_rows_takes_every_row_of_a_new_list():
    head = make_list([("`zork` one", doc("a")), ("b", "help")])
    assert changed_rows("", head) == ["CC-01", "CC-02"]


def test_a_page_that_holds_every_word_gives_no_warning():
    lines, reader = run([("`zork --frob` sets `gizmo.toml`", doc("a"))], ["CC-01"],
                        {doc("a"): "Run zork --frob to write gizmo.toml.\n"})
    assert lines == [Line("CC-01", 7, HELD, [], 3)]
    assert warnings(lines) == []
    assert "CC-01" not in render(lines)[1]
    assert reader.calls == [doc("a")]


def test_one_missing_word_gives_the_warning():
    rows = filler(20) + [("`zork --frob` sets `gizmo.toml`", doc("a"))]
    lines, _ = run(rows, ["CC-21"], {doc("a"): "Run zork --frob to write a file.\n"})
    assert lines == [Line("CC-21", 27, MISSING, ["gizmo.toml"], 3)]
    assert warnings(lines) == [
        "::warning file=docs/clients.md,line=27::CC-21: 1 of 3 exact words is not on the page"]


def test_the_warning_counts_every_missing_word():
    lines, _ = run([("`zork --frob` sets `gizmo.toml`", doc("a"))], ["CC-01"],
                   {doc("a"): "Nothing here.\n"})
    assert texts(lines) == ["CC-01: 3 of 3 exact words are not on the page"]
    lines, _ = run([("`gizmo.toml` holds it", doc("a"))], ["CC-01"], {doc("a"): "Nothing.\n"})
    assert texts(lines) == ["CC-01: 1 of 1 exact word is not on the page"]


def test_guess_says_where_to_look_for_a_page():
    rows = filler(3) + [("`zork --frob` turns it on", "guess")]
    lines, reader = run(rows, ["CC-04"])
    assert [line.verdict for line in lines] == [GUESS]
    assert texts(lines) == ["CC-04: no page named; scripts/watch_sources.py can look for one"]
    assert lines[0].line == 10
    assert reader.calls == []


@pytest.mark.parametrize("source", ["help", "install"])
def test_help_and_install_give_nothing(source):
    lines, reader = run([("`zork --frob` turns it on", source)], ["CC-01"])
    assert [line.verdict for line in lines] == [NO_CHECK]
    assert warnings(lines) == []
    assert "CC-01" not in render(lines)[1]
    assert reader.calls == []


@pytest.mark.parametrize("error", [OSError("timed out"), ValueError("redirected away"),
                                   http.client.IncompleteRead(b"")])
def test_a_page_that_cannot_be_read(error):
    rows = filler(6) + [("`zork --frob` turns it on", doc("a"))]
    lines, _ = run(rows, ["CC-07"], {doc("a"): error})
    assert lines == [Line("CC-07", 13, UNREAD, [], 2)]
    assert texts(lines) == ["CC-07: the page could not be read"]


def test_a_row_with_no_exact_word_gets_no_warning_and_is_counted():
    lines, reader = run([("Gadgets are slow on rainy days", doc("a"))], ["CC-01"])
    assert [line.verdict for line in lines] == [CANNOT]
    assert warnings(lines) == []
    summary = render(lines)[1]
    assert "Cannot check: 1." in summary
    assert "- CC-01, line 7: cannot check: the row has no exact word" in summary
    assert reader.calls == []


def test_only_the_rows_named_are_checked():
    rows = [("`zork` one", "guess"), ("`zork` two", "guess")]
    lines, _ = run(rows, ["CC-02"])
    assert [line.row_id for line in lines] == ["CC-02"]


def test_each_page_is_read_once():
    rows = [("`zork` one", doc("a")), ("`zork` two", doc("a")), ("`zork` three", doc("b"))]
    lines, reader = run(rows, ["CC-01", "CC-02", "CC-03"],
                        {doc("a"): "zork\n", doc("b"): OSError("down")})
    assert reader.calls == [doc("a"), doc("b")]
    assert [line.verdict for line in lines] == [HELD, HELD, UNREAD]


def test_a_failed_page_is_not_read_again():
    rows = [("`zork` one", doc("a")), ("`zork` two", doc("a"))]
    lines, reader = run(rows, ["CC-01", "CC-02"], {doc("a"): OSError("down")})
    assert reader.calls == [doc("a")]
    assert [line.verdict for line in lines] == [UNREAD, UNREAD]


def test_at_most_twenty_pages_are_read():
    assert PAGES_MAX == 20
    rows = [(f"`zork{n}` fact", doc(f"p{n}")) for n in range(1, 23)]
    rows.append(("`zork1` again", doc("p1")))
    pages = {doc(f"p{n}"): f"zork{n}\n" for n in range(1, 23)}
    ids = [f"CC-{n:02d}" for n in range(1, 24)]
    lines, reader = run(rows, ids, pages)
    assert reader.calls == [doc(f"p{n}") for n in range(1, 21)]
    assert [line.verdict for line in lines] == [HELD] * 20 + [NOT_CHECKED] * 2 + [HELD]
    assert warnings(lines) == []
    summary = render(lines)[1]
    assert "- CC-21, line 27: not checked: more than 20 pages in one pull request" in summary
    assert "Not checked: 2." in summary


class FakeClock:
    """A monotonic clock that moves on `step` seconds during each page read."""

    def __init__(self, step: float):
        self.now = 1000.0
        self.step = step

    def __call__(self):
        return self.now

    def reader(self, pages):
        inner = FakeReader(pages)

        def read(address):
            self.now += self.step
            return inner(address)

        read.calls = inner.calls
        return read


def test_the_check_stops_once_it_took_too_long():
    assert TIME_MAX == 180
    clock = FakeClock(50)
    rows = [(f"`zork{n}` fact", doc(f"p{n}")) for n in range(1, 7)]
    rows += [("`zork1` again", doc("p1")), ("`zork` guessed", "guess")]
    read = clock.reader({doc(f"p{n}"): f"zork{n}\n" for n in range(1, 7)})
    lines = check(make_list(rows), [f"CC-{n:02d}" for n in range(1, 9)], HOSTS, read, clock)
    # 50, 100, 150 seconds: a fourth read starts, and after it 200 seconds are spent. A row
    # on a page already read is not matched either; a guess costs nothing and still warns.
    assert read.calls == [doc(f"p{n}") for n in range(1, 5)]
    assert [line.verdict for line in lines] == [HELD] * 4 + [SLOW] * 3 + [GUESS]
    warned, summary = render(lines)
    assert [w.split("::")[2] for w in warned] == [
        "CC-08: no page named; scripts/watch_sources.py can look for one"]
    assert "- CC-05, line 11: not checked: the check took too long" in summary
    assert "Not checked: 3." in summary


def test_the_time_counts_from_the_start_of_the_check():
    clock = FakeClock(0)
    rows = [("`zork` one", doc("a")), ("`zork` two", doc("b"))]
    read = clock.reader({doc("a"): "zork\n", doc("b"): "zork\n"})
    clock.now += 10_000  # time before the check does not count
    lines = check(make_list(rows), ["CC-01", "CC-02"], HOSTS, read, clock)
    assert [line.verdict for line in lines] == [HELD, HELD]


def test_the_time_counts_word_matching_too(monkeypatch):
    # Reads take no time here; each row's matching takes 100 seconds.
    clock = FakeClock(0)

    def slow_held(words, body):
        clock.now += 100
        return held(words, body)

    monkeypatch.setattr(list_sources, "held", slow_held)
    rows = [("`zork` one", doc("a")), ("`zork` two", doc("a")), ("`zork` three", doc("a")),
            ("`zork` four", "guess")]
    read = clock.reader({doc("a"): "zork\n"})
    lines = check(make_list(rows), ["CC-01", "CC-02", "CC-03", "CC-04"], HOSTS, read, clock)
    assert [line.verdict for line in lines] == [HELD, HELD, SLOW, GUESS]


def test_a_row_with_more_than_forty_exact_words_is_not_checked():
    assert WORDS_MAX == 40
    many = " ".join(f"`w{n}x`" for n in range(41))
    rows = [(many, doc("a")), (" ".join(f"`w{n}x`" for n in range(40)), doc("a"))]
    lines, reader = run(rows, ["CC-01", "CC-02"], {doc("a"): "nothing\n"})
    assert [line.verdict for line in lines] == [TOO_MANY, MISSING]
    assert reader.calls == [doc("a")]  # read for the second row only
    warned, summary = render(lines)
    assert [w.split("::")[2].split(":")[0] for w in warned] == ["CC-02"]
    assert "- CC-01, line 7: not checked: more than 40 exact words" in summary
    assert "Not checked: 1." in summary


def test_a_failed_read_counts_toward_the_time():
    clock = FakeClock(200)
    rows = [("`zork` one", doc("a")), ("`zork` two", doc("b"))]
    read = clock.reader({doc("a"): OSError("slow and failed")})
    lines = check(make_list(rows), ["CC-01", "CC-02"], HOSTS, read, clock)
    assert [line.verdict for line in lines] == [UNREAD, SLOW]


def test_main_passes_its_clock_to_check(tmp_path, capsys):
    clock = FakeClock(500)
    head = make_list([("`zork` one", doc("a")), ("`zork` two", doc("b"))])
    read = clock.reader({doc("a"): "zork\n", doc("b"): "zork\n"})
    summary = tmp_path / "summary.md"
    assert main(files(tmp_path, "", head), {"GITHUB_STEP_SUMMARY": str(summary)}, read,
                clock) == 0
    assert "CC-02, line 8: not checked: the check took too long" in summary.read_text()


def test_an_html_page_is_read_as_its_text():
    # In the markup, tags cut the words and `&` is written `&amp;`.
    page = "<p>Run <code>zork</code>--frob, x&amp;y and <b>gizmo</b>.toml</p>"
    rows = [("`zork--frob` and `gizmo.toml` and `x&y`", doc("a"))]
    lines, _ = run(rows, ["CC-01"], {doc("a"): page}, kind="text/html")
    assert lines == [Line("CC-01", 7, HELD, [], 3)]


def test_a_page_that_cannot_be_parsed_is_a_page_not_read(monkeypatch):
    def broken(body, kind):
        raise ValueError("bad markup")

    monkeypatch.setattr(list_sources, "sections", broken)
    rows = [("`zork` one", doc("a"))]
    lines, _ = run(rows, ["CC-01"], {doc("a"): "<p>zork</p>"}, kind="text/html")
    assert [line.verdict for line in lines] == [UNREAD]


def test_the_summary_counts_every_verdict():
    rows = [("`zork` one", doc("a")), ("`zork` two", doc("b")), ("`zork` three", "guess"),
            ("`zork` four", "help"), ("`zork` five", "https://example.com/docs/x"),
            ("five", doc("a")), ("`zork` six", doc("c"))]
    ids = [f"CC-{n:02d}" for n in range(1, 8)]
    lines, _ = run(rows, ids, {doc("a"): "zork\n", doc("b"): "nothing\n"})
    summary = render(lines)[1]
    assert ("Rows added or changed: 7. Every word on the page: 1. Words missing: 1. "
            "Page not read: 1. Not a doc address: 1. No page named: 1. Cannot check: 1. "
            "`help` or `install`: 1.\n") in summary


def test_the_summary_counts_only_what_happened():
    lines, _ = run([("`zork` one", "guess")], ["CC-01"])
    assert "Rows added or changed: 1. No page named: 1.\n" in render(lines)[1]


def test_the_summary_shows_at_most_ten_missing_words_a_row():
    words = [f"w{n}x" for n in range(1, 13)]
    lines = [Line("CC-01", 7, MISSING, words, 12)]
    item = [line for line in render(lines)[1].splitlines() if line.startswith("- ")]
    assert item == ["- CC-01, line 7: 12 of 12 exact words are not on the page: "
                    + ", ".join(f"`{w}`" for w in words[:10]) + " and 2 more"]


def test_the_summary_lists_at_most_a_hundred_rows():
    lines = [Line(f"CC-{n:03d}", n, GUESS, [], 1) for n in range(1, 106)]
    warned, summary = render(lines)
    assert len(warned) == 105
    items = [line for line in summary.splitlines() if line.startswith("- ")]
    assert len(items) == 101
    assert items[-1] == "- and 5 more rows"


def test_render_refuses_a_row_id_it_did_not_make():
    with pytest.raises(ValueError):
        render([Line("CC-01::error::x", 7, GUESS, [], 1)])


def test_the_summary_names_a_table_under_an_unknown_heading():
    warned, summary = render([], ["Claude Code (CLI)", "Zed`|\x07" + "z" * 70])
    assert warned == []
    items = [line for line in summary.splitlines() if line.startswith("- ")]
    assert items == [
        "- the table under `Claude Code (CLI)` was skipped: its heading is not a client's",
        "- the table under `Zed" + "z" * 57 + "` was skipped: its heading is not a client's",
    ]
    assert "No row was added or changed." not in summary
    assert "No row was added or changed in the tables of the known clients." in summary


def test_the_summary_names_at_most_ten_unknown_headings():
    summary = render([], [f"H{n}" for n in range(12)])[1]
    items = [line for line in summary.splitlines() if line.startswith("- ")]
    assert len(items) == 11
    assert items[-1] == "- and 2 more skipped tables"


def test_main_names_a_renamed_heading(tmp_path, capsys):
    base = make_list([("`zork` one", doc("a"))])
    head = base.replace("## Claude Code", "## Claude  Code")
    summary = tmp_path / "summary.md"
    assert main(files(tmp_path, base, head), {"GITHUB_STEP_SUMMARY": str(summary)},
                FakeReader()) == 0
    assert "- the table under `Claude  Code` was skipped" in summary.read_text()
    assert capsys.readouterr().out == ""


def test_the_summary_says_when_no_row_changed():
    warned, summary = render([])
    assert warned == []
    assert "No row was added or changed." in summary


# Step 2 (Review Focus 5): a pull request's text cannot pass for a workflow command, break the
# summary, or make the check read another host.

WARNING = re.compile(
    r"::warning file=docs/clients\.md,line=\d+::(CC|CX|CU)-\d{2,}: "
    r"(\d+ of \d+ exact words? (is|are) not on the page"
    r"|no page named; scripts/watch_sources\.py can look for one"
    r"|the page could not be read"
    r"|`Source` is not a doc address)")

HOSTILE = [
    "`::error::boom`",
    "`%0A::error::boom`",
    "`x%25y%0D%0Az`",
    "`a|b`",
    "`" + "w" * 70 + "`",
    "`bell\x07ring`",
    "`flip‮me`",
    "`::warning file=x,line=1::fake`",
    "`##[error]old`",
    "`odd`tick`",
]


def hostile_list(source: str) -> str:
    """Rows full of what a pull request might write, a CR and a LF among them."""
    rows = [(f"{word} and `zork`", source) for word in HOSTILE]
    text = make_list(rows)
    # A CR or a LF in a row ends the row's line: what is left is not a row of six cells.
    text += row("`cr\rcarriage` and `zork`", source) + row("`lf\nline` and `zork`", source)
    return text


def check_hostile(source, pages=None):
    reader = FakeReader(pages)
    text = hostile_list(source)
    lines = check(text, changed_rows("", text), HOSTS, reader)
    return lines, reader


def test_hostile_rows_change_no_warning():
    lines, _ = check_hostile(doc("a"), {doc("a"): "zork\n"})
    warned = warnings(lines)
    assert len(warned) == len(HOSTILE)
    for line in warned:
        assert WARNING.fullmatch(line), line


def test_hostile_rows_with_a_failed_page_or_a_guess_change_no_warning():
    for source in (doc("a"), "guess", "https://example.com/docs/a"):
        lines, _ = check_hostile(source)
        for line in warnings(lines):
            assert WARNING.fullmatch(line), line


def code_spans(summary: str) -> list[str]:
    return re.findall(r"`([^`\n]*)`", summary)


def test_the_summary_shows_missing_words_cut_cleaned_and_as_code():
    lines, _ = check_hostile(doc("a"), {doc("a"): "zork\n"})
    summary = render(lines)[1]
    shown = [line for line in summary.splitlines() if line.startswith("- ") and "exact" in line]
    assert len(shown) == len(HOSTILE)
    words = [span for line in shown for span in code_spans(line.split(": ", 2)[2])]
    # row_words takes the list's prose marks, `:` among them, off a word's ends.
    assert "error::boom" in words
    assert "%0A::error::boom" in words
    assert "x%25y%0D%0Az" in words
    assert "ab" in words
    assert "w" * 60 in words
    assert "bellring" in words
    assert "flipme" in words
    assert all(len(w) <= 60 for w in words)
    for line in shown:
        # Each word stands in its own code span: the rest is fixed text.
        rest = re.sub(r"`[^`\n]*`", "", line.split(": ", 2)[2])
        assert re.fullmatch(r"(, )*", rest), line
    assert "|" not in summary
    assert "\x07" not in summary and "‮" not in summary and "\r" not in summary


def test_no_summary_line_starts_like_a_workflow_command():
    lines, _ = check_hostile(doc("a"), {doc("a"): "zork\n"})
    for line in render(lines)[1].splitlines():
        assert not line.lstrip().startswith("::"), line


def test_an_address_on_another_host_is_not_read_and_not_printed():
    rows = filler(8) + [("`zork --frob` turns it on", "https://example.com/docs/en/zork")]
    lines, reader = run(rows, ["CC-09"], {"https://example.com/docs/en/zork": "zork --frob"})
    assert reader.calls == []
    assert lines == [Line("CC-09", 15, NOT_ADDRESS, [], 2)]
    assert texts(lines) == ["CC-09: `Source` is not a doc address"]
    warned, summary = render(lines)
    assert "example.com" not in "\n".join(warned) + summary


@pytest.mark.parametrize("source", [
    "http://code.claude.com/docs/en/zork",
    "https://code.claude.com/docs/en/zork?x=1",
    "https://code.claude.com:444/docs/en/zork",
    "https://code.claude.com/blog/zork",
    "see the docs",
    "",
])
def test_any_address_that_fails_the_check_is_not_read(source):
    lines, reader = run([("`zork` fact", source)], ["CC-01"])
    assert reader.calls == []
    assert [line.verdict for line in lines] == [NOT_ADDRESS]


SECRET_PAGE = "Plinth-marker-7Qx: page text that must never be printed. zork"


def test_no_text_of_a_page_is_in_any_output(tmp_path, capsys):
    rows = [("`zork` and `gizmo`", doc("a")), ("`zork` only", doc("a"))]
    head = tmp_path / "head.md"
    head.write_text(make_list(rows))
    base = tmp_path / "base.md"
    base.write_text("")
    summary = tmp_path / "summary.md"
    code = main(["--base", str(base), "--head", str(head)], {"GITHUB_STEP_SUMMARY": str(summary)},
                FakeReader({doc("a"): SECRET_PAGE}))
    out = capsys.readouterr()
    assert code == 0
    every = out.out + out.err + summary.read_text()
    assert "Plinth" not in every and "never printed" not in every
    assert "1 of 2 exact words" in every


# main


def files(tmp_path, base: str, head: str):
    (tmp_path / "base.md").write_text(base)
    (tmp_path / "head.md").write_text(head)
    return ["--base", str(tmp_path / "base.md"), "--head", str(tmp_path / "head.md")]


def test_main_prints_the_warnings_and_writes_the_summary(tmp_path, capsys):
    base = make_list([("`zork` one", doc("a"))])
    head = make_list([("`zork` one", doc("a")), ("`gizmo` two", doc("a")),
                      ("`zork` three", "guess")])
    summary = tmp_path / "summary.md"
    summary.write_text("before\n")
    code = main(files(tmp_path, base, head), {"GITHUB_STEP_SUMMARY": str(summary)},
                FakeReader({doc("a"): "zork\n"}))
    out = capsys.readouterr()
    assert code == 0
    assert out.out.splitlines() == [
        "::warning file=docs/clients.md,line=8::CC-02: 1 of 1 exact word is not on the page",
        "::warning file=docs/clients.md,line=9::CC-03: no page named; scripts/watch_sources.py "
        "can look for one",
    ]
    written = summary.read_text()
    assert written.startswith("before\n")
    assert "- CC-02, line 8: 1 of 1 exact word is not on the page: `gizmo`" in written


def test_main_prints_only_its_warnings_to_stdout(tmp_path, capsys):
    head = hostile_list(doc("a"))
    summary = tmp_path / "summary.md"
    main(files(tmp_path, "", head), {"GITHUB_STEP_SUMMARY": str(summary)},
         FakeReader({doc("a"): "zork\n"}))
    out = capsys.readouterr()
    for line in out.out.splitlines():
        assert WARNING.fullmatch(line), line
    for line in out.err.splitlines():
        assert not line.lstrip().startswith("::"), line


def test_main_prints_the_summary_when_there_is_no_summary_file(tmp_path, capsys):
    head = hostile_list(doc("a"))
    assert main(files(tmp_path, "", head), {}, FakeReader({doc("a"): "zork\n"})) == 0
    out = capsys.readouterr().out
    assert "Rows added or changed:" in out
    for line in out.splitlines():
        assert WARNING.fullmatch(line) or not line.lstrip().startswith("::"), line


def test_main_reads_pages_with_get_doc_by_default(tmp_path, capsys, monkeypatch):
    calls = []

    def fake_get_doc(address, hosts, opener=None):
        calls.append((address, hosts))
        return "zork\n", "text/markdown", address + ".md"

    monkeypatch.setattr(list_sources, "get_doc", fake_get_doc)
    head = make_list([("`zork` one", doc("a"))])
    assert main(files(tmp_path, "", head), {}) == 0
    assert calls == [(doc("a"), HOSTS)]


@pytest.mark.parametrize("which", ["base", "head"])
def test_main_exits_0_when_a_file_cannot_be_read(tmp_path, capsys, which):
    argv = files(tmp_path, "", make_list([("`zork` one", "guess")]))
    (tmp_path / f"{which}.md").unlink()
    summary = tmp_path / "summary.md"
    reader = FakeReader()
    assert main(argv, {"GITHUB_STEP_SUMMARY": str(summary)}, reader) == 0
    out = capsys.readouterr()
    assert out.out == "::warning::list check failed: FileNotFoundError\n"
    assert f"The {which} list could not be read: nothing was checked." in summary.read_text()
    assert reader.calls == []


def test_main_exits_0_when_a_file_is_not_utf8(tmp_path, capsys):
    argv = files(tmp_path, "", "")
    (tmp_path / "head.md").write_bytes(b"\xff\xfe\x00bad")
    assert main(argv, {}, FakeReader()) == 0
    out = capsys.readouterr().out
    assert out.startswith("::warning::list check failed: UnicodeDecodeError\n")
    assert "The head list could not be read: nothing was checked." in out


def test_main_exits_0_on_bad_arguments(capsys):
    assert main(["--base"], {}, FakeReader()) == 0
    assert main([], {}, FakeReader()) == 0
    said = ("::warning::list check failed: SystemExit\n"
            "The list check could not start: bad arguments.\n")
    assert capsys.readouterr().out == said * 2
    assert main(["--help"], {}, FakeReader()) == 0  # asked for, so not a failure
    assert "::warning::" not in capsys.readouterr().out


def test_main_exits_0_on_a_bug_and_names_only_its_class(tmp_path, capsys):
    head = make_list([("`zork` one", doc("a"))])

    def broken(address):
        raise RuntimeError("Plinth secret detail")

    summary = tmp_path / "summary.md"
    assert main(files(tmp_path, "", head), {"GITHUB_STEP_SUMMARY": str(summary)}, broken) == 0
    out = capsys.readouterr()
    # A bug must not leave a silent green check: a warning, and one line in the summary.
    assert out.out == "::warning::list check failed: RuntimeError\n"
    assert summary.read_text() == "The list check failed: RuntimeError. Nothing more was checked.\n"
    assert "Plinth" not in out.out + out.err + summary.read_text()


def test_main_exits_0_when_the_summary_file_cannot_be_written(tmp_path, capsys):
    head = make_list([("`zork` one", "guess")])
    bad = tmp_path / "no-such-folder" / "summary.md"
    assert main(files(tmp_path, "", head), {"GITHUB_STEP_SUMMARY": str(bad)}, FakeReader()) == 0
    out = capsys.readouterr()
    assert "CC-01: no page named" in out.out
    assert out.out.endswith("::warning::list check failed: FileNotFoundError\n")
