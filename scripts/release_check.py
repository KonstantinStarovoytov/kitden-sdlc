"""Check that Kitden's names and descriptions agree across its files and fit each store.

Kitden's CI runs this on every pull request and every tag. The limits are in
docs/platform-rules.md, with their sources.
"""

import argparse
import json
import re
import sys
import tomllib
from pathlib import Path

# See docs/platform-rules.md. "server" is the MCP Registry's limit for server.json
# `description`; "brew" is the longest `desc` that `brew audit` accepts.
LIMITS = {"server": 100, "brew": 80}
MCP_NAME = "io.github.KonstantinStarovoytov/kitden"
TAG = re.compile(r"v(\d+\.\d+\.\d+)\Z")
# Fields that both plugin.json schemas allow. The Claude file adds more (icon, displayName...).
SHARED_PLUGIN_FIELDS = (
    "name",
    "version",
    "description",
    "author",
    "homepage",
    "repository",
    "license",
    "keywords",
)
PYPROJECT = "pyproject.toml"
SERVER = "server.json"
MARKETPLACE = ".claude-plugin/marketplace.json"
CODEX = "plugins/kitden/plugin.json"
CLAUDE = "plugins/kitden/.claude-plugin/plugin.json"
LISTING = "listing.toml"

_MISSING = object()


def load_listing(root: Path) -> dict:
    return tomllib.loads((root / LISTING).read_text())


def _read(root: Path, name: str, problems: list[str]) -> dict | None:
    """Read a TOML or JSON file. On any problem add it to `problems` and return None."""
    try:
        text = (root / name).read_text()
        return tomllib.loads(text) if name.endswith(".toml") else json.loads(text)
    except OSError:
        problems.append(f"{name}: missing")
    except (ValueError, tomllib.TOMLDecodeError):
        kind = "TOML" if name.endswith(".toml") else "JSON"
        problems.append(f"{name}: not valid {kind}")
    return None


def _differs(problems: list[str], where: str, field: str, value, wanted, source: str) -> None:
    if value != wanted:
        verb = "differ" if field.endswith("keywords") else "differs"
        problems.append(f"{where}: {field} {verb} from {source}")


def _check_brew(brew: str) -> list[str]:
    where = f"{LISTING}: brew"
    problems = []
    if len(brew) > LIMITS["brew"]:
        problems.append(f"{where} is {len(brew)} characters, over the limit of {LIMITS['brew']}")
    if brew.endswith("."):
        problems.append(f"{where} ends with a period")
    if re.match(r"(?:a|an|the)\s", brew, re.IGNORECASE):
        problems.append(f'{where} starts with an article ("A", "An" or "The")')
    if "kitden" in brew.lower():
        problems.append(f'{where} contains the formula name "Kitden"')
    return problems


def _check_notes(root: Path, tag: str, version: str) -> list[str]:
    name = f"docs/releases/{tag}.md"
    try:
        lines = (root / name).read_text().splitlines()
    except OSError:
        return [f"{name}: missing"]
    problems = []
    title = f"# Kitden {version} — "
    if not (lines and lines[0].startswith(title)):
        problems.append(f'{name}: title must start with "{title}"')
    if "## Upgrade and limits" not in lines:
        problems.append(f'{name}: no "## Upgrade and limits" heading')
    if not any(line.startswith("**Full changelog:**") for line in lines):
        problems.append(f'{name}: no "**Full changelog:**" line')
    return problems


