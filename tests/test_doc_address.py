import copy
import email.message
import io
import pickle
import urllib.error
import urllib.request
import urllib.response

import pytest

from doc_address import (
    CONFIG,
    NO_TEXT_CLIENTS,
    Page,
    allowed,
    clean_heading,
    client_of,
    load_hosts,
    location,
    make_opener,
    read,
)
from watch_feed import PRODUCTS

HOSTS = load_hosts()
PAGE = "https://code.claude.com/docs/en/mcp.md"


class FakeWeb(urllib.request.HTTPSHandler):
    """Answers https requests from `pages` (address: (status, headers, body)) and records each
    request it gets. An address not in `pages` gives 404."""

    def __init__(self, pages):
        super().__init__()
        self.pages = pages
        self.asked = []

    def https_open(self, req):
        self.asked.append(req)
        status, headers, body = self.pages.get(req.full_url, (404, {}, b"missing"))
        head = email.message.Message()
        for name, value in headers.items():
            head[name] = value
        resp = urllib.response.addinfourl(io.BytesIO(body), head, req.full_url, status)
        resp.msg = "fake"
        return resp


def web(pages, follow=True):
    fake = FakeWeb(pages)
    return fake, make_opener(HOSTS, follow, fake)


def test_config_lists_the_doc_hosts():
    assert CONFIG.name == "doc-hosts.yml"
    assert ("code.claude.com", "/docs/") in HOSTS
    assert ("cursor.com", "/help/") in HOSTS
    assert ("developers.openai.com", "/codex/") in HOSTS
    assert ("developers.openai.com", "/plugins/") in HOSTS


REFUSED = [
    "http://code.claude.com/docs/en/mcp.md",
    "https://code.claude.com/docs/en/mcp.md?x=1",
    "https://code.claude.com/docs/en/mcp.md?",
    "https://code.claude.com:8443/docs/en/mcp.md",
    "https://code.claude.com:443/docs/en/mcp.md",
    "https://me@code.claude.com/docs/en/mcp.md",
    "https://me:pw@code.claude.com/docs/en/mcp.md",
    "https://example.com/docs/en/mcp.md",
    "https://code.claude.com.example.com/docs/en/mcp.md",
    "https://evil.code.claude.com/docs/en/mcp.md",
    "https://code.claude.com/blog/post",
    "https://code.claude.com/docs",
    "https://code.claude.com/docs/../blog/post",
    "https://code.claude.com/docs/%2e%2e/blog/post",
    "https://cursor.com/changelog",
    "https://cursor.com/docsx/a",
    "ftp://cursor.com/docs/a",
    "https:///docs/a",
    "https://code.claude.com/docs/en/mcp\x7f",
    "https://code.claude.com/docs/en/caf\u00e9",
    "https://code.claude.com/docs/en/\u202egpj.md",
    "not an address",
    "",
]


@pytest.mark.parametrize("address", REFUSED)
def test_refused_address_is_not_allowed(address):
    assert allowed(address, HOSTS) is False


@pytest.mark.parametrize("address", REFUSED)
def test_refused_address_is_never_read(address):
    fake, opener = web({address: (200, {"Content-Type": "text/plain"}, b"x")})
    with pytest.raises(ValueError):
        read(address, HOSTS, opener)
    assert fake.asked == []


@pytest.mark.parametrize("address", [
    PAGE,
    "https://Code.Claude.COM/docs/en/mcp.md",
    "https://cursor.com/help/a",
    "https://learn.chatgpt.com/docs/x",
    "https://developers.openai.com/codex/config",
    "https://developers.openai.com/plugins/build/plugins",
])
def test_listed_address_is_allowed(address):
    assert allowed(address, HOSTS) is True


def test_path_start_is_compared_as_written():
    assert allowed("https://code.claude.com/Docs/en/mcp.md", HOSTS) is False


def test_read_gives_body_type_and_address():
    fake, opener = web({PAGE: (200, {"Content-Type": "text/markdown; charset=utf-8"},
                               "# MCP\nhello é\n".encode())})
    assert read(PAGE, HOSTS, opener) == ("# MCP\nhello é\n", "text/markdown", PAGE)


