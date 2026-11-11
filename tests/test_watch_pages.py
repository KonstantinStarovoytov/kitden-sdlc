import pytest

from watch_pages import get, releases, sections


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
