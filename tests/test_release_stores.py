import json
import subprocess
import sys
from pathlib import Path

import release_stores
from release_stores import Row, behind, read_all, summary

STORES = Path(__file__).parent / "fixtures" / "release" / "stores"
SCRIPT = Path(__file__).parent.parent / "scripts" / "release_stores.py"
TAG = "v0.8.0"
OWNER = "KonstantinStarovoytov"
URLS = {
    "pypi": release_stores.PYPI,
    "release": release_stores.RELEASE.format(tag=TAG),
    "registry": release_stores.REGISTRY,
    "formula": release_stores.FORMULA,
    "branch": release_stores.COMMIT.format(ref="release"),
    "tag": release_stores.COMMIT.format(ref=TAG),
    "marketplace": release_stores.MARKETPLACE,
    "repo": release_stores.REPO,
    "listing": release_stores.LISTING.format(tag=TAG),
}
FILES = {
    "pypi": "pypi.json",
    "release": "github_release.json",
    "registry": "registry.json",
    "formula": "kitden.rb",
    "branch": "commit.json",
    "tag": "commit.json",
    "marketplace": "marketplace.json",
    "repo": "repo.json",
    "listing": "listing.toml",
}


def make_fetch(**changes):
    """A fake fetch over the recorded files. A change is new text, or None to make it fail."""
    bodies = {key: (STORES / name).read_text() for key, name in FILES.items()}
    bodies.update(changes)

    def fetch(url: str) -> str:
        for key, wanted in URLS.items():
            if url == wanted:
                if bodies[key] is None:
                    raise OSError(f"404 {url}")
                return bodies[key]
        raise AssertionError(f"unexpected url {url}")

    return fetch


def rows_by_place(**changes) -> dict[str, Row]:
    return {row.place: row for row in read_all(TAG, make_fetch(**changes))}


def test_all_current():
    rows = read_all(TAG, make_fetch())
    assert [row.place for row in rows] == [
        "PyPI",
        "GitHub release",
        "MCP Registry",
        "Homebrew formula",
        "release branch",
        "Marketplace entry",
        "GitHub description",
        "Claude directory",
        "Glama",
    ]
    assert [row.ok for row in rows] == [True] * 7 + [None, None]


def test_pypi_old_version():
    row = rows_by_place(pypi='{"info": {"version": "0.7.2"}}')["PyPI"]
    assert row.ok is False
    assert row.expected == "0.8.0"
    assert row.seen == "0.7.2"


def test_github_release_missing():
    assert rows_by_place(release=None)["GitHub release"].ok is False


def test_registry_old_version():
    data = json.loads((STORES / "registry.json").read_text())
    data["servers"] = [s for s in data["servers"] if s["server"]["version"] != "0.8.0"]
    data["servers"][-1]["_meta"]["io.modelcontextprotocol.registry/official"]["isLatest"] = True
    row = rows_by_place(registry=json.dumps(data))["MCP Registry"]
    assert row.ok is False
    assert "0.7.2" in row.seen


def test_registry_has_version_but_not_latest():
    data = json.loads((STORES / "registry.json").read_text())
    for server in data["servers"]:
        server["_meta"]["io.modelcontextprotocol.registry/official"]["isLatest"] = False
    assert rows_by_place(registry=json.dumps(data))["MCP Registry"].ok is False


def test_brew_old_version():
    formula = (
        (STORES / "kitden.rb").read_text().replace("kitden-0.8.0.tar.gz", "kitden-0.7.2.tar.gz")
    )
    row = rows_by_place(formula=formula)["Homebrew formula"]
    assert row.ok is False
    assert "0.7.2" in row.seen


def test_brew_bottles_old_root_url():
    formula = (
        (STORES / "kitden.rb")
        .read_text()
        .replace("/download/kitden-0.8.0", "/download/kitden-0.7.2")
    )
    row = rows_by_place(formula=formula)["Homebrew formula"]
    assert row.ok is False
    assert "kitden-0.7.2" in row.seen


def test_brew_desc_differs():
    formula = (STORES / "kitden.rb").read_text().replace("See and safely change", "Old words")
    assert rows_by_place(formula=formula)["Homebrew formula"].ok is False


def test_release_branch_behind_tag():
    other = '{"sha": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"}'
    assert rows_by_place(branch=other)["release branch"].ok is False


def test_release_branch_missing():
    row = rows_by_place(branch=None)["release branch"]
    assert row.ok is False
    assert "no release branch" in row.seen


def test_marketplace_ref_main():
    text = (STORES / "marketplace.json").read_text().replace('"release"', '"main"')
    row = rows_by_place(marketplace=text)["Marketplace entry"]
    assert row.ok is False
    assert row.seen == "main"


def test_marketplace_source_is_a_path():
    text = '{"plugins": [{"name": "kitden", "source": "./plugins/kitden"}]}'
    row = rows_by_place(marketplace=text)["Marketplace entry"]
    assert row.ok is False
    assert row.seen == "none"


def test_github_description_differs():
    row = rows_by_place(repo='{"description": "Something else"}')["GitHub description"]
    assert row.ok is False


def test_no_listing_yet_makes_description_rows_by_hand():
    rows = rows_by_place(listing=None)
    for place in ("Homebrew formula", "GitHub description"):
        assert rows[place].ok is None
        assert "listing.toml" in rows[place].seen
    assert rows["PyPI"].ok is True


def test_no_listing_does_not_hide_an_old_homebrew_version():
    formula = (
        (STORES / "kitden.rb").read_text().replace("kitden-0.8.0.tar.gz", "kitden-0.7.2.tar.gz")
    )
    assert rows_by_place(listing=None, formula=formula)["Homebrew formula"].ok is False


def test_a_failed_store_is_a_row_not_a_crash():
    row = rows_by_place(pypi=None)["PyPI"]
    assert row.ok is False
    assert "404" in row.seen


def test_hand_rows_are_none():
    rows = rows_by_place()
    assert rows["Claude directory"].ok is None
    assert rows["Glama"].ok is None


def test_behind_waits_48h_for_homebrew_only():
    rows = [
        Row("PyPI", "0.8.0", "0.7.2", False),
        Row("Homebrew formula", "0.8.0", "0.7.2", False),
        Row("MCP Registry", "0.8.0", "0.8.0", True),
        Row("Glama", "-", "check by hand", None),
    ]
    assert [r.place for r in behind(rows, 1)] == ["PyPI"]
    assert [r.place for r in behind(rows, 47.9)] == ["PyPI"]
    assert [r.place for r in behind(rows, 48)] == ["PyPI", "Homebrew formula"]


def test_summary_table():
    rows = [
        Row("PyPI", "0.8.0", "0.8.0", True),
        Row("MCP Registry", "0.8.0", "0.7.2", False),
        Row("Glama", "-", "check by hand", None),
    ]
    assert summary(rows).splitlines() == [
        "| Place | Expected | Seen | Status |",
        "| --- | --- | --- | --- |",
        "| PyPI | 0.8.0 | 0.8.0 | ok |",
        "| MCP Registry | 0.8.0 | 0.7.2 | behind |",
        "| Glama | - | check by hand | check by hand |",
    ]


def test_summary_keeps_a_pipe_from_breaking_the_table():
    line = summary([Row("PyPI", "a|b", "c", True)]).splitlines()[2]
    assert line == "| PyPI | a\\|b | c | ok |"


def test_cli_rejects_a_bad_tag():
    result = subprocess.run([sys.executable, str(SCRIPT), "0.8.0"], capture_output=True, text=True)
    assert result.returncode == 2