def test_unknown_charset_falls_back_to_utf8():
    fake, opener = web({PAGE: (200, {"Content-Type": "text/plain; charset=bogus"},
                               "hello é".encode())})
    assert read(PAGE, HOSTS, opener) == ("hello é", "text/plain", PAGE)


def test_read_sends_our_user_agent_and_timeout():
    fake, opener = web({PAGE: (200, {"Content-Type": "text/plain"}, b"x")})
    read(PAGE, HOSTS, opener)
    agent = fake.asked[0].get_header("User-agent")
    assert agent.startswith("kitden-sdlc-watcher")
    assert agent == "kitden-sdlc-watcher (+https://github.com/KonstantinStarovoytov/kitden-sdlc)"
    assert fake.asked[0].timeout == 20


def test_redirect_to_an_allowed_address_is_followed():
    final = "https://code.claude.com/docs/en/mcp-new.md"
    fake, opener = web({
        PAGE: (301, {"Location": final}, b""),
        final: (200, {"Content-Type": "text/markdown"}, b"# New\n"),
    })
    assert read(PAGE, HOSTS, opener) == ("# New\n", "text/markdown", final)
    assert [r.full_url for r in fake.asked] == [PAGE, final]


def test_relative_redirect_is_followed_when_allowed():
    final = "https://code.claude.com/docs/en/other.md"
    fake, opener = web({
        PAGE: (302, {"Location": "/docs/en/other.md"}, b""),
        final: (200, {"Content-Type": "text/markdown"}, b"ok"),
    })
    assert read(PAGE, HOSTS, opener)[2] == final


@pytest.mark.parametrize("target", [
    "https://example.com/docs/en/mcp.md",
    "https://code.claude.com/blog/post",
    "http://code.claude.com/docs/en/mcp.md",
    "https://code.claude.com/docs/en/mcp.md?x=1",
    "/blog/post",
])
def test_redirect_off_the_list_raises_before_the_second_request(target):
    fake, opener = web({PAGE: (302, {"Location": target}, b"")})
    with pytest.raises(ValueError):
        read(PAGE, HOSTS, opener)
    assert [r.full_url for r in fake.asked] == [PAGE]


def test_read_with_the_default_opener_refuses_without_a_request(monkeypatch):
    def no_network(*args, **kwargs):
        raise AssertionError("no request expected")

    monkeypatch.setattr(urllib.request.OpenerDirector, "open", no_network)
    with pytest.raises(ValueError):
        read("https://example.com/docs/a", HOSTS)


def test_body_over_two_megabytes_raises_oserror():
    big = b"a" * (2 * 1024 * 1024 + 1)
    fake, opener = web({PAGE: (200, {"Content-Type": "text/plain"}, big)})
    with pytest.raises(OSError):
        read(PAGE, HOSTS, opener)


def test_body_of_exactly_two_megabytes_is_read():
    body = b"a" * (2 * 1024 * 1024)
    fake, opener = web({PAGE: (200, {"Content-Type": "text/plain"}, body)})
    assert len(read(PAGE, HOSTS, opener)[0]) == len(body)


def test_missing_page_raises_oserror():
    fake, opener = web({})
    with pytest.raises(OSError) as caught:
        read(PAGE, HOSTS, opener)
    assert isinstance(caught.value, urllib.error.HTTPError)


def test_timeout_raises_oserror():
    class Slow(urllib.request.HTTPSHandler):
        def https_open(self, req):
            raise TimeoutError("timed out")

    with pytest.raises(OSError):
        read(PAGE, HOSTS, make_opener(HOSTS, True, Slow()))


def test_location_gives_an_allowed_target_without_following():
    target = "https://code.claude.com/docs/en/mcp-new.md"
    fake, opener = web({PAGE: (301, {"Location": target}, b"")}, follow=False)
    assert location(PAGE, HOSTS, opener) == target
    assert [r.full_url for r in fake.asked] == [PAGE]


def test_location_joins_a_relative_target():
    fake, opener = web({PAGE: (308, {"Location": "/docs/en/b.md"}, b"")}, follow=False)
    assert location(PAGE, HOSTS, opener) == "https://code.claude.com/docs/en/b.md"


