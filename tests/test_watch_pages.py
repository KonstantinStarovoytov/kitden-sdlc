import email.message

import pytest

import watch_pages
from doc_address import USER_AGENT, load_hosts, make_opener
from tests.test_doc_address import FakeWeb
from watch_pages import get, get_doc, releases, sections

HOSTS = load_hosts()
DOC = "https://code.claude.com/docs/en/mcp"
MD = (200, {"Content-Type": "text/markdown; charset=utf-8"}, b"# Title\nmarkdown body\n")
HTML = (200, {"Content-Type": "text/html; charset=utf-8"}, b"<h1>Title</h1><p>html body</p>")


def web(pages):
    fake = FakeWeb(pages)
    return fake, make_opener(HOSTS, True, fake)


def test_markdown_sections_by_level():
    out = sections("# T\n## 2.1.2\n- a\n## 2.1.1\n- b\n### sub\nc\n", "text/markdown", level=2)
    assert [s.key for s in out] == ["T", "2.1.2", "2.1.1"]
    assert "sub" in out[2].text


def test_html_hash_ignores_scripts_and_spacing():
    a = sections("<nav>x1</nav><h2>Rules</h2><p>Use  mdc</p><script>1</script>", "text/html")
    b = sections("<nav>x2</nav><h2>Rules</h2>\n<p>Use mdc</p><script>2</script>", "text/html")
    assert a[0].key == "Rules" and a[0].hash == b[0].hash


def test_same_heading_twice_gets_a_number():
    out = sections("## A\n1\n## A\n2\n", "text/markdown")
    assert [s.key for s in out] == ["A", "A (2)"]


def test_releases_skip_prereleases():
    payload = [
        {"tag_name": "rust-v0.169.0-alpha.1", "prerelease": True, "draft": False, "body": ""},
        {"tag_name": "rust-v0.168.0", "prerelease": False, "draft": False, "body": "notes"},
    ]
    assert [s.key for s in releases(payload)] == ["rust-v0.168.0"]


def test_get_refuses_plain_http():
    with pytest.raises(ValueError):
        get("http://example.com")


def test_text_keeps_newlines_and_hash_ignores_spacing():
    a = sections("## A\nx\ny\n", "text/markdown")
    b = sections("## A\nx  \ny\n", "text/markdown")
    assert "\n" in a[0].text and a[0].hash == b[0].hash


def test_hash_in_fence_is_not_a_heading():
    out = sections("## A\n```\n# comment\n```\n## B", "text/markdown", level=2)
    assert [s.key for s in out] == ["A", "B"]


def test_inline_html_adds_no_space_and_blocks_keep_apart():
    html = ("<h2>Rules</h2><p>Edit <code>~/.cursor/</code>mcp.json</p>"
            "<ul><li>one</li><li>two</li></ul>a<br>b")
    text = sections(html, "text/html")[0].text
    assert "~/.cursor/mcp.json" in text
    assert "onetwo" not in text and "ab" not in text


def test_table_cells_and_list_terms_keep_apart():
    html = ("<h2>Keys</h2><table><tr><th>Key</th><th>Type</th></tr>"
            "<tr><td>a</td><td>b</td></tr></table><dl><dt>x</dt><dd>y</dd></dl>"
            "<blockquote>q</blockquote>z")
    text = sections(html, "text/html")[0].text
    assert "KeyType" not in text and "ab" not in text
    assert "xy" not in text and "qz" not in text


def entry(date, title, body):
    return (f"<article><p><time>{date}</time> · Changelog</p><header><h1><a>{title}</a></h1>"
            f"</header><p>{body}</p><h2><a>#</a>Get started</h2><p>More on {title}.</p>"
            "</article>")


PAGE = ("<html><header><nav>menu</nav>Site</header><main><p>Changelog</p>{}</main>"
        "<footer>foot</footer><script>x</script></html>")


def test_split_starts_one_section_per_tag_keyed_by_its_first_heading():
    html = PAGE.format(entry("Nov 6, 2026", "Voice Chat", "Talk.") +
                       entry("Nov 5, 2026", "Live Apps", "Build."))
    out = sections(html, "text/html", level=2, split="article")
    assert [s.key for s in out] == ["", "Voice Chat", "Live Apps"]
    voice = " ".join(out[1].text.split())
    assert voice.startswith("Nov 6, 2026") and "Voice Chat" in voice and "Get started" in voice
    assert "Nov 5" not in voice and "Live Apps" not in voice
    assert "Build." in out[2].text
    assert all(w not in s.text for s in out for w in ("menu", "Site", "foot", "x"))


