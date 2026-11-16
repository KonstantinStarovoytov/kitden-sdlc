import contextlib
import copy
import email.message
import json
from datetime import date
from pathlib import Path

import pytest

import watch_feed
import watch_pages
from doc_address import load_hosts
from watch_feed import (
    FEED_MAX,
    KEEP_DAYS,
    PRODUCTS,
    STALE_DAYS,
    TOPIC_WORDS,
    Entry,
    kept_sections,
    load_feed,
    read_feed,
    wanted,
)
from watch_fetch import read_or_none
from watch_list import terms
from watch_pages import Section

HOSTS = load_hosts()
TODAY = date(2026, 11, 16)
FIXTURE = Path("tests/fixtures/feed.json")
BODY = FIXTURE.read_text(encoding="utf-8")
SOURCE = {"id": "agent-docs-feed", "kind": "feed",
          "url": "https://raw.githubusercontent.com/o/agent-docs/main/feed.json"}

NEW = "https://code.claude.com/docs/en/example-new.md"
SAME = "https://code.claude.com/docs/en/example-same.md"
CHANGED = "https://developers.openai.com/codex/example-changed.md"
GONE = "https://cursor.com/docs/example-gone.md"
MCP = "https://modelcontextprotocol.io/docs/example-new.md"
RULES = "https://cursor.com/docs/example-rules.md"


def feed(**changes) -> dict:
    data = json.loads(BODY)
    data.update(changes)
    return data


def one_day(**lists) -> str:
    day = {"day": "2026-11-15", "added": [], "changed": [], "removed": []}
    day.update(lists)
    return json.dumps({"checked": "2026-11-15", "days": [day]})


def entry(day, kind, url, product="claude-code", sections=()) -> Entry:
    return Entry(day, kind, url, product, tuple(sections))


# --- load_feed --------------------------------------------------------------------------


def test_constants():
    assert FEED_MAX == 1024 * 1024
    assert (STALE_DAYS, KEEP_DAYS) == (3, 14)
    assert PRODUCTS == ("claude-code", "codex", "cursor")
    assert TOPIC_WORDS == ("mcp", "skill", "plugin", "hook", "marketplace", "agents.md",
                           "claude.md", ".cursor/rules", "instruction file")


def test_load_feed_gives_every_entry_oldest_day_first():
    assert load_feed(BODY, TODAY) == [
        entry("2026-11-14", "added", MCP, "mcp"),
        entry("2026-11-14", "changed", RULES, "cursor", ["Planted heading three"]),
        entry("2026-11-15", "added", NEW),
        entry("2026-11-15", "changed", SAME),
        entry("2026-11-15", "changed", CHANGED, "codex",
              ["Planted heading one", "Planted heading two"]),
        entry("2026-11-15", "removed", GONE, "cursor"),
    ]


def test_an_entry_keeps_its_sections_as_a_tuple():
    [*_, changed, _] = load_feed(BODY, TODAY)
    assert changed.sections == ("Planted heading one", "Planted heading two")


def test_a_feed_with_no_days_is_read_as_empty():
    assert load_feed(json.dumps(feed(days=[])), TODAY) == []


@pytest.mark.parametrize("checked", ["2026-11-13", "2026-11-16", "2026-11-17"])
def test_checked_up_to_three_days_old_or_a_day_ahead_is_read(checked):
    assert load_feed(json.dumps(feed(checked=checked, days=[])), TODAY) == []


@pytest.mark.parametrize("checked", ["2026-11-12", "2026-01-01", "2026-11-18", "2099-01-01"])
def test_checked_four_days_old_or_more_than_a_day_ahead_is_refused(checked):
    with pytest.raises(ValueError, match="stale|still to come"):
        load_feed(json.dumps(feed(checked=checked, days=[])), TODAY)


@pytest.mark.parametrize("checked", [
    "2026-13-01", "2026-02-30", "20261115", "2026-11-15T00:00", "2026-W46-7", " 2026-11-15",
    "2026-11-15\n", "", "yesterday", 20261115, 2026.11, None, True, [], {}, ["2026-11-15"],
])
def test_checked_that_is_not_a_date_is_refused(checked):
    with pytest.raises(ValueError):
        load_feed(json.dumps(feed(checked=checked)), TODAY)


