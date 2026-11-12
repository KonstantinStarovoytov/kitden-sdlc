import re
import shutil
from pathlib import Path

import yaml

from release_check import check

REPO = Path(__file__).parent.parent
SKILLS = REPO / "plugins" / "kitden-sdlc" / "skills"
FIXTURE = Path(__file__).parent / "fixtures" / "release" / "kitden"
FENCE = re.compile(r"^(`{3,})([a-z]*)\n(.*?)^\1$", re.MULTILINE | re.DOTALL)


def frontmatter(path: Path) -> dict:
    text = path.read_text()
    assert text.startswith("---\n"), f"{path}: no frontmatter"
    return yaml.safe_load(text.split("---\n", 2)[1])


def notes_example() -> str:
    text = (SKILLS / "release-notes" / "SKILL.md").read_text()
    blocks = [body for _, lang, body in FENCE.findall(text) if lang == "markdown"]
    assert len(blocks) == 1, "the release-notes skill must hold one ```markdown example"
    return blocks[0]


def test_skills_have_frontmatter():
    files = sorted(SKILLS.glob("*/SKILL.md"))
    names = {path.parent.name for path in files}
    assert {"review-kitden", "release-notes", "readme-kitden"} <= names
    for path in files:
        meta = frontmatter(path)
        assert meta.get("name") == path.parent.name, path
        assert isinstance(meta.get("description"), str) and meta["description"].strip(), path


def test_notes_example_passes_check(tmp_path):
    example = notes_example()
    version = re.match(r"# Kitden (\d+\.\d+\.\d+) — ", example).group(1)
    root = tmp_path / "kitden"
    shutil.copytree(FIXTURE, root)
    pyproject = root / "pyproject.toml"
    pyproject.write_text(
        pyproject.read_text().replace('version = "1.2.3"', f'version = "{version}"')
    )
    (root / "docs" / "releases" / f"v{version}.md").write_text(example)

    assert check(root, f"v{version}") == []
    assert "<summary>Other changes</summary>" in example
