# ruff: noqa: E501
from watch_list import Row, doc_pages, parse_list, terms

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
