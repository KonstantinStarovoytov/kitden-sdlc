# ruff: noqa: E501
"""The table of doc pages for rows that have none. Every search here is a fake: no network."""

import re
from pathlib import Path

import pytest

import watch_sources
from agent_docs import Search, make_opener
from doc_address import load_hosts
from tests.test_agent_docs import (
    HEALTH,
    OPENAPI,
    SEARCH,
    WITH,
    WITHOUT,
    FakeWeb,
    json_answer,
    openapi,
)
from watch_fetch import MOVED_TEXT
from watch_sources import clean_heading, main, pick_rows

HOSTS = load_hosts()
KEY = "Tq4Wn8RowsKeyHx2Ld6Pz3"
ENV = {"COHERE_API_KEY": KEY}

# Made-up rows: no fact about a real client.
LIST = """# The list

## Claude Code

| What | Kind | Files | Seen in | macOS and Linux | Source |
|---|---|---|---|---|---|
| `zork --frob` turns the frob on | command | `src/a.py` | scan | same | guess |
| Widgets live in `~/.zork/widgets.toml` under `gizmos` | path | `src/a.py` | scan | same | install |
| Gadgets are slow on rainy days | key | `src/a.py` | scan | same | help |
| `zork plugin-add` adds a plugin | command | `src/a.py` | scan | same | https://code.claude.com/docs/en/plugins |

## Codex

| What | Kind | Files | Seen in | macOS and Linux | Source |
|---|---|---|---|---|---|
| `quux run` reads `quux.toml` | command | `src/b.py` | scan | same | guess |

## Cursor

| What | Kind | Files | Seen in | macOS and Linux | Source |
|---|---|---|---|---|---|
| Rules in `.blorp/rules` | path | `src/c.py` | scan | same | install |
"""

# The rows' questions: their What without backticks.
CC1 = "zork --frob turns the frob on"
CC2 = "Widgets live in ~/.zork/widgets.toml under gizmos"
CC3 = "Gadgets are slow on rainy days"
CC4 = "zork plugin-add adds a plugin"
CX1 = "quux run reads quux.toml"
CU1 = "Rules in .blorp/rules"

PAGE = "https://code.claude.com/docs/en/zork.md"
SHOWN = "https://code.claude.com/docs/en/zork"
FAIL = object()


def passage(text, url=PAGE, heading="Turn the frob on"):
    return {"url": url, "heading": heading, "text": text}


class FakeSearch:
    """Answers from `answers` (question: passages, or FAIL); an unknown question gets []."""

    def __init__(self, answers=None, woke=True, product=True):
        self.answers = answers or {}
        self.woke = woke
        self.product = product
        self.calls = []
        self.cuts = []
        self.asked = 0
        self.failed = 0

    def wake(self):
        self.calls.append("wake")
        return self.woke

    def has_product(self):
        self.calls.append("has_product")
        return self.product

    def search(self, query, product, cut=1500):
        self.calls.append(("search", query, product))
        self.cuts.append(cut)
        self.asked += 1
        found = self.answers.get(query, [])
        if found is FAIL:
            self.failed += 1
            return []
        return found

    @property
    def searched(self):
        return [call[1:] for call in self.calls if isinstance(call, tuple)]


class Run:
    """One run of main(), with its exit code, stdout, stderr and the fakes it used."""

    def __init__(self, code, out, err, search, sleeps, pages):
        self.code, self.out, self.err = code, out, err
        self.search, self.sleeps, self.pages = search, sleeps, pages

    def line(self, row_id):
        [found] = [ln for ln in self.out.splitlines() if ln.startswith(f"| {row_id} ")]
        return found

    @property
    def first(self):
        return self.out.splitlines()[0]


@pytest.fixture
def run(tmp_path, capsys):
    (tmp_path / "docs").mkdir()

    def go(*args, answers=None, text=LIST, env=ENV, search=None, moved=(), woke=True, product=True):
        (tmp_path / "docs" / "clients.md").write_text(text)
        fake = search or FakeSearch(answers, woke=woke, product=product)
        sleeps, pages = [], []

        def find_moved(given):
            pages.append(given)
            return None if moved is None else list(moved)

        code = main(["--kitden", str(tmp_path), *args], env=env, make_search=lambda key: fake,
                    sleep=sleeps.append, find_moved=find_moved)
        out, err = capsys.readouterr()
        return Run(code, out, err, fake, sleeps, pages)

    return go


# Which rows are checked