@pytest.mark.parametrize("body", [
    "", " ", "{", "not json", "<html><body>Rate limited</body></html>", "\x00",
    '{"checked": "2026-11-15", "days": []',  # cut short
    "[]", "null", "1", '"feed"', "true", "1e999",
    '{"checked": 1' + "0" * 5000 + ', "days": []}',  # an integer Python will not read
    "[" * 100_000 + "]" * 100_000,  # deeper than Python's recursion limit
    '{"checked": "2026-11-15", "days": ' + "[" * 100_000 + "]" * 100_000 + "}",
    '{"days": []}', '{"checked": "2026-11-15"}',
])
def test_a_body_that_is_not_a_feed_object_is_refused(body):
    with pytest.raises(ValueError):
        load_feed(body, TODAY)


def test_a_body_that_is_not_text_is_refused():
    with pytest.raises(ValueError):
        load_feed(BODY.encode(), TODAY)


@pytest.mark.parametrize("days", [{}, "2026-11-15", 1, None, {"2026-11-15": []}])
def test_days_that_are_not_a_list_are_refused(days):
    with pytest.raises(ValueError):
        load_feed(json.dumps(feed(days=days)), TODAY)


@pytest.mark.parametrize("day", [
    None, 1, "2026-11-15", [], ["2026-11-15"],
    {"day": "yesterday", "added": [], "changed": [], "removed": []},
    {"day": "2026-02-30", "added": [], "changed": [], "removed": []},
    {"day": "20261115", "added": [], "changed": [], "removed": []},
    {"day": 20261115, "added": [], "changed": [], "removed": []},
    {"added": [], "changed": [], "removed": []},
    {"day": "2026-11-15", "changed": [], "removed": []},
    {"day": "2026-11-15", "added": {}, "changed": [], "removed": []},
    {"day": "2026-11-15", "added": [], "changed": "x", "removed": []},
    {"day": "2026-11-15", "added": [], "changed": [], "removed": None},
])
def test_a_day_of_another_shape_is_refused(day):
    with pytest.raises(ValueError):
        load_feed(json.dumps(feed(days=[day])), TODAY)


def test_a_day_after_checked_is_refused():
    # Taken, a day ahead would make the watcher skip the real days up to it.
    day = {"day": "2026-11-16", "added": [], "changed": [], "removed": []}
    with pytest.raises(ValueError):
        load_feed(json.dumps(feed(days=[day])), TODAY)


def test_the_same_day_twice_is_refused():
    data = json.loads(BODY)
    data["days"].append(copy.deepcopy(data["days"][0]))
    with pytest.raises(ValueError):
        load_feed(json.dumps(data), TODAY)


def test_entries_of_another_shape_are_skipped_and_counted(capsys):
    body = one_day(
        added=[
            {"url": NEW, "product": "claude-code"},
            None, "https://code.claude.com/docs/en/x.md", [NEW, "claude-code"],
            {"url": 1, "product": "claude-code"},
            {"url": NEW, "product": None},
            {"product": "claude-code"},
            {"url": NEW},
        ],
        changed=[
            {"url": CHANGED, "product": "codex", "new_sections": ["Planted heading one"]},
            {"url": CHANGED, "product": "codex"},
            {"url": CHANGED, "product": "codex", "new_sections": "Planted heading one"},
            {"url": CHANGED, "product": "codex", "new_sections": [1]},
            {"url": CHANGED, "product": "codex", "new_sections": ["ok", None]},
            {"url": CHANGED, "product": "codex", "new_sections": [["nested"]]},
            {"url": CHANGED, "product": "codex", "new_sections": {"a": "b"}},
        ],
        removed=[{"url": GONE, "product": "cursor"}, 7],
    )
    assert load_feed(body, TODAY) == [
        entry("2026-11-15", "added", NEW),
        entry("2026-11-15", "changed", CHANGED, "codex", ["Planted heading one"]),
        entry("2026-11-15", "removed", GONE, "cursor"),
    ]
    assert capsys.readouterr().err == "feed: 14 entries of another shape skipped\n"


