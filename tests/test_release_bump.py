import json
import subprocess
import sys
from datetime import date
from pathlib import Path

from release_bump import bump, main, next_versions

SCRIPT = Path(__file__).parent.parent / "scripts" / "release_bump.py"
TODAY = date(2026, 12, 1)

PLUGIN = '{\n  "name": "kitden",\n  "version": "0.8.0",\n  "description": "x"\n}\n'
SERVER = (
    '{\n  "name": "io.github.x/kitden",\n  "version": "0.8.0",\n  "packages": [\n'
    '    {\n      "identifier": "kitden",\n      "version": "0.8.0"\n    }\n  ]\n}\n'
)
ROADMAP = (
    "# Kitden roadmap\n\nLast updated: 2026-11-12\n\n## Done\n\n### Not yet released\n\n"
    "- A thing.\n\n### 0.8.0\n\n- Older.\n"
)
FILES = {
    "pyproject.toml": '[project]\nname = "kitden"\nversion = "0.8.0"\n',
    "src/kitden/__init__.py": '"""Kitden."""\n\n__version__ = "0.8.0"\n',
    "plugins/kitden/.claude-plugin/plugin.json": PLUGIN,
    "plugins/kitden/plugin.json": PLUGIN,
    "server.json": SERVER,
    "install.sh": '#!/bin/sh\nKITDEN_VERSION="0.8.0"\nuv tool install "kitden==$KITDEN_VERSION"\n',
    "install.ps1": '$KitdenVersion = "0.8.0"\nuv tool install "kitden==$KitdenVersion"\n',
    "uv.lock": (
        'version = 1\n\n[[package]]\nname = "other"\nversion = "0.8.0"\n\n'
        '[[package]]\nname = "kitden"\nversion = "0.8.0"\nsource = { editable = "." }\n'
    ),
    "ROADMAP.md": ROADMAP,
}


def make_root(tmp_path: Path, roadmap: str = ROADMAP) -> Path:
    for name, text in FILES.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(roadmap if name == "ROADMAP.md" else text)
    return tmp_path


def test_next_versions():
    assert next_versions("0.8.0") == ("0.9.0", "0.8.1")
    assert next_versions("1.9.4") == ("1.10.0", "1.9.5")


def test_bump_sets_eight_places(tmp_path):
    root = make_root(tmp_path)
    bump(root, "0.9.0", today=TODAY)
    read = lambda name: (root / name).read_text()  # noqa: E731
    assert 'version = "0.9.0"' in read("pyproject.toml")
    assert '__version__ = "0.9.0"' in read("src/kitden/__init__.py")
    for name in ("plugins/kitden/.claude-plugin/plugin.json", "plugins/kitden/plugin.json"):
        assert json.loads(read(name))["version"] == "0.9.0"
    server = json.loads(read("server.json"))
    assert server["version"] == "0.9.0"
    assert server["packages"][0]["version"] == "0.9.0"
    assert 'KITDEN_VERSION="0.9.0"' in read("install.sh")
    assert '$KitdenVersion = "0.9.0"' in read("install.ps1")
    lock = read("uv.lock")
    assert 'name = "kitden"\nversion = "0.9.0"' in lock
    assert 'name = "other"\nversion = "0.8.0"' in lock
    assert "0.8.0" not in read("pyproject.toml")


def test_bump_moves_roadmap_heading(tmp_path):
    root = make_root(tmp_path)
    bump(root, "0.9.0", today=TODAY)
    text = (root / "ROADMAP.md").read_text()
    assert "### 0.9.0\n\n- A thing." in text
    assert "Not yet released" not in text
    assert "Last updated: 2026-12-01" in text
    assert "### 0.8.0" in text


def test_bump_leaves_roadmap_without_heading(tmp_path, capsys):
    plain = "# Kitden roadmap\n\nLast updated: 2026-11-12\n\n### 0.8.0\n"
    root = make_root(tmp_path, roadmap=plain)
    bump(root, "0.9.0", today=TODAY)
    assert (root / "ROADMAP.md").read_text() == plain
    assert "Not yet released" in capsys.readouterr().out


def test_cli_refuses_other_version(tmp_path, capsys):
    root = make_root(tmp_path)
    assert main([str(root), "2.0.0"]) == 1
    assert "0.9.0" in capsys.readouterr().out
    assert 'version = "0.8.0"' in (root / "pyproject.toml").read_text()
    result = subprocess.run(
        [sys.executable, str(SCRIPT), str(root), "0.8.1"], capture_output=True, text=True
    )
    assert result.returncode == 0
    assert 'version = "0.8.1"' in (root / "pyproject.toml").read_text()


def test_cli_refuses_missing_place(tmp_path, capsys):
    root = make_root(tmp_path)
    (root / "install.sh").write_text("nothing\n")
    assert main([str(root), "0.9.0"]) == 1
    assert "install.sh" in capsys.readouterr().out
    assert 'version = "0.8.0"' in (root / "pyproject.toml").read_text()
