"""Set Kitden's version for a release. No model, no network.

Run `python scripts/release_bump.py ROOT X.Y.Z`. X.Y.Z must be the next minor or the next patch
of the version in pyproject.toml. It edits the eight version places, uv.lock, and the ROADMAP
heading and date. Nothing is written unless every place can be found.
"""

import argparse
import re
import sys
import tomllib
from datetime import date
from pathlib import Path

PYPROJECT = "pyproject.toml"
ROADMAP = "ROADMAP.md"
NOT_YET = "### Not yet released"

# (file, pattern with the version in group 2, how many matches are expected)
PLACES = [
    (PYPROJECT, r'(?m)^(version = ")(\d+\.\d+\.\d+)(")', 1),
    ("src/kitden/__init__.py", r'(?m)^(__version__ = ")(\d+\.\d+\.\d+)(")', 1),
    ("plugins/kitden/.claude-plugin/plugin.json", r'(?m)^(  "version": ")(\d+\.\d+\.\d+)(")', 1),
    ("plugins/kitden/plugin.json", r'(?m)^(  "version": ")(\d+\.\d+\.\d+)(")', 1),
    # server.json has the top version and packages[0].version, two matches.
    ("server.json", r'(?m)^(\s+"version": ")(\d+\.\d+\.\d+)(")', 2),
    ("install.sh", r'(?m)^(KITDEN_VERSION=")(\d+\.\d+\.\d+)(")', 1),
    ("install.ps1", r'(?m)^(\$KitdenVersion = ")(\d+\.\d+\.\d+)(")', 1),
    # The kitden package block in uv.lock, so `uv sync --locked` keeps working.
    ("uv.lock", r'(?m)^(name = "kitden"\nversion = ")(\d+\.\d+\.\d+)(")', 1),
]


def next_versions(current: str) -> tuple[str, str]:
    """The next minor and the next patch version after `current`."""
    major, minor, patch = (int(part) for part in current.split("."))
    return f"{major}.{minor + 1}.0", f"{major}.{minor}.{patch + 1}"


def current_version(root: Path) -> str:
    return tomllib.loads((root / PYPROJECT).read_text())["project"]["version"]


def bump(root: Path, version: str, today: date | None = None) -> None:
    """Write `version` into every place. Raises ValueError, writing nothing, if one is missing."""
    today = today or date.today()
    new_texts: dict[Path, str] = {}
    for name, pattern, expected in PLACES:
        path = root / name
        if not path.is_file():
            raise ValueError(f"{name}: file not found")
        text = path.read_text()
        found = len(re.findall(pattern, text))
        if found != expected:
            raise ValueError(f"{name}: expected {expected} version line(s), found {found}")
        new_texts[path] = re.sub(pattern, rf"\g<1>{version}\g<3>", text)

    roadmap = root / ROADMAP
    if roadmap.is_file():
        text = roadmap.read_text()
        if re.search(rf"(?m)^{re.escape(NOT_YET)}[ \t]*$", text):
            text = re.sub(rf"(?m)^{re.escape(NOT_YET)}[ \t]*$", f"### {version}", text, count=1)
            text = re.sub(
                r"(?m)^Last updated: \d{4}-\d{2}-\d{2}$", f"Last updated: {today}", text, count=1
            )
            new_texts[roadmap] = text
        else:
            print(f'{ROADMAP}: no "{NOT_YET}" heading, left as it is')
    else:
        print(f"{ROADMAP}: not found, left as it is")

    for path, text in new_texts.items():
        path.write_text(text)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path, help="the Kitden checkout")
    parser.add_argument("version", help="the new version, like 1.2.3")
    args = parser.parse_args(argv)
    try:
        allowed = next_versions(current_version(args.root))
    except (OSError, KeyError, ValueError) as error:
        print(f"cannot read the current version: {error}")
        return 1
    if args.version not in allowed:
        print(f"version {args.version} must be one of {' or '.join(allowed)}")
        return 1
    try:
        bump(args.root, args.version)
    except ValueError as error:
        print(error)
        return 1
    print(f"Kitden is now {args.version}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