def test_a_feed_with_no_odd_entry_prints_nothing(capsys):
    load_feed(BODY, TODAY)
    assert capsys.readouterr().err == ""


def test_extra_keys_are_ignored():
    data = json.loads(BODY)
    data["note"] = "x"
    data["days"][0]["extra"] = 1
    data["days"][0]["added"][0]["title"] = "A title"
    assert load_feed(json.dumps(data), TODAY) == load_feed(BODY, TODAY)


def test_the_skip_message_holds_no_feed_text(capsys):
    body = one_day(added=[{"url": "@owner [x](https://evil)", "product": ["::error::x"]}])
    assert load_feed(body, TODAY) == []
    err = capsys.readouterr().err
    assert "evil" not in err and "owner" not in err and "::" not in err


def test_an_odd_heading_is_kept_for_comparing_and_never_printed(capsys):
    odd = ["\ud800", "\x1b[31mred", "::error::x", "a" * 5000, ""]
    body = one_day(changed=[{"url": CHANGED, "product": "codex", "new_sections": odd}])
    [got] = load_feed(body, TODAY)
    assert got.sections == tuple(odd)
    assert capsys.readouterr() == ("", "")


ODD_VALUES = [None, True, 0, -1, 1.5, 1e308, "", "x", "2026-11-15", [], [None], {}, {"a": 1}]


def _places(value, path=()):
    """Every place in a JSON value, as the path of keys and indexes to it."""
    yield path
    if isinstance(value, dict):
        for key, inner in value.items():
            yield from _places(inner, (*path, key))
    elif isinstance(value, list):
        for i, inner in enumerate(value):
            yield from _places(inner, (*path, i))


def _put(data, path, value):
    if not path:
        return value
    inner = data
    for step in path[:-1]:
        inner = inner[step]
    inner[path[-1]] = value
    return data


def _drop(data, path):
    inner = data
    for step in path[:-1]:
        inner = inner[step]
    del inner[path[-1]]
    return data


def test_any_one_wrong_value_anywhere_gives_a_list_or_a_value_error():
    tried = 0
    for path in _places(json.loads(BODY)):
        bodies = [json.dumps(_put(json.loads(BODY), path, v)) for v in ODD_VALUES]
        if path:
            bodies.append(json.dumps(_drop(json.loads(BODY), path)))
        for body in bodies:
            tried += 1
            with contextlib.suppress(ValueError):
                assert isinstance(load_feed(body, TODAY), list)
    assert tried > 400


def test_the_feed_cut_anywhere_gives_a_value_error():
    for end in range(len(BODY.rstrip())):
        with pytest.raises(ValueError):
            load_feed(BODY[:end], TODAY)


# --- read_feed --------------------------------------------------------------------------


def test_read_feed_reads_the_source_with_the_feed_limit(monkeypatch):
    seen = []

    def fake_get(url, limit=None):
        seen.append((url, limit))
        return BODY, "text/plain"

    monkeypatch.setattr(watch_feed, "get", fake_get)
    assert read_feed(SOURCE, TODAY) == load_feed(BODY, TODAY)
    assert seen == [(SOURCE["url"], FEED_MAX)]


class BigResponse:
    """A 2 MB answer that counts the bytes it hands out."""

    url = SOURCE["url"]

    def __init__(self):
        self.data = b"[" * (2 * 1024 * 1024)
        self.given = 0
        self.headers = email.message.Message()
        self.headers["Content-Type"] = "text/plain; charset=utf-8"

    def read(self, size=-1):
        out = self.data if size < 0 else self.data[:size]
        self.given += len(out)
        return out

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_a_2_mb_feed_is_refused_before_it_is_parsed(monkeypatch):
    answer = BigResponse()
    monkeypatch.setattr(watch_pages.urllib.request, "urlopen", lambda request, timeout: answer)

    def never(*args):
        raise AssertionError("parsed")

    monkeypatch.setattr(watch_feed, "load_feed", never)
    with pytest.raises(ValueError):
        read_feed(SOURCE, TODAY)
    assert answer.given == FEED_MAX + 1


