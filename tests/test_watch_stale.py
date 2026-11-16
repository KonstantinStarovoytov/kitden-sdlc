# ruff: noqa: E501
import re
from pathlib import Path

import pytest

from post_findings import WORD_JOINER
from watch_fetch import _moved_item
from watch_pages import Section
from watch_route import TEXT_MAX, client_name
from watch_stale import (
    ADDRESS,
    LABELS_SHOWN,
    Fact,
    list_facts,
    page_hash,
    rule_facts,
    stale,
)

FIXTURE = Path(__file__).parent / "fixtures" / "platform-rules.md"
REAL_RULES = Path(__file__).parent.parent / "docs" / "platform-rules.md"

LIST = """# What Kitden relies on in each client

A date in brackets is when that fact was last checked.

## Claude Code

| What | Kind | Files | Seen in | macOS and Linux | Source |
|---|---|---|---|---|---|
| `demo add <name>` takes the entry as an argument (2026-10-01) | command | `src/a.py` | adding a server (2026-10-20) | same | https://docs.example.com/en/servers |
| `demo remove <name>` | command | `src/a.py` | removing a server | same | https://docs.example.com/en/servers#remove |
| Keys in `~/.demo.json` (2026-10-05) | key | `src/a.py` | scan | same | install |
| `demo list` prints one line a server (2026-09-01) | command | `src/a.py` | scan | same | https://docs.example.com/en/list. |
| `demo show` (2026-13-01) | command | `src/a.py` | scan | same | https://docs.example.com/en/show |
| `demo run` prints its plan (2026-11-15, version 1.4, macOS) | command | `src/a.py` | scan | same | https://docs.example.com/en/run |
| Hooks in `~/.demo/hooks.json` (2026-11-09); the client's own code reads `hooks` (2026-11-15, Linux) | key | `src/a.py` | scan (checked 2026-11-12 on the page) | same | https://docs.example.com/en/hooks |

## Codex

| What | Kind | Files | Seen in | macOS and Linux | Source |
|---|---|---|---|---|---|
| Servers under `[servers]` in `config.toml` | key | `src/b.py` | scan (2026-10-12) | same | https://docs.example.org/config#servers |
| Skills in `~/.demo/skills` | path | `src/b.py` | scan | same | guess |
"""

SUBMIT = "https://shelf.example.com/docs/submit"
ONE = "Shelf one (plugins/demo)"
INDEX = "Index (https://index.example.net/servers/demo)"
FIXTURE_FACTS = [
    Fact(SUBMIT, "2026-11-10", f"{ONE}, line 9", "Store rules"),
    Fact("https://shelf.example.com/docs/checklist", "2026-11-09", f"{ONE}, line 14", "Store rules"),
    Fact(SUBMIT, "2026-11-09", f"{ONE}, line 14", "Store rules"),
    Fact("https://docs.example.org/en/reference", "2026-11-09", f"{ONE}, line 14", "Store rules"),
    Fact("https://schemas.example.net/2026-01-01/demo.schema.json", "2026-11-07", f"{INDEX}, line 27", "Store rules"),
    Fact("https://docs.example.org/guide", "2026-11-06", f"{INDEX}, line 32", "Store rules"),
    Fact("https://docs.example.org/word-rules", "2026-11-06", f"{INDEX}, line 32", "Store rules"),
    Fact("https://docs.example.org/limits", "2026-11-05", f"{INDEX}, line 39", "Store rules"),
    Fact("https://docs.example.org/sizes", "2026-11-05", f"{INDEX}, line 39", "Store rules"),
]


def fact(address="https://docs.example.com/a", checked="2026-11-10", label="CC-01",
         client="claude-code"):
    return Fact(address, checked, label, client)


# ADDRESS


@pytest.mark.parametrize(("text", "found"), [
    ("Source: <https://example.com/a>.", "https://example.com/a"),
    ("the [Guide](https://example.com/b) and", "https://example.com/b"),
    ("[x](https://example.com/c]", "https://example.com/c"),
])
def test_address_takes_no_bracket(text, found):
    assert ADDRESS.search(text).group() == found


# list_facts


