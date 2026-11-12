import io
import json
import urllib.error
from pathlib import Path

import pytest

import release_publish
from release_publish import (
    DIRECTORY,
    bump,
    hand_steps,
    must_pass,
    needs_tag,
    registry_has,
    sdist,
    valid_version,
    wait_for_pypi,
)
from release_stores import Row

VERSION = "0.8.1"


def not_found(url: str) -> urllib.error.HTTPError:
    return urllib.error.HTTPError(url, 404, "Not Found", {}, io.BytesIO(b""))


def test_valid_version():
    assert valid_version("0.8.1") == "0.8.1"
    for bad in ("v0.8.1", "0.8", "0.8.1\n", "0.8.1; rm -rf /", "", "1.2.3.4"):
        with pytest.raises(ValueError):
            valid_version(bad)


def test_autotag_needs_new_version_and_notes():
    assert needs_tag(VERSION, {"v0.8.0", "v0.7.2"}, notes_exist=True) is True
    # No notes yet: the version was bumped, but the release PR is not merged.
    assert needs_tag(VERSION, {"v0.8.0"}, notes_exist=False) is False


def test_autotag_skips_existing_tag():
    assert needs_tag(VERSION, {"v0.8.0", "v0.8.1"}, notes_exist=True) is False


def test_wait_for_pypi_times_out_with_message():
    waited = []

    def fetch(url):
        raise not_found(url)

    with pytest.raises(SystemExit) as stop:
        wait_for_pypi(VERSION, fetch, waited.append, timeout_s=90)
    assert str(stop.value) == "PyPI does not serve kitden 0.8.1 yet; re-run this job"
    assert sum(waited) <= 90 and waited


def test_wait_for_pypi_returns_when_served():
    answers = [not_found, not_found, lambda url: json.dumps({"info": {"version": VERSION}})]
    asked, waited = [], []

    def fetch(url):
        asked.append(url)
        answer = answers.pop(0)(url)
        if isinstance(answer, Exception):
            raise answer
        return answer

    wait_for_pypi(VERSION, fetch, waited.append, timeout_s=900)
    assert asked == ["https://pypi.org/pypi/kitden/0.8.1/json"] * 3
    assert len(waited) == 2


def test_wait_for_pypi_keeps_waiting_on_network_errors():
    calls = []

    def fetch(url):
        calls.append(url)
        if len(calls) == 1:
            raise OSError("connection reset")
        return json.dumps({"info": {"version": VERSION}})

    wait_for_pypi(VERSION, fetch, lambda s: None)
    assert len(calls) == 2


def test_registry_skips_published():
    entry = {"server": {"name": release_publish.MCP_NAME, "version": VERSION}}

    def fetch(url):
        assert url == (
            "https://registry.modelcontextprotocol.io/v0/servers/"
            "io.github.KonstantinStarovoytov%2Fkitden/versions/0.8.1"
        )
        return json.dumps(entry)

    assert registry_has(VERSION, fetch) is True


def test_registry_has_not_when_not_found():
    def fetch(url):
        raise not_found(url)

    assert registry_has(VERSION, fetch) is False


def test_registry_has_raises_on_other_errors():
    def fetch(url):
        raise urllib.error.HTTPError(url, 503, "Unavailable", {}, io.BytesIO(b""))

    with pytest.raises(urllib.error.HTTPError):
        registry_has(VERSION, fetch)


def test_sdist_reads_url_and_sha256():
    data = {
        "urls": [
            {
                "packagetype": "bdist_wheel",
                "url": "https://x/kitden-0.8.1-py3-none-any.whl",
                "digests": {"sha256": "a" * 64},
            },
            {
                "packagetype": "sdist",
                "url": "https://files.pythonhosted.org/kitden-0.8.1.tar.gz",
                "digests": {"sha256": "b" * 64},
            },
        ]
    }
    asked = []

    def fetch(url):
        asked.append(url)
        return json.dumps(data)

    assert sdist(VERSION, fetch) == ("https://files.pythonhosted.org/kitden-0.8.1.tar.gz", "b" * 64)
    assert asked == ["https://pypi.org/pypi/kitden/0.8.1/json"]