def _unread(monkeypatch, capsys, body):
    monkeypatch.setattr(watch_feed, "get", lambda url, limit=None: (body, "text/plain"))
    got = read_or_none(SOURCE["id"], lambda s: read_feed(s, TODAY), SOURCE)
    return got, capsys.readouterr().err


def test_a_feed_four_days_old_is_a_failed_read(monkeypatch, capsys):
    got, err = _unread(monkeypatch, capsys, json.dumps(feed(checked="2026-11-12")))
    assert got is None and err == "cannot read agent-docs-feed: ValueError\n"


def test_a_feed_that_is_not_json_is_a_failed_read_and_none_of_it_is_printed(monkeypatch, capsys):
    got, err = _unread(monkeypatch, capsys, "<html>::error::@owner token</html>")
    # json's JSONDecodeError is a ValueError.
    assert got is None and err == "cannot read agent-docs-feed: JSONDecodeError\n"


def test_a_feed_over_its_limit_is_a_failed_read(monkeypatch, capsys):
    answer = BigResponse()
    monkeypatch.setattr(watch_pages.urllib.request, "urlopen", lambda request, timeout: answer)
    got = read_or_none(SOURCE["id"], lambda s: read_feed(s, TODAY), SOURCE)
    assert got is None
    assert capsys.readouterr().err == "cannot read agent-docs-feed: ValueError\n"


def test_a_good_feed_is_read(monkeypatch, capsys):
    got, err = _unread(monkeypatch, capsys, BODY)
    assert got == load_feed(BODY, TODAY) and err == ""


# --- wanted -----------------------------------------------------------------------------


def test_wanted_keeps_added_pages_and_changed_pages_with_new_sections():
    assert wanted(load_feed(BODY, TODAY), HOSTS, set(), "") == [
        entry("2026-11-14", "changed", RULES, "cursor", ["Planted heading three"]),
        entry("2026-11-15", "added", NEW),
        entry("2026-11-15", "changed", CHANGED, "codex",
              ["Planted heading one", "Planted heading two"]),
    ]


def test_a_changed_page_with_no_new_section_and_a_removed_page_are_not_wanted():
    entries = load_feed(BODY, TODAY)
    assert entry("2026-11-15", "changed", SAME) in entries
    assert entry("2026-11-15", "removed", GONE, "cursor") in entries
    urls = [e.url for e in wanted(entries, HOSTS, set(), "")]
    assert SAME not in urls and GONE not in urls


def test_a_day_not_after_the_last_day_taken_is_skipped():
    entries = load_feed(BODY, TODAY)
    assert [e.day for e in wanted(entries, HOSTS, set(), "2026-11-14")] == ["2026-11-15"] * 2
    assert wanted(entries, HOSTS, set(), "2026-11-15") == []


@pytest.mark.parametrize("product", ["mcp", "", "gemini", "Claude-Code", "claude_code"])
def test_a_product_that_is_not_a_client_is_dropped(product):
    entries = [entry("2026-11-15", "added", NEW, product)]
    assert wanted(entries, HOSTS, set(), "") == []


@pytest.mark.parametrize("listed", [
    "https://code.claude.com/docs/en/example-new",
    "https://code.claude.com/docs/en/example-new.md",
    "https://code.claude.com/docs/en/example-new/",
    "https://code.claude.com/docs/en/example-new#a-section",
    "https://Code.Claude.com/docs/en/example-new",
])
@pytest.mark.parametrize("url", [
    "https://code.claude.com/docs/en/example-new.md",
    "https://code.claude.com/docs/en/example-new",
    "https://code.claude.com/docs/en/example-new/",
    "https://code.claude.com/docs/en/example-new.md#a-section",
    "https://CODE.claude.com/docs/en/example-new.md",
])
def test_a_page_the_list_names_is_dropped_with_or_without_md(listed, url):
    entries = [entry("2026-11-15", "added", url)]
    assert wanted(entries, HOSTS, {listed}, "") == []
    assert wanted(entries, HOSTS, {"https://code.claude.com/docs/en/other"}, "") == entries