def test_list_facts_reads_rows_with_an_address_and_a_date():
    facts, undated = list_facts(LIST)
    assert facts == [
        Fact("https://docs.example.com/en/servers", "2026-10-20", "CC-01", "claude-code"),
        Fact("https://docs.example.com/en/list", "2026-09-01", "CC-04", "claude-code"),
        Fact("https://docs.example.com/en/hooks", "2026-11-12", "CC-07", "claude-code"),
        Fact("https://docs.example.org/config", "2026-10-12", "CX-01", "codex"),
    ]
    # CC-02 has an address and no date; CC-05's only date is not a day; CC-06's only date
    # was seen on an install. CC-03 and CX-02 have no address, so they are not counted.
    assert undated == 3


def test_a_row_with_two_dates_uses_the_latest():
    facts, _ = list_facts(LIST)
    assert facts[0].checked == "2026-10-20"  # What says 2026-10-01, Seen in 2026-10-20
    later = LIST.replace("adding a server (2026-10-20)", "adding a server (2026-09-20)")
    assert list_facts(later)[0][0].checked == "2026-10-01"


def test_a_date_in_seen_in_counts():
    facts, _ = list_facts(LIST)
    assert Fact("https://docs.example.org/config", "2026-10-12", "CX-01", "codex") in facts


def row(what, seen_in="scan"):
    return ("## Cursor\n\n| What | Kind | Files | Seen in | macOS and Linux | Source |\n"
            "|---|---|---|---|---|---|\n"
            f"| {what} | key | `src/c.py` | {seen_in} | same | https://docs.example.com/c |\n")


@pytest.mark.parametrize("what", [
    "Rules in `.demo/rules` (2026-11-01)",
    "Rules in `.demo/rules` (checked 2026-11-01)",
    "Rules in `.demo/rules` (Checked 2026-11-01 against the page)",
    "Rules in `.demo/rules` (checked 2026-11-01, by hand)",
])
def test_a_date_alone_or_after_checked_is_a_check(what):
    assert list_facts(row(what)) == (
        [Fact("https://docs.example.com/c", "2026-11-01", "CU-01", "cursor")], 0)


@pytest.mark.parametrize("what", [
    "Rules in `.demo/rules` (2026-11-01, version 3.2, macOS)",
    "Rules in `.demo/rules` (2026-11-01, Linux)",
    "Rules in `.demo/rules` (2026-11-01 in the client's own code)",
    "Rules in `.demo/rules` ( 2026-11-01)",
    "Rules in `.demo/rules` (2026-11-01",
    "Rules in `.demo/rules` (seen 2026-11-01)",
    "Rules in `.demo/rules` (checked: 2026-11-01)",
])
def test_a_date_with_more_in_its_bracket_is_no_check(what):
    assert list_facts(row(what)) == ([], 1)
    assert list_facts(row("Rules", seen_in=what)) == ([], 1)


def test_a_date_seen_in_the_code_does_not_make_the_page_look_fresh():
    # The shape of CU-13: two checks of the docs, then a later date for the client's code.
    text = row("Skills in `.demo/skills` (2026-11-14); a switch (2026-11-09). Its own code "
               "drops them (2026-11-15, version 3.29.9, macOS)")
    facts, _ = list_facts(text)
    assert [f.checked for f in facts] == ["2026-11-14"]
    (item,) = stale(facts, {"https://docs.example.com/c": "2026-11-15"})
    assert item["changed"].endswith(": CU-01.")


def test_a_date_after_checked_in_seen_in_counts():
    facts, _ = list_facts(LIST)
    # CC-07: "(2026-11-09)" in What, "(checked 2026-11-12 on the page)" in Seen in, and a
    # later "(2026-11-15, Linux)" that does not count.
    assert Fact("https://docs.example.com/en/hooks", "2026-11-12", "CC-07", "claude-code") in facts


def test_a_date_in_another_cell_does_not_count():
    text = LIST.replace("| `src/b.py` | scan (2026-10-12) | same |",
                        "| `src/b.py` | scan | same (2026-10-12) |")
    facts, undated = list_facts(text)
    assert [f.label for f in facts] == ["CC-01", "CC-04", "CC-07"]
    assert undated == 4


def test_list_facts_of_no_list():
    assert list_facts("") == ([], 0)
    assert list_facts("# Nothing here\n\nJust words (2026-11-01).\n") == ([], 0)


# rule_facts


def test_rule_facts_reads_the_fixture():
    facts, skipped = rule_facts(FIXTURE.read_text(encoding="utf-8"))
    assert facts == FIXTURE_FACTS
    # The policy's "checked 2026-11-08", the cleaner's mark with no `Checked:`, and that
    # mark's own "checked 2026-10-28".
    assert skipped == 3


