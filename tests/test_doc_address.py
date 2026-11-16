import email.message
import io
import urllib.error
import urllib.request
import urllib.response

import pytest

from doc_address import CONFIG, allowed, load_hosts, location, make_opener, read

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
