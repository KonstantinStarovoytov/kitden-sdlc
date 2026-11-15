import json

import pytest

from doc_address import load_hosts
from watch_moved import manifest_addresses, moved

HOSTS = load_hosts()


class Locate:
    """A fake `locate`: answers from `targets` (address: target) and records each call."""

    def __init__(self, targets=None, fail=False):
        self.targets = targets or {}
        self.fail = fail
        self.asked = []

    def __call__(self, address):
        self.asked.append(address)
        if self.fail:
            raise OSError("no network")
        return self.targets.get(address)


def body(keys):
    return json.dumps({"indexed_at": "2026-11-15",
                       "documents": {k: {"summary": "s"} for k in keys}})


def test_manifest_addresses_returns_the_keys():
    keys = ["https://code.claude.com/docs/en/a.md", "https://cursor.com/docs/b.md"]
    assert manifest_addresses(body(keys)) == set(keys)


@pytest.mark.parametrize("text", [
    "[]",
    "{}",
    '{"documents": []}',
    '{"documents": "x"}',
    '{"documents": {}}',
    "[1, 2]",
    "not json",
])
def test_manifest_addresses_refuses_another_shape(text):
    with pytest.raises(ValueError):
        manifest_addresses(text)


def test_address_in_the_manifest_gives_nothing_and_is_not_asked():
    locate = Locate()
    pages = {"https://code.claude.com/docs/en/a": "claude",
             "https://code.claude.com/docs/en/b.md": "claude"}
    manifest = {"https://code.claude.com/docs/en/a.md", "https://code.claude.com/docs/en/b.md"}
    assert moved(pages, manifest, HOSTS, locate) == []
    assert locate.asked == []


def test_redirect_to_an_allowed_address_is_moved():
    locate = Locate({"https://cursor.com/docs/context/skills": "https://cursor.com/docs/skills"})
    pages = {"https://cursor.com/docs/context/skills": "cursor"}
    assert moved(pages, set(), HOSTS, locate) == [
        {"address": "https://cursor.com/docs/context/skills", "client": "cursor",
         "verdict": "moved", "to": "https://cursor.com/docs/skills"},
    ]


def test_moved_to_drops_a_trailing_md():
    locate = Locate({"https://code.claude.com/docs/en/a": "https://code.claude.com/docs/en/b.md"})
    result = moved({"https://code.claude.com/docs/en/a": "claude"}, set(), HOSTS, locate)
    assert result[0]["to"] == "https://code.claude.com/docs/en/b"


def test_redirect_to_another_doc_host_is_moved():
    address = "https://developers.openai.com/codex/config-reference"
    locate = Locate({address: "https://learn.chatgpt.com/docs/config-reference"})
    result = moved({address: "codex"}, set(), HOSTS, locate)
    assert result[0]["verdict"] == "moved"
    assert result[0]["to"] == "https://learn.chatgpt.com/docs/config-reference"


def test_redirect_to_an_address_that_is_not_allowed_is_not_moved():
    address = "https://cursor.com/docs/a"
    locate = Locate({address: "https://example.com/docs/a"})
    result = moved({address: "cursor"}, set(), HOSTS, locate)
    assert result[0]["verdict"] == "absent"


def test_same_host_and_last_part_is_maybe():
    locate = Locate()
    pages = {"https://cursor.com/docs/context/skills": "cursor"}
    manifest = {"https://cursor.com/docs/skills.md", "https://cursor.com/docs/rules.md"}
    assert moved(pages, manifest, HOSTS, locate) == [
        {"address": "https://cursor.com/docs/context/skills", "client": "cursor",
         "verdict": "maybe", "to": "https://cursor.com/docs/skills"},
    ]
    assert locate.asked == ["https://cursor.com/docs/context/skills"]


def test_maybe_takes_the_first_match_in_sorted_order():
    pages = {"https://cursor.com/docs/old/skills": "cursor"}
    manifest = {"https://cursor.com/docs/z/skills.md", "https://cursor.com/docs/a/skills.md"}
    result = moved(pages, manifest, HOSTS, Locate())
    assert result[0]["to"] == "https://cursor.com/docs/a/skills"