def _check_plugins(root: Path, listing: dict) -> list[str]:
    problems: list[str] = []
    codex = _read(root, CODEX, problems)
    claude = _read(root, CLAUDE, problems)
    market = _read(root, MARKETPLACE, problems)
    source = "listing.toml"
    if codex and claude:
        for field in SHARED_PLUGIN_FIELDS:
            if codex.get(field, _MISSING) != claude.get(field, _MISSING):
                problems.append(f"{CODEX}: {field} differs from {CLAUDE}")
    if codex:
        _differs(
            problems,
            CODEX,
            "description",
            codex.get("description"),
            listing["plugin"],
            f"{source} plugin",
        )
        _differs(
            problems,
            CODEX,
            "keywords",
            codex.get("keywords"),
            listing["keywords"],
            f"{source} keywords",
        )
    if claude:
        _differs(
            problems,
            CLAUDE,
            "description",
            claude.get("description"),
            listing["plugin"],
            f"{source} plugin",
        )
        _differs(
            problems,
            CLAUDE,
            "displayName",
            claude.get("displayName"),
            listing["display_name"],
            f"{source} display_name",
        )
        _differs(
            problems,
            CLAUDE,
            "keywords",
            claude.get("keywords"),
            listing["keywords"],
            f"{source} keywords",
        )
    if market:
        _differs(
            problems,
            MARKETPLACE,
            "description",
            market.get("description"),
            listing["tagline"],
            f"{source} tagline",
        )
        entries = market.get("plugins")
        entry = entries[0] if isinstance(entries, list) and entries else {}
        _differs(
            problems,
            MARKETPLACE,
            "plugins[0] description",
            entry.get("description"),
            listing["plugin"],
            f"{source} plugin",
        )
        _differs(
            problems,
            MARKETPLACE,
            "plugins[0] displayName",
            entry.get("displayName"),
            listing["display_name"],
            f"{source} display_name",
        )
        _differs(
            problems,
            MARKETPLACE,
            "plugins[0] keywords",
            entry.get("keywords"),
            listing["keywords"],
            f"{source} keywords",
        )
    return problems


def check(root: Path, tag: str | None = None) -> list[str]:
    """Return what is wrong in the Kitden tree at `root`, one string per problem that names
    the file and the field. An empty list means it passes. With `tag` (like "v1.2.3"),
    also check the tag and that tag's release notes."""
    problems: list[str] = []
    listing = _read(root, LISTING, problems)
    if listing is None:
        return problems
    pyproject = _read(root, PYPROJECT, problems)
    server = _read(root, SERVER, problems)
    project = (pyproject or {}).get("project", {})

    if pyproject:
        _differs(
            problems,
            PYPROJECT,
            "description",
            project.get("description"),
            listing["short"],
            "listing.toml short",
        )
        if "\n" in str(project.get("description", "")) or "\r" in str(project.get("description")):
            problems.append(f"{PYPROJECT}: description has a line break")
    if server:
        description = server.get("description")
        _differs(
            problems, SERVER, "description", description, listing["short"], "listing.toml short"
        )
        if isinstance(description, str) and len(description) > LIMITS["server"]:
            problems.append(
                f"{SERVER}: description is {len(description)} characters, "
                f"over the limit of {LIMITS['server']}"
            )
    problems += _check_plugins(root, listing)
    problems += _check_brew(listing["brew"])

    try:
        readme = (root / "README.md").read_text()
    except OSError:
        problems.append("README.md: missing")
    else:
        if f"<!-- mcp-name: {MCP_NAME} -->" not in readme:
            problems.append(f"README.md: no mcp-name: {MCP_NAME} line")

    if tag is not None:
        found = TAG.match(tag)
        if not found:
            problems.append(f'tag {tag} must look like "vX.Y.Z"')
        else:
            version = found.group(1)
            # The other version fields are checked by Kitden's own test_release_files.py.
            if pyproject and project.get("version") != version:
                problems.append(
                    f"tag {tag} differs from {PYPROJECT} version {project.get('version')}"
                )
            problems += _check_notes(root, tag, version)
    return problems


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path, help="the Kitden checkout")
    parser.add_argument("--tag", help="the release tag, like v1.2.3")
    args = parser.parse_args(argv)
    problems = check(args.root, args.tag)
    for problem in problems:
        print(problem)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
