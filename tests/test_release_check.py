import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from release_check import LIMITS, check, load_listing, main

FIXTURE = Path(__file__).parent / "fixtures" / "release" / "kitden"
SCRIPT = Path(__file__).parent.parent / "scripts" / "release_check.py"
CLAUDE = "plugins/kitden/.claude-plugin/plugin.json"
CODEX = "plugins/kitden/plugin.json"
MARKET = ".claude-plugin/marketplace.json"


def copy_fixture(tmp_path: Path) -> Path:
    root = tmp_path / "kitden"
    shutil.copytree(FIXTURE, root)
    return root


def set_json(path: Path, key: str, value) -> None:
    data = json.loads(path.read_text())
    data[key] = value
    path.write_text(json.dumps(data))


def edit(path: Path, old: str, new: str) -> None:
    text = path.read_text()
    assert old in text
    path.write_text(text.replace(old, new))


def set_brew(root: Path, text: str) -> None:
    lines = (root / "listing.toml").read_text().splitlines()
    lines = [f'brew = "{text}"' if line.startswith("brew =") else line for line in lines]
    (root / "listing.toml").write_text("\n".join(lines) + "\n")


def test_fixture_passes():
    assert check(FIXTURE) == []
    assert check(FIXTURE, "v1.2.3") == []


def test_limits_and_listing():
    assert LIMITS == {"server": 100, "brew": 80}
    assert load_listing(FIXTURE)["display_name"] == "Kitden"


def test_short_text_differs(tmp_path):
    root = copy_fixture(tmp_path)
    set_json(root / "server.json", "description", "Other")
    assert check(root) == ["server.json: description differs from listing.toml short"]


def test_pyproject_short_differs(tmp_path):
    root = copy_fixture(tmp_path)
    edit(root / "pyproject.toml", 'description = "Shows', 'description = "Show')
    assert check(root) == ["pyproject.toml: description differs from listing.toml short"]


def test_pypi_summary_has_a_line_break(tmp_path):
    root = copy_fixture(tmp_path)
    edit(root / "listing.toml", 'short = "Shows what', 'short = "Shows\\nwhat')
    edit(root / "pyproject.toml", 'description = "Shows what', 'description = "Shows\\nwhat')
    edit(root / "server.json", '"description": "Shows what', '"description": "Shows\\nwhat')
    assert check(root) == ["pyproject.toml: description has a line break"]


def test_server_description_over_limit(tmp_path):
    root = copy_fixture(tmp_path)
    long = "x" * 101  # the text is this plus the fixture's 99 characters
    edit(root / "listing.toml", 'short = "', f'short = "{long}')
    edit(root / "pyproject.toml", 'description = "', f'description = "{long}')
    edit(root / "server.json", '"description": "', f'"description": "{long}')
    problems = check(root)
    assert len(problems) == 1
    assert problems[0].startswith("server.json: description")
    assert "100" in problems[0]
    assert str(len(long) + 99) in problems[0]


def test_tagline_differs(tmp_path):
    root = copy_fixture(tmp_path)
    set_json(root / MARKET, "description", "Other")
    assert check(root) == [f"{MARKET}: description differs from listing.toml tagline"]


def test_plugin_text_differs(tmp_path):
    root = copy_fixture(tmp_path)
    for name in (CLAUDE, CODEX):
        set_json(root / name, "description", "Other")
    assert check(root) == [
        f"{CODEX}: description differs from listing.toml plugin",
        f"{CLAUDE}: description differs from listing.toml plugin",
    ]


def test_marketplace_plugin_entry_differs(tmp_path):
    root = copy_fixture(tmp_path)
    path = root / MARKET
    data = json.loads(path.read_text())
    data["plugins"][0]["description"] = "Other"
    data["plugins"][0]["displayName"] = "Other"
    data["plugins"][0]["keywords"] = ["other"]
    path.write_text(json.dumps(data))
    assert check(root) == [
        f"{MARKET}: plugins[0] description differs from listing.toml plugin",
        f"{MARKET}: plugins[0] displayName differs from listing.toml display_name",
        f"{MARKET}: plugins[0] keywords differ from listing.toml keywords",
    ]


def test_display_name_and_keywords_differ(tmp_path):
    root = copy_fixture(tmp_path)
    set_json(root / CLAUDE, "displayName", "Other")
    set_json(root / CLAUDE, "keywords", ["other"])
    set_json(root / CODEX, "keywords", ["other"])
    problems = check(root)
    assert f"{CLAUDE}: displayName differs from listing.toml display_name" in problems
    assert f"{CLAUDE}: keywords differ from listing.toml keywords" in problems
    assert f"{CODEX}: keywords differ from listing.toml keywords" in problems


@pytest.mark.parametrize(
    ("text", "reason"),
    [
        ("x" * 81, "81 characters"),
        ("Show what clients load.", "period"),
        ("A tool for clients", "article"),
        ("An app for clients", "article"),
        ("The client viewer", "article"),
        ("Shows what KITDEN loads", "Kitden"),
    ],
)
def test_brew_text_breaks_audit(tmp_path, text, reason):
    root = copy_fixture(tmp_path)
    set_brew(root, text)
    problems = check(root)
    assert len(problems) == 1
    assert problems[0].startswith("listing.toml: brew")
    assert reason in problems[0]