def test_split_keys_and_hashes_stay_when_a_new_entry_is_added_on_top():
    old_entries = entry("Nov 6, 2026", "Voice Chat", "Talk.") + entry("Nov 5, 2026", "A", "b")
    old = sections(PAGE.format(old_entries * 2), "text/html", split="article")
    new = sections(PAGE.format((entry("Nov 9, 2026", "New", "n") + old_entries) * 2),
                   "text/html", split="article")
    before = {s.key: s.hash for s in old if s.key}
    after = {s.key: s.hash for s in new if s.key}
    assert set(before) == {"Voice Chat", "A"}
    assert {k: after[k] for k in before} == before


def test_a_repeated_section_with_the_same_text_is_dropped():
    html = PAGE.format(entry("Nov 6, 2026", "A", "a") * 2 + entry("Nov 7, 2026", "A", "b"))
    out = sections(html, "text/html", split="article")
    assert [s.key for s in out] == ["", "A", "A (2)"]
    assert "Nov 7" in out[2].text
    assert [s.key for s in sections("## A\n1\n## A\n1\n", "text/markdown")] == ["A"]


def test_get_doc_reads_the_md_address_first():
    fake, opener = web({DOC + ".md": MD, DOC: HTML})
    body, kind, read_from = get_doc(DOC, HOSTS, opener)
    assert "markdown body" in body and kind == "text/markdown"
    assert read_from == DOC + ".md"
    assert [r.full_url for r in fake.asked] == [DOC + ".md"]


def test_get_doc_takes_plain_text_from_the_md_address():
    plain = (200, {"Content-Type": "text/plain"}, b"# Title\nplain body\n")
    fake, opener = web({DOC + ".md": plain, DOC: HTML})
    assert get_doc(DOC, HOSTS, opener) == ("# Title\nplain body\n", "text/plain", DOC + ".md")


def test_get_doc_reads_the_plain_address_when_md_is_missing():
    fake, opener = web({DOC: HTML})
    body, kind, read_from = get_doc(DOC, HOSTS, opener)
    assert "html body" in body and kind == "text/html" and read_from == DOC
    assert [r.full_url for r in fake.asked] == [DOC + ".md", DOC]


def test_get_doc_reads_the_plain_address_when_md_is_html():
    fake, opener = web({DOC + ".md": HTML, DOC: HTML})
    assert get_doc(DOC, HOSTS, opener)[2] == DOC


def test_get_doc_reads_an_md_address_once():
    fake, opener = web({DOC + ".md": MD})
    assert get_doc(DOC + ".md", HOSTS, opener)[2] == DOC + ".md"
    assert [r.full_url for r in fake.asked] == [DOC + ".md"]


def test_get_doc_lets_the_plain_error_out():
    fake, opener = web({})
    with pytest.raises(OSError):
        get_doc(DOC, HOSTS, opener)


def test_get_doc_refuses_an_address_not_allowed():
    fake, opener = web({})
    with pytest.raises(ValueError):
        get_doc("https://example.com/docs/a", HOSTS, opener)
    assert fake.asked == []


def test_get_doc_sends_the_watcher_user_agent():
    fake, opener = web({DOC + ".md": MD})
    get_doc(DOC, HOSTS, opener)
    assert fake.asked[0].get_header("User-agent") == USER_AGENT


class Answer:
    """What `get` needs from a urlopen answer."""

    url = "https://example.com/changes"

    def __init__(self):
        self.headers = email.message.Message()
        self.headers["Content-Type"] = "text/plain; charset=utf-8"

    def read(self):
        return b"changes"

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_get_sends_the_watcher_user_agent(monkeypatch):
    asked = []

    def urlopen(request, timeout):
        asked.append(request)
        return Answer()

    monkeypatch.setattr(watch_pages.urllib.request, "urlopen", urlopen)
    assert get("https://example.com/changes") == ("changes", "text/plain")
    assert asked[0].full_url == "https://example.com/changes"
    assert asked[0].get_header("User-agent") == USER_AGENT