def test_sdist_refuses_a_missing_sdist():
    with pytest.raises(ValueError, match="no sdist"):
        sdist(VERSION, lambda url: json.dumps({"urls": []}))


def rows(**not_ok) -> list[Row]:
    places = [
        "PyPI",
        "GitHub release",
        "MCP Registry",
        "Homebrew formula",
        "release branch",
        "Marketplace entry",
        "GitHub description",
    ]
    result = [Row(place, "x", not_ok.get(place, "x"), place not in not_ok) for place in places]
    return [*result, Row("Claude directory", "-", "check by hand", None)]


def test_must_pass_all_ok():
    assert must_pass(rows()) == []


def test_must_pass_names_the_four_places_only():
    problems = must_pass(
        rows(**{"MCP Registry": "latest 0.8.0", "Homebrew formula": "0.8.0", "PyPI": "0.8.0"})
    )
    assert problems == [
        "PyPI: expected x, seen 0.8.0",
        "MCP Registry: expected x, seen latest 0.8.0",
    ]


def test_must_pass_reports_a_missing_place():
    problems = must_pass([row for row in rows() if row.place != "release branch"])
    assert problems == ["release branch: not read"]


def test_hand_steps_for_listing_or_privacy():
    for changed in (["listing.toml"], ["src/kitden/x.py", "PRIVACY.md"]):
        steps = hand_steps(changed)
        assert len(steps) == 1
        assert DIRECTORY in steps[0]


def test_hand_steps_none_for_other_files():
    assert hand_steps([]) == []
    assert hand_steps(["src/kitden/x.py", "docs/listing.toml.md", "plugins/PRIVACY.md"]) == []


FORMULA = Path(__file__).parent / "fixtures" / "release" / "kitden.rb"
NEW_URL = "https://files.pythonhosted.org/packages/aa/bb/kitden-0.8.1.tar.gz"


def pypi_fetch(url):
    assert url == "https://pypi.org/pypi/kitden/0.8.1/json"
    return json.dumps(
        {"urls": [{"packagetype": "sdist", "url": NEW_URL, "digests": {"sha256": "c" * 64}}]}
    )


def test_bump_takes_desc_from_listing(tmp_path):
    formula = tmp_path / "kitden.rb"
    formula.write_text(FORMULA.read_text())
    listing = tmp_path / "listing.toml"
    listing.write_text('short = "s"\nbrew = "New brew words"\n')
    assert bump(formula, VERSION, listing, pypi_fetch) is True
    text = formula.read_text()
    assert f'  url "{NEW_URL}"' in text and f'  sha256 "{"c" * 64}"' in text
    assert '  desc "New brew words"' in text


def test_bump_keeps_desc_without_listing(tmp_path):
    formula = tmp_path / "kitden.rb"
    formula.write_text(FORMULA.read_text())
    assert bump(formula, VERSION, None, pypi_fetch) is True
    assert '  desc "See and safely change what AI coding clients load on this computer"' in (
        formula.read_text()
    )


def test_bump_skips_a_formula_at_the_version(tmp_path):
    formula = tmp_path / "kitden.rb"
    formula.write_text(FORMULA.read_text())

    def fetch(url):
        raise AssertionError("PyPI is not asked")

    assert bump(formula, "0.8.0", None, fetch) is False
    assert formula.read_text() == FORMULA.read_text()


def test_cli_refuses_a_bad_version(capsys):
    assert release_publish.main(["check-version", "0.8.1$(id)"]) == 2
    assert release_publish.main(["summary", "0.8.1", "--changed", "x", "--out", "y"]) == 2
    assert release_publish.main(["check-version", VERSION]) == 0
    assert capsys.readouterr().out == "0.8.1\n"


def test_cli_needs_tag(tmp_path, capsys):
    tags = tmp_path / "tags"
    tags.write_text("v0.8.0\nv0.7.2\n")
    notes = tmp_path / "v0.8.1.md"
    args = ["needs-tag", VERSION, "--tags", str(tags), "--notes", str(notes)]
    assert release_publish.main(args) == 0  # no notes file
    notes.write_text("")
    assert release_publish.main(args) == 0  # an empty notes file
    notes.write_text("## New\n")
    assert release_publish.main(args) == 0
    assert capsys.readouterr().out == "false\nfalse\ntrue\n"