def test_one_address_in_angle_brackets_on_the_marks_line():
    facts, _ = rule_facts(FIXTURE.read_text(encoding="utf-8"))
    assert [f for f in facts if f.label.endswith("line 9")] == [FIXTURE_FACTS[0]]


def test_three_addresses_over_three_lines_under_sources():
    facts, _ = rule_facts(FIXTURE.read_text(encoding="utf-8"))
    assert [f.address for f in facts if f.label.endswith("line 14")] == [
        "https://shelf.example.com/docs/checklist", SUBMIT,
        "https://docs.example.org/en/reference"]


def test_a_dash_source_whose_dash_checked_is_three_lines_on():
    facts, _ = rule_facts(FIXTURE.read_text(encoding="utf-8"))
    assert [f for f in facts if f.label.endswith("line 27")] == [FIXTURE_FACTS[4]]


def test_an_address_in_a_markdown_link_is_read_without_its_bracket():
    facts, _ = rule_facts(FIXTURE.read_text(encoding="utf-8"))
    assert [f.address for f in facts if f.label.endswith("line 32")] == [
        "https://docs.example.org/guide", "https://docs.example.org/word-rules"]


def test_an_address_followed_by_a_full_stop_or_a_comma():
    facts, _ = rule_facts(FIXTURE.read_text(encoding="utf-8"))
    assert [f.address for f in facts if f.label.endswith("line 39")] == [
        "https://docs.example.org/limits", "https://docs.example.org/sizes"]


def test_a_mark_whose_only_date_is_in_a_sentence_is_skipped_and_counted():
    text = FIXTURE.read_text(encoding="utf-8")
    facts, _ = rule_facts(text)
    assert not [f for f in facts if "cleaner" in f.address]
    alone = "\n".join(text.split("\n")[39:])  # the "Pictures" rule and what follows
    assert alone.startswith("- **Pictures.**")
    assert rule_facts(alone) == ([], 2)


def test_a_sentence_date_outside_a_mark_is_counted_and_its_address_is_no_fact():
    text = ("## Shelf\n\nPolicy ([Policy](https://help.example.com/policy),\n"
            "checked 2026-11-08):\n\n- Be kind.\n")
    assert rule_facts(text) == ([], 1)
    assert rule_facts("Read on 2026-11-08 (Checked 2026-11-08).\n") == ([], 1)


def test_a_block_ends_at_an_empty_line():
    text = "## Shelf\n\nSource: <https://example.com/a>.\n\nChecked: 2026-11-01.\n"
    assert rule_facts(text) == ([], 1)


def test_a_block_is_at_most_six_lines():
    six = "Source: <https://example.com/a>\n" + "more\n" * 4 + "Checked: 2026-11-01.\n"
    assert rule_facts(six) == ([Fact("https://example.com/a", "2026-11-01", "line 1",
                                     "Store rules")], 0)
    seven = "Source: <https://example.com/a>\n" + "more\n" * 5 + "Checked: 2026-11-01.\n"
    assert rule_facts(seven) == ([], 1)


def test_a_block_ends_at_the_next_mark():
    # The first rule's date is not known: it is not taken from the second rule.
    text = ("- **One.** Source: words.\n"
            "  Source: <https://example.com/a>.\n"
            "  Source: <https://example.com/b>. Checked: 2026-11-01.\n")
    assert rule_facts(text) == ([Fact("https://example.com/b", "2026-11-01", "line 3",
                                      "Store rules")], 1)


def test_a_block_ends_at_a_heading():
    text = "Source: <https://example.com/a>\n## Next (<https://example.com/b>)\nChecked: 2026-11-01.\n"
    assert rule_facts(text) == ([], 1)


def test_a_mark_with_a_date_and_no_address_is_counted():
    text = "- Source: `demo audit` runs the check.\n- Checked: 2026-11-01.\n"
    assert rule_facts(text) == ([], 1)


@pytest.mark.parametrize("checked", ["Checked: 2026-13-01.", "Checked: 2026-1-01.",
                                     "Checked: soon."])
def test_a_mark_with_a_date_that_is_not_a_day_is_counted(checked):
    assert rule_facts(f"Source: <https://example.com/a>. {checked}\n") == ([], 1)