def test_brew_text_of_80_characters_passes(tmp_path):
    root = copy_fixture(tmp_path)
    set_brew(root, "x" * 80)
    assert check(root) == []


def test_readme_lacks_mcp_name(tmp_path):
    root = copy_fixture(tmp_path)
    (root / "README.md").write_text("# Kitden\n")
    assert check(root) == ["README.md: no mcp-name: io.github.KonstantinStarovoytov/kitden line"]


def test_notes_missing_on_tag(tmp_path):
    root = copy_fixture(tmp_path)
    shutil.copy(root / "docs/releases/v1.2.3.md", root / "docs/releases/v1.2.4.md")
    (root / "docs/releases/v1.2.3.md").unlink()
    assert check(root, "v1.2.3") == ["docs/releases/v1.2.3.md: missing"]


def test_notes_need_house_headings(tmp_path):
    root = copy_fixture(tmp_path)
    notes = root / "docs/releases/v1.2.3.md"
    notes.write_text("# Release 1.2.3\n\nText.\n")
    assert check(root, "v1.2.3") == [
        'docs/releases/v1.2.3.md: title must start with "# Kitden 1.2.3 — "',
        'docs/releases/v1.2.3.md: no "## Upgrade and limits" heading',
        'docs/releases/v1.2.3.md: no "**Full changelog:**" line',
    ]


def test_notes_sections_are_optional(tmp_path):
    root = copy_fixture(tmp_path)
    notes = root / "docs/releases/v1.2.3.md"
    notes.write_text(
        "# Kitden 1.2.3 — x\n\n## New\n\n- a\n\n## Better\n\n- b\n\n## Documentation\n\n- c\n\n"
        "## Upgrade and limits\n\nText.\n\n**Full changelog:** https://example.com\n"
    )
    assert check(root, "v1.2.3") == []


def test_tag_differs_from_pyproject(tmp_path):
    root = copy_fixture(tmp_path)
    shutil.copy(root / "docs/releases/v1.2.3.md", root / "docs/releases/v1.2.4.md")
    edit(root / "docs/releases/v1.2.4.md", "Kitden 1.2.3 —", "Kitden 1.2.4 —")
    assert check(root, "v1.2.4") == ["tag v1.2.4 differs from pyproject.toml version 1.2.3"]


def test_tag_must_look_like_a_version(tmp_path):
    assert check(FIXTURE, "1.2.3") == ['tag 1.2.3 must look like "vX.Y.Z"']


def test_tag_skips_the_version_fields_of_other_files(tmp_path):
    root = copy_fixture(tmp_path)
    set_json(root / "server.json", "version", "9.9.9")
    set_json(root / CODEX, "version", "9.9.9")
    assert check(root, "v1.2.3") == [
        f"{CODEX}: version differs from {CLAUDE}",
    ]


@pytest.mark.parametrize("field", ["name", "description", "author", "homepage", "license"])
def test_plugin_files_share_fields(tmp_path, field):
    root = copy_fixture(tmp_path)
    set_json(root / CODEX, field, "other" if field != "author" else {"name": "Other"})
    problems = check(root)
    assert f"{CODEX}: {field} differs from {CLAUDE}" in problems


def test_plugin_files_share_repository_version_and_keywords(tmp_path):
    root = copy_fixture(tmp_path)
    set_json(root / CODEX, "repository", "https://example.com")
    set_json(root / CODEX, "version", "0.0.1")
    set_json(root / CODEX, "keywords", ["a"])
    problems = check(root)
    for field in ("repository", "version", "keywords"):
        assert f"{CODEX}: {field} differs from {CLAUDE}" in problems


def test_claude_only_fields_may_differ(tmp_path):
    root = copy_fixture(tmp_path)
    set_json(root / CLAUDE, "icon", "./other.png")
    set_json(root / CLAUDE, "privacyPolicyUrl", "https://example.com")
    assert check(root) == []


def test_missing_file_is_a_problem(tmp_path):
    root = copy_fixture(tmp_path)
    (root / "server.json").unlink()
    assert check(root) == ["server.json: missing"]


def test_bad_json_is_a_problem(tmp_path):
    root = copy_fixture(tmp_path)
    (root / "server.json").write_text("{")
    assert check(root) == ["server.json: not valid JSON"]


def test_cli_exit_codes(tmp_path, capsys):
    assert main([str(FIXTURE)]) == 0
    assert capsys.readouterr().out == ""

    root = copy_fixture(tmp_path)
    set_json(root / "server.json", "description", "Other")
    (root / "README.md").write_text("# Kitden\n")
    assert main([str(root)]) == 1
    out = capsys.readouterr().out.splitlines()
    assert out == [
        "server.json: description differs from listing.toml short",
        "README.md: no mcp-name: io.github.KonstantinStarovoytov/kitden line",
    ]


def test_cli_tag_option(tmp_path, capsys):
    assert main([str(FIXTURE), "--tag", "v1.2.3"]) == 0
    assert main([str(FIXTURE), "--tag", "v1.2.4"]) == 1
    assert "differs from pyproject.toml" in capsys.readouterr().out


def test_script_runs_from_the_command_line():
    done = subprocess.run(  # noqa: S603
        [sys.executable, str(SCRIPT), str(FIXTURE)], capture_output=True, text=True
    )
    assert done.returncode == 0