def test_pick_rows_gives_ids_labels_and_exact_words():
    items = pick_rows(LIST)
    assert [i.id for i in items] == ["CC-01", "CC-02", "CC-03", "CX-01", "CU-01"]
    first = items[0]
    assert (first.client, first.label, first.what, first.source) == (
        "claude-code", "`zork --frob` turns the frob on", CC1, "guess")
    assert first.words == ["zork", "--frob"]
    assert items[2].words == []


def test_pick_rows_takes_each_rows_own_words():
    # Without backticks both Whats read "zork frob x": the words go by the row, not the What.
    text = LIST.replace("| `zork --frob` turns the frob on |", "| `zork frob` x |").replace(
        "| Widgets live in `~/.zork/widgets.toml` under `gizmos` |", "| `zork` frob x |")
    items = pick_rows(text)
    assert [(i.id, i.words) for i in items[:2]] == [("CC-01", ["zork", "frob"]),
                                                   ("CC-02", ["zork"])]


def test_rows_with_an_address_are_skipped(run):
    result = run()
    assert ("search", CC4, "claude-code") not in result.search.calls
    assert "CC-04" not in result.out


def test_all_checks_rows_with_an_address_too(run):
    result = run("--all")
    assert (CC4, "claude-code") in result.search.searched
    assert "| CC-04 " in result.out


def test_one_search_a_row_with_the_what_as_question_and_the_client_as_product(run):
    result = run()
    assert result.search.searched == [(CC1, "claude-code"), (CC2, "claude-code"),
                                      (CC3, "claude-code"), (CX1, "codex"), (CU1, "cursor")]


DATED = LIST.replace(
    "| `zork --frob` turns the frob on |",
    "| `zork --frob` turns the frob on (2026-10-21) |").replace(
    "under `gizmos` |", "under `gizmos` (2026-10-19, version 2.1.283) |").replace(
    "| Gadgets are slow on rainy days |", "| Gadgets (version 2.1.4) are slow (on rainy days) |")


def test_the_question_leaves_out_dates_and_versions_in_brackets(run):
    result = run(text=DATED)
    assert result.search.searched[:3] == [
        ("zork --frob turns the frob on", "claude-code"),
        ("Widgets live in ~/.zork/widgets.toml under gizmos", "claude-code"),
        ("Gadgets are slow (on rainy days)", "claude-code"),
    ]


def test_the_exact_words_keep_what_the_question_leaves_out():
    items = pick_rows(DATED)
    assert items[0].words == ["zork", "--frob"]
    assert items[0].what == "zork --frob turns the frob on (2026-10-21)"


@pytest.mark.parametrize(("what", "question"), [
    ("a (2026-10-21) b", "a b"),
    ("a (2026-11-15, version 2.1.325, Linux)", "a"),
    ("a (version 0.169.0) b (2026-10-27)", "a b"),
    ("a (the gateway speaks only http) b", "a (the gateway speaks only http) b"),
    ("a (2026) b", "a (2026) b"),
])
def test_question_drops_only_dated_and_version_groups(what, question):
    from watch_sources import question as ask
    assert ask(what) == question


def test_each_search_asks_for_passages_cut_at_4000_characters(run):
    assert run().search.cuts == [4000] * 5


def test_client_limits_the_run_to_that_client(run):
    result = run("--client", "codex")
    assert result.search.searched == [(CX1, "codex")]


def test_rows_limits_the_run_to_those_rows(run):
    result = run("--rows", "CC-02,cx-01")
    assert result.search.searched == [(CC2, "claude-code"), (CX1, "codex")]


def test_rows_may_name_a_row_with_an_address(run):
    result = run("--rows", "CC-04")
    assert result.search.searched == [(CC4, "claude-code")]


def test_rows_with_an_unknown_id_stops_before_any_search(run):
    result = run("--rows", "CC-01,CC-99")
    assert result.code == 2
    assert "CC-99" in result.err
    assert result.search.calls == []
    assert result.out == ""


def test_rows_and_client_together_are_refused(run):
    with pytest.raises(SystemExit) as caught:
        run("--rows", "CC-01", "--client", "codex")
    assert caught.value.code == 2


def test_an_unknown_client_is_refused(run):
    with pytest.raises(SystemExit) as caught:
        run("--client", "vim")
    assert caught.value.code == 2


# Verdicts


