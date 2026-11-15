# ruff: noqa: E501
import pytest

from watch_list import Row, doc_pages, held, parse_list, row_words, terms

TEXT = """## Codex
| What | Kind | Files | Seen in | macOS and Linux | Source |
|---|---|---|---|---|---|
| `codex plugin list --json` | command | `src/a.py`, `src/b.py` | plugins | same | https://learn.chatgpt.com/docs/plugins |
| rollout log lines | path | `src/c.py` | skill list | same | install |
"""


def test_parse_list_reads_rows():
    rows = parse_list(TEXT)
    assert rows[0] == Row("codex", "codex plugin list --json", "command",
                          ["src/a.py", "src/b.py"], "plugins", "same",
                          "https://learn.chatgpt.com/docs/plugins")
    assert len(rows) == 2


def test_separator_row_with_spaces_is_not_a_row():
    text = TEXT.replace("|---|---|---|---|---|---|", "| --- | --- | --- | --- | --- | --- |")
    assert len(parse_list(text)) == 2
    text = TEXT.replace("|---|---|---|---|---|---|", "| :--- | --- | --- | --- | --- | --- |")
    assert len(parse_list(text)) == 2


def test_doc_pages_keeps_addresses_only():
    assert doc_pages(parse_list(TEXT)) == {"https://learn.chatgpt.com/docs/plugins": "codex"}


def test_rows_outside_a_client_section_are_ignored():
    assert parse_list("| a | path | `x` | y | same | guess |") == []


def test_terms_keep_exact_words_only():
    got = terms(TEXT)
    assert got[("codex", "codex plugin list --json")] == ["--json"]
    assert got[("codex", "rollout log lines")] == []


WORDS = """## Claude Code
| What | Kind | Files | Seen in | macOS and Linux | Source |
|---|---|---|---|---|---|
| `hooks` | key | `src/a.py` | hooks | same | https://example.com/hooks |
| `rules/*.md` | path | `src/b.py` | rules | same | https://example.com/memory |
| `claude mcp add-json -s user <name>` | command | `src/c.py` | servers | same | https://example.com/mcp |
| `a*` and `x/*` | path | `src/d.py` | rules | same | guess |
| `hooks` and `hooks` again | key | `src/e.py` | hooks | same | guess |
| `<project>/.mcp.json` and `cmd '<json>' -s` | path | `src/g.py` | servers | same | guess |
| `'rules/*.md'` and `"enabled"` and `'x*'` and `''` | key | `src/h.py` | rules | same | guess |
| `key = value` and `-` and `--` and `...` and `-s` | key | `src/i.py` | rules | same | guess |
| `(file: path)` and `cursor.plugins.installedIds.` and `.claude` and `rules/` and `x).` and `'(y;)'` | key | `src/j.py` | rules | same | guess |
| rollout log lines | path | `src/f.py` | skill list | same | install |
"""


def test_row_words_keeps_every_word_in_backticks():
    got = row_words(WORDS)
    assert got[("claude-code", "hooks")] == ["hooks"]
    assert got[("claude-code", "claude mcp add-json -s user <name>")] == [
        "claude", "mcp", "add-json", "-s", "user"]
    assert got[("claude-code", "rollout log lines")] == []


def test_row_words_keeps_the_longest_part_of_a_word_with_a_star():
    got = row_words(WORDS)
    assert got[("claude-code", "rules/*.md")] == ["rules/"]
    assert got[("claude-code", "a* and x/*")] == []


def test_row_words_has_no_repeats():
    assert row_words(WORDS)[("claude-code", "hooks and hooks again")] == ["hooks"]


def test_row_words_is_keyed_like_terms():
    assert row_words(WORDS).keys() == terms(WORDS).keys()
    assert row_words(TEXT).keys() == terms(TEXT).keys()


def test_terms_still_drops_short_plain_words():
    assert terms(WORDS)[("claude-code", "hooks")] == []


def test_held_gives_the_words_not_in_the_body_in_order():
    assert held(["rules/", "Hooks", "-s"], "Put files in rules/ with -s.") == ["Hooks"]
    assert held(["b", "a"], "") == ["b", "a"]
    assert held([], "anything") == []


def test_row_words_drops_placeholders():
    got = row_words(WORDS)
    assert got[("claude-code", "<project>/.mcp.json and cmd '<json>' -s")] == ["cmd", "-s"]


def test_row_words_strips_quotes_before_the_star_rule():
    got = row_words(WORDS)
    assert got[("claude-code", "'rules/*.md' and \"enabled\" and 'x*' and ''")] == [
        "rules/", "enabled"]


def test_row_words_drops_a_word_with_no_letter_or_digit():
    got = row_words(WORDS)
    assert got[("claude-code", "key = value and - and -- and ... and -s")] == ["key", "value", "-s"]


@pytest.mark.parametrize(("word", "body", "found"), [
    ("-s", "Pass --scope user.", False),
    ("-s", "Pass --settings here.", False),
    ("-s", "Pass -s user.", True),
    ("ws", "This allows it.", False),
    ("ws", "Types: http, ws.", True),
    ("enable", "Run disable first.", False),
    ("enable", "Run enable first.", True),
    ("enable", "Set enabledPlugins.", False),
    ("id", "The provider is set.", False),
    ("id", "The plugin id.", True),
    ("id", "an id_token", False),
    ("rules/", "Files in rules/*.md load.", True),
    (".claude", "Look in .claude/settings.json now.", True),
    ("hooks", "hooks are read.", True),
    ("hooks", "Read the hooks", True),
    ("hooks", "hooks", True),
    ("Hooks", "hooks are read.", False),
    ("add", "add-json", False),
])
def test_held_finds_a_word_only_where_it_stands_alone(word, body, found):
    assert held([word], body) == ([] if found else [word])


def test_held_finds_a_word_that_stands_alone_once_among_other_uses():
    assert held(["-s"], "Use --scope or -s.") == []


def test_row_words_strips_the_prose_marks_around_a_word():
    got = row_words(WORDS)
    key = ("claude-code", "(file: path) and cursor.plugins.installedIds. and .claude and rules/ "
           "and x). and '(y;)'")
    assert got[key] == ["file", "path", "cursor.plugins.installedIds", ".claude", "rules/", "x",
                        "y"]