def test_location_gives_none_for_a_target_off_the_list():
    fake, opener = web({PAGE: (302, {"Location": "https://example.com/x"}, b"")},
                       follow=False)
    assert location(PAGE, HOSTS, opener) is None
    assert [r.full_url for r in fake.asked] == [PAGE]


def test_location_gives_none_without_a_redirect():
    fake, opener = web({PAGE: (200, {"Content-Type": "text/plain"}, b"x")}, follow=False)
    assert location(PAGE, HOSTS, opener) is None


def test_location_refuses_an_address_off_the_list():
    fake, opener = web({}, follow=False)
    with pytest.raises(ValueError):
        location("https://cursor.com/changelog", HOSTS, opener)
    assert fake.asked == []


def test_location_sends_our_user_agent():
    fake, opener = web({PAGE: (200, {}, b"")}, follow=False)
    location(PAGE, HOSTS, opener)
    assert fake.asked[0].get_header("User-agent").startswith("kitden-sdlc-watcher")


def test_load_hosts_reads_a_given_file(tmp_path):
    path = tmp_path / "hosts.yml"
    path.write_text("- {host: Docs.Example.com, path: /a/}\n")
    assert load_hosts(path) == [("docs.example.com", "/a/")]


@pytest.mark.parametrize("start", ["/a", "a/", "a"])
def test_load_hosts_refuses_a_path_without_slashes_at_both_ends(tmp_path, start):
    path = tmp_path / "hosts.yml"
    path.write_text(f"- {{host: docs.example.com, path: {start}}}\n")
    with pytest.raises(ValueError):
        load_hosts(path)


CLIENTS = {
    ("code.claude.com", "/docs/"): "claude-code",
    ("cursor.com", "/docs/"): "cursor",
    ("cursor.com", "/help/"): "cursor",
    ("learn.chatgpt.com", "/docs/"): "codex",
    ("developers.openai.com", "/codex/"): "codex",
    ("developers.openai.com", "/plugins/"): "codex",
}


def test_every_doc_host_in_the_config_names_its_client():
    assert {pair: pair.client for pair in HOSTS} == CLIENTS
    assert all(pair.client in PRODUCTS for pair in HOSTS)


def test_the_hosts_are_still_plain_pairs():
    assert list(CLIENTS) == HOSTS
    assert all(len(pair) == 2 for pair in HOSTS)
    host, start = HOSTS[0]
    assert (host, start) == ("code.claude.com", "/docs/")


def test_the_hosts_copy_and_pickle_with_their_clients():
    for again in (copy.deepcopy(HOSTS), copy.copy(HOSTS), pickle.loads(pickle.dumps(HOSTS))):
        assert again == HOSTS
        assert [pair.client for pair in again] == [pair.client for pair in HOSTS]


@pytest.mark.parametrize(("url", "client"), [
    ("https://code.claude.com/docs/en/mcp.md", "claude-code"),
    ("https://cursor.com/docs/context/rules", "cursor"),
    ("https://cursor.com/help/models", "cursor"),
    ("https://learn.chatgpt.com/docs/codex", "codex"),
    ("https://developers.openai.com/codex/config", "codex"),
    ("https://developers.openai.com/plugins/build", "codex"),
    ("https://CURSOR.com/docs/x.md#part", "cursor"),
])
def test_client_of_names_the_client_of_the_address_host_and_path(url, client):
    assert client_of(url, HOSTS) == client


@pytest.mark.parametrize("url", [
    "https://cursor.com/blog/x", "https://evil.example.com/docs/x",
    "https://cursor.com/docs/x?y=1", "http://cursor.com/docs/x", "", None, 1,
])
def test_client_of_an_address_that_is_not_allowed_is_none(url):
    assert client_of(url, HOSTS) is None


def test_client_of_with_pairs_that_name_no_client_is_none():
    assert client_of(PAGE, [("code.claude.com", "/docs/")]) is None