@pytest.mark.parametrize("line", ["Source: <https://example.com/a>. Checked: 2026-11-01.",
                                  "  Source: <https://example.com/a>. Checked: 2026-11-01.",
                                  "- Source: <https://example.com/a>. Checked: 2026-11-01.",
                                  "  - Sources: <https://example.com/a>. Checked: 2026-11-01."])
def test_a_mark_after_its_indent_and_a_dash(line):
    assert len(rule_facts(line)[0]) == 1


@pytest.mark.parametrize("line", ["The Source: <https://example.com/a>. Checked: 2026-11-01.",
                                  "* Source: <https://example.com/a>. Checked: 2026-11-01.",
                                  "source: <https://example.com/a>. Checked: 2026-11-01."])
def test_not_a_mark(line):
    assert rule_facts(line) == ([], 0)


def test_an_address_is_read_once_in_a_block_and_without_its_fragment():
    text = "Source: <https://example.com/a#one> and <https://example.com/a#two>. Checked: 2026-11-01.\n"
    assert rule_facts(text)[0] == [Fact("https://example.com/a", "2026-11-01", "line 1",
                                        "Store rules")]


def test_the_heading_is_cleaned_in_the_label():
    text = "## Shelf [x](https://evil.example) @owner `code`\n\nSource: <https://example.com/a>. Checked: 2026-11-01.\n"
    (only,), _ = rule_facts(text)
    assert only.label == "Shelf x(https://evil.example) owner code, line 3"
    long = "## " + "Word " * 40 + "\n" + "Source: <https://example.com/a>. Checked: 2026-11-01.\n"
    (only,), _ = rule_facts(long)
    assert only.label == ("Word " * 16).strip() + ", line 2"


def test_lines_are_counted_as_git_counts_them():
    text = "x y\nSource: <https://example.com/a>. Checked: 2026-11-01.\n"
    assert rule_facts(text)[0][0].label == "line 2"


# The real file


def marks_in(text):
    return [n for n, line in enumerate(text.split("\n"), start=1)
            if re.match(r"\s*(?:- )?Sources?:", line)]


def test_the_real_rules_file():
    text = REAL_RULES.read_text(encoding="utf-8")
    facts, skipped = rule_facts(text)
    assert facts
    read = {int(f.label.rsplit(", line ", 1)[1]) for f in facts}
    in_sentences = len(re.findall(r"\bchecked\s+[0-9]{4}-[0-9]{2}-[0-9]{2}", text, re.IGNORECASE))
    # Every mark is read, or counted among the skipped.
    assert read <= set(marks_in(text))
    assert len(read) + skipped - in_sentences == len(marks_in(text))
    for f in facts:
        assert not set("<>()[]#") & set(f.address), f.address
        assert f.address.startswith("https://") and len(f.address) > len("https://")


# page_hash


def test_page_hash_reads_the_keys_and_hashes_in_order():
    a, b = Section("A", "text a", "1" * 64), Section("B", "text b", "2" * 64)
    assert re.fullmatch(r"[0-9a-f]{64}", page_hash([a, b]))
    assert page_hash([a, b]) == page_hash([Section("A", "other", "1" * 64), b])
    assert page_hash([a, b]) != page_hash([b, a])
    assert page_hash([a]) != page_hash([Section("B", "text a", "1" * 64)])
    assert page_hash([a]) != page_hash([Section("A", "text a", "3" * 64)])
    assert page_hash([]) != page_hash([Section("", "", "")])


def test_page_hash_keeps_key_and_hash_apart():
    assert page_hash([Section("ab", "", "c")]) != page_hash([Section("a", "", "bc")])
    assert page_hash([Section("a", "", "b"), Section("c", "", "d")]) != \
        page_hash([Section("a", "", "bc"), Section("", "", "d")])


# stale


def test_a_fact_checked_on_the_change_day_is_not_stale():
    assert stale([fact(checked="2026-11-10")], {"https://docs.example.com/a": "2026-11-10"}) == []


def test_a_fact_checked_the_day_before_is_stale():
    (item,) = stale([fact(checked="2026-11-09")], {"https://docs.example.com/a": "2026-11-10"})
    assert item["changed"] == "The page changed on 2026-11-10, after this fact was checked: CC-01."
    assert item["title"] == "https://docs.example.com/a changed after its facts were checked"
    assert item["url"] == "https://docs.example.com/a"
    assert item["client"] == "claude-code"
    assert client_name(item) == "Claude Code"