def test_a_passage_holding_every_word_states_it_with_page_and_heading(run):
    result = run(answers={CC1: [passage("Run zork --frob to start.")]})
    assert result.line("CC-01") == (
        "| CC-01 `zork --frob` turns the frob on | guess "
        f"| `{SHOWN}`, `Turn the frob on` | states it |")


def test_the_page_is_shown_without_md_and_without_a_fragment(run):
    result = run(answers={CC1: [passage("zork --frob", url=PAGE + "#the-frob")]})
    assert f"`{SHOWN}`," in result.line("CC-01")
    assert "#the-frob" not in result.out


def test_some_words_is_near_with_the_count_and_the_missing_words(run):
    result = run(answers={CC2: [passage("Put it in ~/.zork/widgets.toml.", heading="Widgets")]})
    line = result.line("CC-02")
    assert "near: 1 of 2; missing `gizmos`" in line
    assert f"`{SHOWN}`, `Widgets`" in line


def test_near_shows_the_passage_holding_the_most_words(run):
    url = "https://code.claude.com/docs/en/widgets.md"
    result = run(answers={CC2: [
        passage("nothing here", heading="First"),
        passage("~/.zork/widgets.toml", url=url, heading="Second"),
    ]})
    line = result.line("CC-02")
    assert "near: 1 of 2" in line
    assert "`https://code.claude.com/docs/en/widgets`, `Second`" in line


def test_near_on_a_tie_shows_the_higher_passage(run):
    result = run(answers={CC2: [
        passage("gizmos", heading="First"),
        passage("~/.zork/widgets.toml", heading="Second"),
    ]})
    assert "`First`" in result.line("CC-02")


def test_a_passage_holding_none_of_the_words_is_no_page_with_a_note(run):
    result = run(answers={CC2: [passage("nothing here"), passage("still nothing")]})
    assert result.line("CC-02") == (
        "| CC-02 Widgets live in `~/.zork/widgets.toml` under `gizmos` | install "
        "|  | no page: the top passage holds none of its words |")
    assert result.first == ("Rows checked: 5. States it: 0 (weak words only: 0). Near: 0. "
                            "Cannot check: 0. No page: 5. Search failed: 0.")


def test_near_needs_at_least_one_word(run):
    result = run(answers={CC2: [passage("gizmos")]})
    assert "near: 1 of 2" in result.line("CC-02")


def test_states_it_uses_a_lower_passage_that_holds_every_word(run):
    url = "https://code.claude.com/docs/en/frob.md"
    result = run(answers={CC1: [
        passage("zork alone", heading="First"),
        passage("zork --frob", url=url, heading="Second"),
    ]})
    line = result.line("CC-01")
    assert line.endswith("| states it |")
    assert "`https://code.claude.com/docs/en/frob`, `Second`" in line


def test_the_heading_counts_as_part_of_the_passage(run):
    result = run(answers={CC1: [passage("Run --frob.", heading="zork")]})
    assert result.line("CC-01").endswith("| states it |")


def test_words_are_compared_as_written(run):
    result = run(answers={CC1: [passage("ZORK --frob")]})
    assert "near: 1 of 2; missing `zork`" in result.line("CC-01")


def test_a_row_with_no_exact_word_cannot_be_checked_and_shows_the_top_passage(run):
    result = run(answers={CC3: [
        passage("Gadgets are slow on rainy days", heading="Gadgets"),
        passage("other", url="https://code.claude.com/docs/en/other.md"),
    ]})
    line = result.line("CC-03")
    assert line.endswith("| cannot check: no exact word |")
    assert f"`{SHOWN}`, `Gadgets`" in line
    assert "other" not in line


def test_a_row_with_no_exact_word_is_never_states_it(run):
    result = run(answers={CC3: [passage(CC3)]})
    assert "states it" not in result.line("CC-03")


def test_no_passage_is_no_page(run):
    result = run(answers={CC1: []})
    assert result.line("CC-01") == "| CC-01 `zork --frob` turns the frob on | guess |  | no page |"


def test_a_failed_search_is_search_failed_not_no_page(run):
    result = run(answers={CC1: FAIL})
    line = result.line("CC-01")
    assert line.endswith("| search failed |")
    assert "no page" not in line


def test_a_row_with_no_word_and_a_failed_search_is_search_failed(run):
    result = run(answers={CC3: FAIL})
    assert result.line("CC-03").endswith("| search failed |")


def test_a_row_with_no_word_and_no_passage_is_no_page(run):
    result = run(answers={CC3: []})
    assert result.line("CC-03").endswith("| no page |")


# Rows that have their own page (--all)