def test_load_hosts_reads_each_client(tmp_path):
    path = tmp_path / "hosts.yml"
    path.write_text("- {host: docs.example.com, path: /a/, client: codex}\n"
                    "- {host: docs.example.com, path: /a/b/, client: cursor}\n"
                    "- {host: other.example.com, path: /z/}\n")
    hosts = load_hosts(path)
    assert [pair.client for pair in hosts] == ["codex", "cursor", None]
    # The longest path an address is under decides.
    assert client_of("https://docs.example.com/a/x", hosts) == "codex"
    assert client_of("https://docs.example.com/a/b/x", hosts) == "cursor"
    assert client_of("https://other.example.com/z/x", hosts) is None


def test_load_hosts_refuses_the_same_host_and_path_twice(tmp_path):
    path = tmp_path / "hosts.yml"
    path.write_text("- {host: docs.example.com, path: /a/, client: codex}\n"
                    "- {host: Docs.example.com, path: /a/, client: cursor}\n")
    with pytest.raises(ValueError):
        load_hosts(path)


# Cleaning what comes from a passage


def test_a_heading_keeps_only_letters_digits_spaces_and_a_few_marks():
    assert clean_heading("Set `x` | <b>y</b> [z](w) *é* 2-a_b.c,d:e(f)/g") == (
        "Set x by/b z(w) é 2-a_b.c,d:e(f)/g")


def test_a_heading_turns_line_breaks_into_spaces_and_drops_hidden_characters():
    assert clean_heading("One\nTwo\tThree\u202eFour\u200b") == "One Two ThreeFour"


def test_a_heading_is_cut_to_80_characters():
    assert len(clean_heading("a" * 200)) == 80


def test_cursor_is_the_one_client_whose_doc_text_is_kept_out():
    from watch_list import CLIENTS

    assert NO_TEXT_CLIENTS == ("cursor",)
    assert set(NO_TEXT_CLIENTS) <= set(CLIENTS.values())


# A Page pair: one page, for a rule page outside the config (watch_fetch.read_rule_page)

SUBMIT = Page("stores.example.org", "/rules/submit")


@pytest.mark.parametrize("address, ok", [
    ("https://stores.example.org/rules/submit", True),
    ("https://stores.example.org/rules/submit/", True),
    ("https://stores.example.org/rules/submit/part", True),
    ("https://stores.example.org/rules/submitx", False),
    ("https://stores.example.org/rules/submit-other", False),
    ("https://stores.example.org/rules/", False),
    ("https://stores.example.org/", False),
    ("https://other.example.org/rules/submit", False),
    ("https://stores.example.org/rules/submit?x=1", False),
    ("https://stores.example.org/rules/submit/../other", False),
])
def test_a_page_pair_allows_its_path_and_whole_parts_under_it_only(address, ok):
    assert allowed(address, [SUBMIT]) is ok


@pytest.mark.parametrize("address, ok", [
    ("https://stores.example.org/help/", True), ("https://stores.example.org/help/a", True),
    ("https://stores.example.org/help", False), ("https://stores.example.org/helpx/", False),
])
def test_a_page_pair_ending_in_a_slash_allows_what_is_under_it(address, ok):
    assert allowed(address, [Page("stores.example.org", "/help/")]) is ok


@pytest.mark.parametrize("start", ["", "/"])
@pytest.mark.parametrize("address, ok", [
    ("https://stores.example.org", True), ("https://stores.example.org/", True),
    ("https://stores.example.org/en/", False), ("https://stores.example.org/a", False),
])
def test_a_page_at_the_root_of_its_host_allows_the_root_only(start, address, ok):
    assert allowed(address, [Page("stores.example.org", start)]) is ok


def test_a_page_pair_compares_and_unpacks_as_the_plain_pair():
    assert SUBMIT == ("stores.example.org", "/rules/submit")
    host, start = SUBMIT
    assert (host, start) == ("stores.example.org", "/rules/submit")
    assert copy.deepcopy(SUBMIT) == SUBMIT and isinstance(copy.deepcopy(SUBMIT), Page)


def test_a_config_pair_still_allows_any_path_that_starts_with_its_path():
    assert allowed("https://code.claude.com/docs/en/mcpx", HOSTS)
    assert allowed("https://stores.example.org/rules/submitx",
                   [("stores.example.org", "/rules/submit")])