@pytest.mark.parametrize("url", [
    "https://code.claude.com/docs/en/example-new.md?x=1",
    "https://code.claude.com/docs/en/example-new.md?",
    "https://evil.example.com/docs/en/example-new.md",
    "https://code.claude.com.evil.example.com/docs/en/example-new.md",
    "https://raw.githubusercontent.com/o/agent-docs/main/feed.json",
    "http://code.claude.com/docs/en/example-new.md",
    "https://code.claude.com:8443/docs/en/example-new.md",
    "https://user@code.claude.com/docs/en/example-new.md",
    "https://code.claude.com/blog/example-new.md",
    "https://code.claude.com/docs/../blog/x.md",
    "https://code.claude.com/docs/en/café.md",
    "https://code.claude.com/docs/en/a b.md",
    "https://code.claude.com/docs/en/a`b.md",
    "javascript:alert(1)",
    "",
])
def test_an_address_that_fails_the_address_check_is_dropped(url):
    assert wanted([entry("2026-11-15", "added", url)], HOSTS, set(), "") == []


def test_a_listed_address_python_cannot_split_does_not_stop_the_filter():
    entries = [entry("2026-11-15", "added", NEW)]
    assert wanted(entries, HOSTS, {"https://[code.claude.com/docs"}, "") == entries


def test_the_same_page_twice_in_one_day_is_kept_once():
    entries = [
        entry("2026-11-15", "added", NEW),
        entry("2026-11-15", "changed", NEW.removesuffix(".md"), sections=["A"]),
        entry("2026-11-16", "changed", NEW, sections=["B"]),
    ]
    assert wanted(entries, HOSTS, set(), "") == [entries[0], entries[2]]


# --- kept_sections ----------------------------------------------------------------------

LIST = """## Codex
| What | Kind | Files | Seen in | macOS and Linux | Source |
|---|---|---|---|---|---|
| `requirements.toml` | file | `src/a.py` | config | same | https://developers.openai.com/codex/c |
"""


def test_kept_sections_keeps_a_list_word_a_topic_word_and_drops_the_rest():
    words = terms(LIST)[("codex", "requirements.toml")]
    assert words == ["requirements.toml"]
    by_word = Section("Admin", "## Admin\nSet it in requirements.toml for a team.\n", "h1")
    by_topic = Section("Plugins", "## Plugins\nInstall from the store.\n", "h2")
    neither = Section("Billing", "## Billing\nPay by card.\n", "h3")
    assert kept_sections([by_word, by_topic, neither], words) == [
        (by_word, "requirements.toml"), (by_topic, "plugin")]


def test_a_list_word_counts_only_standing_alone_and_as_written():
    words = ["requirements.toml"]
    inside = Section("A", "See myrequirements.toml here.", "h")
    other_case = Section("B", "See Requirements.TOML here.", "h")
    assert kept_sections([inside, other_case], words) == []


def test_a_list_word_beats_a_topic_word_in_the_same_section():
    both = Section("A", "Add an MCP server in requirements.toml.", "h")
    assert kept_sections([both], ["requirements.toml"]) == [(both, "requirements.toml")]


@pytest.mark.parametrize(("text", "word"), [
    ("Set up WEBHOOKS", "hook"),
    ("Edit AGENTS.MD at the root", "agents.md"),
    ("Put rules in .Cursor/Rules/", ".cursor/rules"),
    ("an Instruction File is read first", "instruction file"),
    ("the Marketplace lists them", "marketplace"),
    ("Skills load on demand", "skill"),
    ("Use ~/.claude/CLAUDE.md", "claude.md"),
    ("remote mcp servers", "mcp"),
])
def test_a_topic_word_counts_anywhere_in_any_case(text, word):
    section = Section("Any", text, "h")
    assert kept_sections([section], []) == [(section, word)]


def test_a_topic_word_only_in_the_key_does_not_count():
    # The text of a section holds its heading line; a key alone is not text.
    assert kept_sections([Section("Plugins", "Pay by card.", "h")], []) == []


def test_a_blank_list_word_keeps_nothing():
    assert kept_sections([Section("Billing", "Pay by card.", "h")], ["", " "]) == []