def test_a_row_whose_own_page_states_it_is_not_flagged(run):
    result = run("--all", answers={CC4: [
        passage("zork plugin-add", url="https://code.claude.com/docs/en/plugins.md")]})
    line = result.line("CC-04")
    assert line.endswith("| states it |")
    assert "https://code.claude.com/docs/en/plugins |" in line


def test_a_row_whose_page_is_not_the_one_that_states_it_is_flagged_other_page(run):
    result = run("--all", answers={CC4: [passage("zork plugin-add")]})
    line = result.line("CC-04")
    assert line.endswith("| states it, other page |")
    assert f"`{SHOWN}`" in line


def test_the_own_page_is_shown_when_it_states_it_below_another_page(run):
    own = "https://code.claude.com/docs/en/plugins.md"
    result = run("--all", answers={CC4: [
        passage("zork plugin-add", heading="Elsewhere"),
        passage("zork plugin-add", url=own, heading="Own"),
    ]})
    line = result.line("CC-04")
    assert line.endswith("| states it |")
    assert "`https://code.claude.com/docs/en/plugins`, `Own`" in line


def test_a_row_with_an_address_that_is_only_near_is_not_flagged(run):
    result = run("--all", answers={CC4: [passage("zork")]})
    assert "other page" not in result.line("CC-04")


# The first line


def test_the_first_line_counts_each_verdict(run):
    result = run(answers={
        CC1: [passage("zork --frob")],
        CC2: [passage("gizmos")],
        CC3: [passage("anything")],
        CX1: [],
        CU1: FAIL,
    })
    assert result.first == ("Rows checked: 5. States it: 1 (weak words only: 0). Near: 1. "
                            "Cannot check: 1. No page: 1. Search failed: 1.")


SHORT = LIST.replace("| `quux run` reads `quux.toml` |", "| `qx` reads `-r` and `a.b` |")


def test_a_states_it_on_short_words_only_is_weak(run):
    result = run("--rows", "CX-01", text=SHORT, answers={"qx reads -r and a.b": [passage("qx -r a.b")]})
    assert result.line("CX-01").endswith("| states it (weak words only) |")
    assert result.first.startswith("Rows checked: 1. States it: 1 (weak words only: 1). ")


PLAIN = LIST.replace("| `quux run` reads `quux.toml` |", "| It reads a `file` and its `description` |")


def test_a_states_it_on_plain_lowercase_words_only_is_weak(run):
    question = "It reads a file and its description"
    result = run("--rows", "CX-01", text=PLAIN, answers={question: [passage("a description file")]})
    assert result.line("CX-01").endswith("| states it (weak words only) |")
    assert "(weak words only: 1)" in result.first


def test_a_states_it_with_one_strong_word_is_not_weak(run):
    result = run("--rows", "CX-01", answers={CX1: [passage("quux run quux.toml")]})
    assert result.line("CX-01").endswith("| states it |")
    assert "(weak words only: 0)" in result.first


def test_weak_words_and_other_page_go_together(run):
    text = LIST.replace("`zork plugin-add` adds", "`zork` `plugin` `add` adds")
    result = run("--rows", "CC-04", text=text,
                 answers={"zork plugin add adds a plugin": [passage("zork plugin add")]})
    assert result.line("CC-04").endswith("| states it (weak words only), other page |")


def test_a_short_word_inside_a_longer_one_is_not_found(run):
    result = run("--rows", "CX-01", text=SHORT, answers={"qx reads -r and a.b": [
        passage("qxz --r a.bc")]})
    assert result.line("CX-01").endswith("| no page: the top passage holds none of its words |")


def test_the_first_line_counts_other_page_when_rows_with_an_address_are_checked(run):
    result = run("--all", answers={CC4: [passage("zork plugin-add")]})
    assert result.first.endswith(" Other page: 1.")


def test_a_run_where_every_search_failed_says_so_in_the_first_line(run):
    result = run("--rows", "CC-01,CC-02", answers={CC1: FAIL, CC2: FAIL})
    assert result.first.startswith("Every search failed")
    assert "Search failed: 2." in result.first
    assert result.code == 0


ALL_FAIL = {q: FAIL for q in (CC1, CC2, CC3, CX1, CU1)}