def test_the_item_has_the_keys_of_a_moved_item():
    (item,) = stale([fact(checked="2026-11-09")], {"https://docs.example.com/a": "2026-11-10"})
    moved = _moved_item({"verdict": "moved", "address": "https://x", "to": "https://y",
                         "client": "codex"})
    assert set(item) == set(moved)
    assert (item["effect"], item["severity"], item["sure"]) == ("outdated", "minor", True)
    assert item["fix"] and item["why"]
    assert (item["user_gets"], item["systems"], item["row"], item["files"], item["version"]) == \
        ("not checked", "", "", [], "")


def test_a_page_not_in_changed_is_not_stale():
    assert stale([fact(checked="2026-01-01")], {}) == []
    assert stale([fact(checked="2026-01-01")], {"https://docs.example.com/b": "2026-11-10"}) == []


def test_two_rows_of_one_page_make_one_item_naming_both():
    facts, _ = list_facts(LIST.replace("https://docs.example.com/en/list.",
                                       "https://docs.example.com/en/servers"))
    (item,) = stale(facts, {"https://docs.example.com/en/servers": "2026-11-01"})
    assert item["changed"] == ("The page changed on 2026-11-01, after these 2 facts were "
                               "checked: CC-01; CC-04.")


def test_only_the_facts_checked_before_the_day_are_named():
    facts = [fact(label="CC-01", checked="2026-11-01"), fact(label="CC-02", checked="2026-11-12")]
    (item,) = stale(facts, {"https://docs.example.com/a": "2026-11-05"})
    assert item["changed"].endswith("after this fact was checked: CC-01.")


def test_an_address_is_compared_without_its_fragment():
    facts, _ = list_facts(LIST)
    (item,) = stale(facts, {"https://docs.example.org/config": "2026-11-01"})
    assert item["changed"].endswith(": CX-01.")
    assert item["url"] == "https://docs.example.org/config"


def test_the_same_label_twice_is_named_once():
    facts = [fact("https://e.example/a", label="CC-01"), fact("https://e.example/a", label="CC-01")]
    (item,) = stale(facts, {"https://e.example/a": "2026-11-12"})
    assert item["changed"].endswith("after this fact was checked: CC-01.")


def test_two_rules_of_one_page_make_one_item():
    facts, _ = rule_facts(FIXTURE.read_text(encoding="utf-8"))
    items = stale(facts, {SUBMIT: "2026-11-11"})
    assert [i["changed"] for i in items] == [
        f"The page changed on 2026-11-11, after these 2 facts were checked: {ONE}, line 9; "
        f"{ONE}, line 14."]
    assert items[0]["client"] == "Store rules"
    assert client_name(items[0]) == "Store rules"


def test_one_item_a_page_in_the_order_of_the_facts():
    facts = [fact("https://e.example/b", label="CC-01"), fact("https://e.example/a", label="CC-02"),
             fact("https://e.example/b", label="CC-03")]
    items = stale(facts, {"https://e.example/a": "2026-11-12", "https://e.example/b": "2026-11-12"})
    assert [i["url"] for i in items] == ["https://e.example/b", "https://e.example/a"]


def test_at_most_ten_labels_and_how_many_more():
    facts = [fact(label=f"CC-{n:02d}", checked="2026-11-01") for n in range(1, 15)]
    (item,) = stale(facts, {"https://docs.example.com/a": "2026-11-02"})
    shown = "; ".join(f"CC-{n:02d}" for n in range(1, LABELS_SHOWN + 1))
    assert item["changed"] == ("The page changed on 2026-11-02, after these 14 facts were "
                               f"checked: {shown} and 4 more.")


def test_text_is_cut_by_quiet():
    long = "Shelf " + "x" * 74 + ", line 100"
    facts = [fact("https://docs.example.com/@team", label=f"{long}{n}", checked="2026-11-01")
             for n in range(12)]
    (item,) = stale(facts, {"https://docs.example.com/@team": "2026-11-02"})
    assert len(item["changed"]) == TEXT_MAX
    assert item["changed"].startswith("The page changed on 2026-11-02, after these 12 facts")
    assert item["title"].startswith(f"https://docs.example.com/@{WORD_JOINER}team changed")
    assert item["url"] == "https://docs.example.com/@team"