def test_maybe_needs_the_same_path_start():
    pages = {"https://cursor.com/help/customization/rules": "cursor"}
    manifest = {"https://cursor.com/docs/rules.md"}
    result = moved(pages, manifest, HOSTS, Locate())
    assert (result[0]["verdict"], result[0]["to"]) == ("absent", "")


def test_maybe_takes_the_shortest_path():
    pages = {"https://cursor.com/docs/context/skills": "cursor"}
    manifest = {"https://cursor.com/docs/agent-sdk/reference/skills.md",
                "https://cursor.com/docs/skills.md"}
    result = moved(pages, manifest, HOSTS, Locate())
    assert result[0]["to"] == "https://cursor.com/docs/skills"


def test_maybe_needs_the_same_host():
    pages = {"https://cursor.com/docs/old/skills": "cursor"}
    manifest = {"https://code.claude.com/docs/en/skills.md"}
    result = moved(pages, manifest, HOSTS, Locate())
    assert result[0]["verdict"] == "absent"


def test_no_redirect_and_no_match_is_absent():
    pages = {"https://cursor.com/docs/gone": "cursor"}
    manifest = {"https://cursor.com/docs/skills.md"}
    assert moved(pages, manifest, HOSTS, Locate()) == [
        {"address": "https://cursor.com/docs/gone", "client": "cursor",
         "verdict": "absent", "to": ""},
    ]


def test_manifest_address_with_a_query_is_ignored():
    pages = {"https://cursor.com/docs/a": "cursor", "https://cursor.com/docs/old/skills": "cursor"}
    manifest = {"https://cursor.com/docs/a.md?x=1", "https://cursor.com/docs/skills.md?x=1",
                "https://example.com/docs/skills.md"}
    result = moved(pages, manifest, HOSTS, Locate())
    assert [(r["address"], r["verdict"]) for r in result] == [
        ("https://cursor.com/docs/a", "absent"),
        ("https://cursor.com/docs/old/skills", "absent"),
    ]


def test_locate_is_called_once_an_address():
    locate = Locate()
    pages = {"https://cursor.com/docs/a": "cursor", "https://cursor.com/docs/b": "cursor"}
    moved(pages, set(), HOSTS, locate)
    assert sorted(locate.asked) == ["https://cursor.com/docs/a", "https://cursor.com/docs/b"]


def test_locate_that_raises_is_no_redirect():
    pages = {"https://cursor.com/docs/old/skills": "cursor"}
    manifest = {"https://cursor.com/docs/skills.md"}
    result = moved(pages, manifest, HOSTS, Locate(fail=True))
    assert result[0]["verdict"] == "maybe"


@pytest.mark.parametrize("address", [
    "https://[bad/docs/x",
    "https://evil.example/docs/skills",
    "http://cursor.com/docs/skills",
    "https://cursor.com/docs/skills?x=1",
    "https://cursor.com/blog/skills",
])
def test_list_address_that_is_not_allowed_is_skipped(address):
    locate = Locate({address: "https://cursor.com/docs/skills"})
    manifest = {"https://cursor.com/docs/skills.md"}
    assert moved({address: "cursor"}, manifest, HOSTS, locate) == []
    assert locate.asked == []


def test_list_address_that_is_not_allowed_does_not_stop_the_rest():
    pages = {"https://[bad/docs/x": "cursor", "https://cursor.com/docs/gone": "cursor"}
    result = moved(pages, set(), HOSTS, Locate(fail=True))
    assert [r["address"] for r in result] == ["https://cursor.com/docs/gone"]


def test_list_address_with_an_empty_last_part_is_never_maybe():
    pages = {"https://cursor.com/docs/skills/": "cursor"}
    manifest = {"https://cursor.com/docs/skills.md", "https://cursor.com/docs/a/skills.md"}
    result = moved(pages, manifest, HOSTS, Locate())
    assert result == [{"address": "https://cursor.com/docs/skills/", "client": "cursor",
                       "verdict": "absent", "to": ""}]


def test_result_is_sorted_by_address():
    pages = {"https://cursor.com/docs/c": "cursor", "https://code.claude.com/docs/en/a": "claude",
             "https://cursor.com/docs/b": "cursor"}
    result = moved(pages, set(), HOSTS, Locate())
    assert [r["address"] for r in result] == sorted(pages)