def test_three_failed_searches_first_stop_the_run_with_exit_5(run):
    result = run(answers=ALL_FAIL)
    assert result.code == 5
    assert result.search.searched == [(CC1, "claude-code"), (CC2, "claude-code"),
                                      (CC3, "claude-code")]
    assert result.sleeps == [7, 7]
    stop = [ln for ln in result.err.splitlines() if "searches fail" in ln]
    assert len(stop) == 1
    assert "key" in stop[0] and "limit" in stop[0] and "server" in stop[0]


def test_a_stopped_run_prints_the_table_of_what_was_done(run):
    result = run(answers=ALL_FAIL, moved=[])
    assert result.first.startswith("Every search failed")
    assert "Rows checked: 3." in result.first
    assert [result.line(r).endswith("| search failed |") for r in ("CC-01", "CC-02", "CC-03")] \
        == [True, True, True]
    assert "| CX-01 " not in result.out
    assert "Stopped after 3 failed searches: 2 rows were not searched." in result.out
    assert "Every doc page of the list is in Agent Docs." in result.out


def test_three_rows_that_all_fail_also_exit_5(run):
    result = run("--rows", "CC-01,CC-02,CC-03", answers=ALL_FAIL)
    assert result.code == 5
    assert "Stopped after 3 failed searches: 0 rows were not searched." in result.out


def test_a_failure_after_a_success_does_not_stop_the_run(run):
    result = run(answers={**ALL_FAIL, CC1: [passage("zork --frob")]})
    assert result.code == 0
    assert len(result.search.searched) == 5
    assert "Stopped" not in result.out


def test_a_success_among_the_first_three_does_not_stop_the_run(run):
    result = run(answers={**ALL_FAIL, CC2: []})
    assert result.code == 0
    assert len(result.search.searched) == 5


def test_failed_rows_are_named_under_the_table_with_the_command_to_redo_them(run):
    result = run(answers={CC2: FAIL, CX1: FAIL})
    assert "`--rows CC-02,CX-01`" in result.out


def test_no_failed_row_names_no_rows_to_redo(run):
    assert "--rows" not in run().out


def test_no_row_to_check_searches_nothing(run):
    result = run("--client", "codex", text=LIST.replace("| guess |\n\n## Cursor", "| https://learn.chatgpt.com/docs/quux |\n\n## Cursor"))
    assert result.search.calls == []
    assert result.first.startswith("Rows checked: 0.")
    assert result.code == 0


def test_the_table_has_a_header_and_a_line_a_row(run):
    result = run()
    lines = result.out.splitlines()
    assert lines[1].startswith("Limits: ")
    assert lines[2] == ""
    assert lines[3] == "| Row | Source | Page and section | Verdict |"
    assert lines[4] == "|---|---|---|---|"
    assert [ln.split(" ")[1] for ln in lines[5:10]] == ["CC-01", "CC-02", "CC-03", "CX-01", "CU-01"]


def test_the_limits_line_names_the_three_known_limits(run):
    limits = run().out.splitlines()[1]
    # Words that name Kitden are left out by row_words, so that limit is gone.
    assert "Kitden" not in limits
    assert "rows whose words are long strings cannot reach \"states it\"" in limits
    assert "`mcp.json` in `.mcp.json`" in limits
    assert "a letter, digit, `_` or `-`" in limits


# Waking, product and the pause


def test_wake_then_has_product_come_before_any_search(run):
    result = run()
    assert result.search.calls[:2] == ["wake", "has_product"]
    assert result.code == 0


def test_a_server_without_product_stops_with_exit_3_and_no_search(run):
    result = run(product=False)
    assert result.code == 3
    assert "product" in result.err and "deploy" in result.err
    assert "could not be read" in result.err
    assert result.search.searched == []
    assert result.out == ""


def test_a_server_that_does_not_wake_stops_with_exit_4_and_no_search(run):
    result = run(woke=False)
    assert result.code == 4
    assert "wake" in result.err
    assert result.search.calls == ["wake"]
    assert result.out == ""


def test_the_pause_is_7_seconds_between_searches(run):
    result = run()
    assert result.sleeps == [7, 7, 7, 7]


def test_the_pause_is_also_kept_after_a_failed_search(run):
    result = run(answers={CC1: FAIL})
    assert result.sleeps == [7, 7, 7, 7]


def test_pause_sets_the_pause(run):
    result = run("--pause", "2")
    assert result.sleeps == [2, 2, 2, 2]


def test_one_row_has_no_pause(run):
    assert run("--rows", "CC-01").sleeps == []


@pytest.mark.parametrize("bad", ["-1", "soon"])
def test_a_bad_pause_is_refused(run, bad):
    with pytest.raises(SystemExit) as caught:
        run("--pause", bad)
    assert caught.value.code == 2