@pytest.mark.parametrize(("length", "name"), [
    (43, "aaaaaa/last-part-x"),
    (67, "a" * 30 + "/last-part-x"),
    (68, "last-part-x"),
    (120, "last-part-x"),
    (500, "last-part-x"),
])
def test_the_title_stays_under_80_for_a_long_address(length, name):
    address = "https://docs.example.com/" + "a" * (length - 25 - 12) + "/last-part-x"
    assert len(address) == length
    (item,) = stale([fact(address, checked="2026-11-01")], {address: "2026-11-02"})
    assert len(item["title"]) < 80
    assert item["title"] == f"{name} changed after its facts were checked"
    assert item["url"] == address


def test_the_title_uses_the_longest_tail_that_fits():
    address = "https://docs.example.com/" + "a" * 40 + "/plugins/install"
    (item,) = stale([fact(address, checked="2026-11-01")], {address: "2026-11-02"})
    assert item["title"] == "plugins/install changed after its facts were checked"
    address = "https://code.example.com/docs/en/plugins/install"  # 48 characters
    (item,) = stale([fact(address, checked="2026-11-01")], {address: "2026-11-02"})
    assert item["title"] == "docs/en/plugins/install changed after its facts were checked"


def test_two_long_addresses_with_one_last_part_get_two_titles():
    one = "https://learn.example.com/docs/config-file/config-reference"
    two = "https://learn.example.com/docs/other-file/config-reference"
    items = stale([fact(one, checked="2026-11-01"), fact(two, checked="2026-11-01")],
                  {one: "2026-11-02", two: "2026-11-02"})
    assert [i["title"] for i in items] == [
        "docs/config-file/config-reference changed after its facts were checked",
        "docs/other-file/config-reference changed after its facts were checked"]


def test_an_address_with_no_path_uses_its_host():
    address = "https://" + "h" * 30 + ".example.com/"
    (item,) = stale([fact(address, checked="2026-11-01")], {address: "2026-11-02"})
    assert item["title"] == "h" * 30 + ".example.com changed after its facts were checked"
    address = "https://" + "h" * 60 + ".example.com"
    (item,) = stale([fact(address, checked="2026-11-01")], {address: "2026-11-02"})
    assert item["title"] == "h" * 42 + " changed after its facts were checked"


def test_a_title_that_fits_keeps_the_whole_address():
    address = "https://docs.example.com/" + "a" * 17  # 42 characters
    (item,) = stale([fact(address, checked="2026-11-01")], {address: "2026-11-02"})
    assert item["title"] == f"{address} changed after its facts were checked"
    assert len(item["title"]) == 79


def test_a_long_last_part_is_cut():
    address = "https://docs.example.com/" + "b" * 475
    (item,) = stale([fact(address, checked="2026-11-01")], {address: "2026-11-02"})
    assert item["title"] == "b" * 42 + " changed after its facts were checked"
    address = "https://docs.example.com/x/" + "@team" + "c" * 60 + "/"
    (item,) = stale([fact(address, checked="2026-11-01")], {address: "2026-11-02"})
    assert len(item["title"]) < 80
    assert item["title"].startswith("teamccc")


@pytest.mark.parametrize("address", ["https://docs.example.com/a`b", "https://docs.example.com/é",
                                     'https://docs.example.com/a"b', "https://docs.example.com/a|b"])
def test_an_address_that_cannot_be_shown_has_no_url(address):
    (item,) = stale([fact(address, checked="2026-11-01")], {address: "2026-11-02"})
    assert item["url"] == ""
    assert not set("`\"|") & set(item["title"])
    assert item["title"].endswith(" changed after its facts were checked")


@pytest.mark.parametrize("day", ["", "yesterday", "2026-13-01", "2026-11-1", "20261102",
                                 "2026-W45-1", " 2026-11-02", None, 20261102, ["2026-11-02"]])
def test_a_bad_day_in_changed_is_skipped(day):
    facts = [fact("https://e.example/a", checked="2026-11-01"),
             fact("https://e.example/b", checked="2026-11-01")]
    items = stale(facts, {"https://e.example/a": day, "https://e.example/b": "2026-11-02"})
    assert [i["url"] for i in items] == ["https://e.example/b"]


def test_a_fact_with_a_bad_checked_day_is_not_stale():
    assert stale([fact(checked="")], {"https://docs.example.com/a": "2026-11-02"}) == []


def test_stale_of_nothing():
    assert stale([], {}) == []
