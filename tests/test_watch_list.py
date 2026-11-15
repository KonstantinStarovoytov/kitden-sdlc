# ruff: noqa: E501
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
| rollout log lines | path | `src/f.py` | skill list | same | install |
"""


def test_row_words_keeps_every_word_in_backticks():
    got = row_words(WORDS)
    assert got[("claude-code", "hooks")] == ["hooks"]
    assert got[("claude-code", "claude mcp add-json -s user <name>")] == [
        "claude", "mcp", "add-json", "-s", "user", "<name>"]
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