# The key


@pytest.mark.parametrize("env", [{}, {"COHERE_API_KEY": ""}])
def test_no_key_says_set_cohere_api_key_and_exits_2(run, env):
    result = run(env=env)
    assert result.code == 2
    assert result.err.strip() == "set COHERE_API_KEY"
    assert result.out == ""
    assert result.search.calls == []
    assert result.pages == []


def test_a_key_a_header_cannot_carry_exits_2_without_showing_it(tmp_path, capsys):
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "clients.md").write_text(LIST)
    bad = "Tq4Wn8 SecretPart9"
    code = main(["--kitden", str(tmp_path)], env={"COHERE_API_KEY": bad},
                sleep=lambda s: None, find_moved=lambda pages: [])
    out, err = capsys.readouterr()
    assert code == 2
    assert "SecretPart9" not in out + err
    assert "COHERE_API_KEY" in err


def test_a_missing_list_exits_2(tmp_path, capsys):
    code = main(["--kitden", str(tmp_path)], env=ENV, make_search=lambda key: FakeSearch(),
                sleep=lambda s: None, find_moved=lambda pages: [])
    assert code == 2
    assert "clients.md" in capsys.readouterr().err


# With the real client and a fake server


def real_run(tmp_path, capsys, search_answers, schema=WITH):
    (tmp_path / "docs").mkdir(exist_ok=True)
    (tmp_path / "docs" / "clients.md").write_text(LIST)
    web = FakeWeb({HEALTH: [(200, {}, b'{"status":"ok"}')],
                   OPENAPI: [json_answer(openapi(schema))],
                   SEARCH: search_answers})
    code = main(["--kitden", str(tmp_path), "--rows", "CC-01"], env=ENV,
                make_search=lambda key: Search(key, opener=make_opener(web), sleep=lambda s: None),
                sleep=lambda s: None, find_moved=lambda pages: [])
    out, err = capsys.readouterr()
    return code, out, err, web


def full_passage(content):
    return {"rank": 1, "title": "Zork", "heading": "Frob", "url": PAGE, "score": 0.9,
            "content": content, "description": "d", "other_sections": []}


def test_the_real_client_states_it_and_sends_the_key_only_in_its_header(tmp_path, capsys):
    code, out, err, web = real_run(tmp_path, capsys, [json_answer(
        {"passages": [full_passage("Run zork --frob.")]})])
    assert code == 0
    assert "| CC-01 " in out and out.count("| states it |") == 1
    assert KEY not in out + err
    [search] = [req for req in web.asked if req.full_url == SEARCH]
    assert search.get_header("X-cohere-api-key") == KEY


def test_the_real_client_finds_a_word_at_character_2500(tmp_path, capsys):
    content = "Some filler words. " * 131 + "Run zork --frob."
    assert content.index("zork") > 2480
    code, out, err, web = real_run(tmp_path, capsys, [json_answer(
        {"passages": [full_passage(content)]})])
    assert "| states it |" in out


def test_the_table_is_printed_before_the_moved_check(tmp_path, capsys):
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "clients.md").write_text(LIST)

    def interrupted(pages):
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        main(["--kitden", str(tmp_path)], env=ENV, make_search=lambda key: FakeSearch(),
             sleep=lambda s: None, find_moved=interrupted)
    out = capsys.readouterr().out
    assert out.startswith("Rows checked: 5.")
    assert "| CU-01 " in out


def test_the_real_client_s_429_is_search_failed(tmp_path, capsys):
    code, out, err, web = real_run(tmp_path, capsys, [(429, {}, b"slow down")])
    assert code == 0
    assert "| search failed |" in out
    assert "no page" not in out
    assert "slow down" not in out + err
    assert KEY not in out + err


def test_the_real_client_s_empty_answer_is_no_page(tmp_path, capsys):
    code, out, err, web = real_run(tmp_path, capsys, [json_answer({"passages": []})])
    assert "| no page |" in out


def test_the_real_server_without_product_exits_3(tmp_path, capsys):
    code, out, err, web = real_run(tmp_path, capsys, [json_answer({"passages": []})],
                                   schema=WITHOUT)
    assert code == 3
    assert not [req for req in web.asked if req.full_url == SEARCH]


# Cleaning what comes from a passage


def test_a_heading_keeps_only_letters_digits_spaces_and_a_few_marks():
    assert clean_heading("Set `x` | <b>y</b> [z](w) *é* 2-a_b.c,d:e(f)/g") == (
        "Set x by/b z(w) é 2-a_b.c,d:e(f)/g")


def test_a_heading_turns_line_breaks_into_spaces_and_drops_hidden_characters():
    assert clean_heading("One\nTwo\tThree\u202eFour\u200b") == "One Two ThreeFour"


def test_a_heading_is_cut_to_80_characters():
    assert len(clean_heading("a" * 200)) == 80


@pytest.mark.parametrize(("row_id", "question", "text"), [
    ("CC-01", CC1, "zork --frob"),  # states it
    ("CC-02", CC2, "gizmos"),  # near
    ("CC-03", CC3, "anything"),  # cannot check
])
def test_the_printed_heading_is_cleaned_and_in_backticks(run, row_id, question, text):
    heading = "Frob `on` | ::error:: <script>" + "x" * 100
    result = run(answers={question: [passage(text, heading=heading)]})
    line = result.line(row_id)
    shown = re.search(r"`, `([^`]*)` \|", line).group(1)
    assert shown == clean_heading(heading)
    assert len(shown) <= 80
    assert "<script>" not in result.out and "`on`" not in result.out


def test_an_empty_heading_shows_the_page_alone(run):
    result = run(answers={CC1: [passage("zork --frob", heading="<>")]})
    assert f"| `{SHOWN}` | states it |" in result.line("CC-01")


@pytest.mark.parametrize("url", [
    "https://example.com/docs/en/zork.md",
    "http://code.claude.com/docs/en/zork.md",
    "https://code.claude.com/blog/zork.md",
    "https://code.claude.com/docs/en/zork.md?x=1",
    "https://code.claude.com/docs/en/zo|rk.md",
    "https://code.claude.com/docs/en/zo`rk.md",
    "https://code.claude.com/docs/en/zo<b>rk.md",
    "javascript:alert(1)",
])
def test_a_passage_whose_address_cannot_be_shown_is_not_used(run, url):
    result = run(answers={CC1: [passage("zork --frob", url=url)]})
    line = result.line("CC-01")
    assert line.endswith("| no page |")
    assert url not in result.out


def test_a_passage_whose_address_cannot_be_shown_leaves_the_others(run):
    result = run(answers={CC1: [passage("zork --frob", url="https://example.com/docs/a.md"),
                                passage("zork --frob")]})
    assert f"`{SHOWN}`" in result.line("CC-01")
    assert "example.com" not in result.out


def test_passage_text_is_never_printed(run):
    secret = "PASSAGE-TEXT-MARKER"
    result = run("--all", answers={
        CC1: [passage(f"zork --frob {secret}")],
        CC2: [passage(f"gizmos {secret}")],
        CC3: [passage(secret)],
        CC4: [passage(f"zork plugin-add {secret}")],
    })
    assert secret not in result.out + result.err


def test_a_passage_of_another_shape_is_not_used(run):
    result = run(answers={CC1: [{"url": PAGE}, "text", {"url": PAGE, "heading": 3, "text": "zork --frob"}]})
    assert result.line("CC-01").endswith("| no page |")


# Row text stays a table


def test_a_bar_in_a_row_is_escaped(run):
    text = LIST.replace("`zork --frob` turns", "`zork --a|b` turns")
    result = run(text=text, answers={"zork --a|b turns the frob on": [passage("zork")]})
    line = result.line("CC-01")
    assert "`zork --a\\|b` turns" in line
    assert "missing `--a\\|b`" in line
    assert len(re.findall(r"(?<!\\)\|", line)) == 5


def test_every_table_line_has_five_bars(run):
    result = run("--all", answers={CC1: [passage("zork --frob", heading="a | b")]})
    for line in result.out.splitlines():
        if line.startswith("| "):
            assert len(re.findall(r"(?<!\\)\|", line)) == 5, line


def test_a_line_break_in_row_text_is_escaped():
    from watch_sources import cell
    assert cell("a|b\nc\rd") == "a\\|b c d"


# Progress and output


def test_progress_is_one_line_a_row_on_stderr(run):
    result = run(answers={CC1: [passage("zork --frob")]})
    lines = [ln for ln in result.err.splitlines() if re.match(r"\[\d+/\d+\] ", ln)]
    assert len(lines) == 5
    assert lines[0] == "[1/5] CC-01: states it"
    assert not any(ln.startswith("[") for ln in result.out.splitlines())


# Pages that moved (Part 3)


def test_moved_lines_are_printed_under_the_table(run):
    records = [
        {"address": "https://cursor.com/docs/a", "client": "cursor", "verdict": "moved",
         "to": "https://cursor.com/docs/b"},
        {"address": "https://cursor.com/docs/c", "client": "cursor", "verdict": "maybe",
         "to": "https://cursor.com/docs/x/c"},
        {"address": "https://cursor.com/docs/d", "client": "cursor", "verdict": "absent",
         "to": ""},
    ]
    result = run(moved=records)
    table_end = max(i for i, ln in enumerate(result.out.splitlines()) if ln.startswith("| "))
    after = "\n".join(result.out.splitlines()[table_end + 1:])
    for record in records:
        _, changed, fix = MOVED_TEXT[record["verdict"]]
        shown = {**record, "address": f"`{record['address']}`", "to": f"`{record['to']}`"}
        assert f"- {changed.format(**shown)} {fix.format(**shown)}" in after
    assert "`https://cursor.com/docs/a` is not in Agent Docs" in after
    assert "redirects to `https://cursor.com/docs/b`." in after


def test_moved_is_asked_for_every_doc_page_of_the_list(run):
    result = run("--client", "codex")
    assert result.pages == [{"https://code.claude.com/docs/en/plugins": "claude-code"}]


def test_no_moved_page_says_so(run):
    assert "Every doc page of the list is in Agent Docs." in run(moved=[]).out


def test_an_unreadable_manifest_prints_one_line_and_the_table_still_prints(run):
    result = run(moved=None, answers={CC1: [passage("zork --frob")]})
    assert result.code == 0
    assert "| CC-01 " in result.line("CC-01")
    assert result.out.rstrip().splitlines()[-1] == (
        "Agent Docs' manifest could not be read: pages that moved were not checked.")


def test_a_moved_address_that_cannot_be_shown_is_left_out(run):
    records = [{"address": "https://cursor.com/docs/a|b", "client": "cursor",
                "verdict": "absent", "to": ""}]
    result = run(moved=records)
    assert "a|b" not in result.out


def test_moved_pages_reads_the_manifest_as_fetch_does(tmp_path, monkeypatch):
    sources = tmp_path / "sources.yml"
    sources.write_text("- id: agent-docs-manifest\n  kind: manifest\n"
                       "  url: https://example.com/manifest.json\n"
                       "- id: other\n  client: codex\n  kind: page\n  url: https://example.com/x\n")
    read = []

    def fake_read(source):
        read.append(source["id"])
        return {"https://cursor.com/docs/a.md"}

    monkeypatch.setattr(watch_sources, "read_manifest", fake_read)
    pages = {"https://cursor.com/docs/a": "cursor", "https://cursor.com/docs/gone": "cursor"}
    records = watch_sources.moved_pages(pages, HOSTS, sources, locate=lambda address: None)
    assert read == ["agent-docs-manifest"]
    assert records == [{"address": "https://cursor.com/docs/gone", "client": "cursor",
                        "verdict": "absent", "to": ""}]


def test_moved_pages_gives_none_when_the_manifest_cannot_be_read(tmp_path, monkeypatch, capsys):
    sources = tmp_path / "sources.yml"
    sources.write_text("- id: agent-docs-manifest\n  kind: manifest\n"
                       "  url: https://example.com/manifest.json\n")

    def fail(source):
        raise ValueError("too big")

    monkeypatch.setattr(watch_sources, "read_manifest", fail)
    assert watch_sources.moved_pages({}, HOSTS, sources, locate=lambda a: None) is None
    assert "cannot read agent-docs-manifest: ValueError" in capsys.readouterr().err


def test_moved_pages_gives_none_without_a_manifest_source(tmp_path):
    sources = tmp_path / "sources.yml"
    sources.write_text("- id: other\n  client: codex\n  kind: page\n  url: https://example.com/x\n")
    assert watch_sources.moved_pages({}, HOSTS, sources, locate=lambda a: None) is None


def test_the_default_sources_file_has_the_manifest():
    sources = watch_sources.load_sources(watch_sources.SOURCES)
    assert [s["id"] for s in sources if s["kind"] == "manifest"] == ["agent-docs-manifest"]


def test_no_private_name_is_imported_from_another_module():
    import ast
    tree = ast.parse(Path(watch_sources.__file__).read_text())
    names = [a.name for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
             for a in node.names]
    assert not [n for n in names if n.startswith("_")]
