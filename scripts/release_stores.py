"""Read Kitden's version in every store and say which is behind or different.

No model and no secrets: every store here is public. Run `python scripts/release_stores.py
vX.Y.Z` to print the table (the release workflow writes it to the job summary).
"""

import json
import os
import re
import sys
import tomllib
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass

Fetch = Callable[[str], str]

OWNER = "KonstantinStarovoytov"
PYPI = "https://pypi.org/pypi/kitden/json"
RELEASE = f"https://api.github.com/repos/{OWNER}/kitden/releases/tags/{{tag}}"
REGISTRY = f"https://registry.modelcontextprotocol.io/v0/servers?search=io.github.{OWNER}/kitden"
FORMULA = f"https://raw.githubusercontent.com/{OWNER}/homebrew-tap/main/Formula/kitden.rb"
COMMIT = f"https://api.github.com/repos/{OWNER}/kitden/commits/{{ref}}"
MARKETPLACE = (
    f"https://raw.githubusercontent.com/{OWNER}/kitden/main/.claude-plugin/marketplace.json"
)
REPO = f"https://api.github.com/repos/{OWNER}/kitden"
LISTING = f"https://raw.githubusercontent.com/{OWNER}/kitden/{{tag}}/listing.toml"

MCP_NAME = f"io.github.{OWNER}/kitden"
OFFICIAL = "io.modelcontextprotocol.registry/official"
TAG = re.compile(r"v(\d+\.\d+\.\d+)\Z")
HOMEBREW = "Homebrew formula"
HOMEBREW_WAIT_HOURS = 48
BY_HAND = "check by hand"


@dataclass
class Row:
    place: str
    expected: str
    seen: str
    ok: bool | None  # None means check by hand


def build_request(url: str, token: str | None) -> urllib.request.Request:
    """The request for `url`. The GitHub token goes to api.github.com only, never elsewhere."""
    if not url.startswith("https://"):
        raise ValueError(f"only https URLs: {url}")
    headers = {"User-Agent": "kitden-sdlc-release"}
    if token and urllib.parse.urlsplit(url).hostname == "api.github.com":
        headers["Authorization"] = f"Bearer {token}"
    return urllib.request.Request(url, headers=headers)  # noqa: S310


def fetch_url(url: str) -> str:
    request = build_request(url, os.environ.get("GITHUB_TOKEN"))
    with urllib.request.urlopen(request, timeout=20) as response:  # noqa: S310
        return response.read().decode()


def _row(place: str, expected: str, read: Callable[[], tuple[str, bool | None]]) -> Row:
    """Run `read`, which returns (seen, ok). A store that cannot be read is a row, not a crash."""
    try:
        seen, ok = read()
    except (OSError, ValueError, KeyError, IndexError, TypeError, AttributeError) as error:
        return Row(place, expected, f"could not read: {error}", False)
    return Row(place, expected, seen, ok)


def _pypi(version: str, fetch: Fetch) -> tuple[str, bool]:
    seen = json.loads(fetch(PYPI))["info"]["version"]
    return seen, seen == version


def _release(tag: str, fetch: Fetch) -> tuple[str, bool]:
    fetch(RELEASE.format(tag=tag))
    return f"{tag} exists", True


def _registry(version: str, fetch: Fetch) -> tuple[str, bool]:
    entries = json.loads(fetch(REGISTRY))["servers"]
    latest = [
        e["server"]["version"]
        for e in entries
        if e["server"]["name"] == MCP_NAME and e["_meta"][OFFICIAL]["isLatest"]
    ]
    if not latest:
        return "no latest version", False
    return f"latest {latest[0]}", latest[0] == version


def _homebrew(version: str, listing: dict | None, fetch: Fetch) -> tuple[str, bool | None]:
    text = fetch(FORMULA)
    url = re.search(r'^  url "[^"]*/kitden-([^/"]+)\.tar\.gz"', text, re.MULTILINE)
    root = re.search(r'root_url "[^"]*/kitden-([^/"]+)"', text)
    desc = re.search(r'^  desc "([^"]*)"', text, re.MULTILINE)
    seen_version = url.group(1) if url else "no url"
    seen_root = root.group(1) if root else "no bottle"
    seen = f"{seen_version}, bottles kitden-{seen_root}"
    if seen_version != version or seen_root != version:
        return seen, False
    if listing is None:
        return f"{seen}; desc not checked (no listing.toml)", None
    if (desc.group(1) if desc else None) != listing["brew"]:
        return f"{seen}; desc differs from listing.toml brew", False
    return seen, True


def _branch(tag: str, fetch: Fetch) -> tuple[str, bool]:
    try:
        branch = json.loads(fetch(COMMIT.format(ref="release")))["sha"]
    except OSError:
        return "no release branch", False
    wanted = json.loads(fetch(COMMIT.format(ref=tag)))["sha"]
    return branch[:7], branch == wanted


def _marketplace(fetch: Fetch) -> tuple[str, bool]:
    plugins = json.loads(fetch(MARKETPLACE))["plugins"]
    entry = next((p for p in plugins if p["name"] == "kitden"), None)
    if entry is None:
        return "no kitden entry", False
    source = entry["source"]
    ref = source.get("ref", "none") if isinstance(source, dict) else "none"
    return ref, ref == "release"


def _description(listing: dict | None, fetch: Fetch) -> tuple[str, bool | None]:
    seen = json.loads(fetch(REPO))["description"]
    if listing is None:
        return f"{seen} (not checked: no listing.toml)", None
    return seen, seen == listing["short"]


def _load_listing(tag: str, fetch: Fetch) -> tuple[dict | None, str]:
    """The listing at the tag, or None and why. A listing without short or brew is unreadable."""
    try:
        listing = tomllib.loads(fetch(LISTING.format(tag=tag)))
    except (OSError, ValueError) as error:  # ValueError: bad TOML or bytes that do not decode
        return None, str(error)
    for field in ("short", "brew"):
        if not isinstance(listing.get(field), str):
            return None, f"no {field}"
    return listing, ""


def read_all(tag: str, fetch: Fetch) -> list[Row]:
    found = TAG.match(tag)
    if not found:
        raise ValueError(f'tag {tag} must look like "vX.Y.Z"')
    version = found.group(1)
    listing, why = _load_listing(tag, fetch)
    short = listing["short"] if listing else f"listing.toml not readable at {tag}: {why}"
    rows = [
        _row("PyPI", version, lambda: _pypi(version, fetch)),
        _row("GitHub release", tag, lambda: _release(tag, fetch)),
        _row("MCP Registry", version, lambda: _registry(version, fetch)),
        _row(HOMEBREW, version, lambda: _homebrew(version, listing, fetch)),
        _row("release branch", f"at {tag}", lambda: _branch(tag, fetch)),
        _row("Marketplace entry", "release", lambda: _marketplace(fetch)),
        _row("GitHub description", short, lambda: _description(listing, fetch)),
        Row("Claude directory", "-", BY_HAND, None),
        Row("Glama", "-", BY_HAND, None),
    ]
    return rows


def behind(rows: list[Row], tag_age_hours: float) -> list[Row]:
    """Rows that are not ok. Homebrew builds bottles slowly, so it counts only after 48 hours.
    Rows to check by hand are not behind."""
    return [
        row
        for row in rows
        if row.ok is False and (row.place != HOMEBREW or tag_age_hours >= HOMEBREW_WAIT_HOURS)
    ]


def _cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def summary(rows: list[Row]) -> str:
    status = {True: "ok", False: "behind", None: BY_HAND}
    lines = ["| Place | Expected | Seen | Status |", "| --- | --- | --- | --- |"]
    for row in rows:
        cells = (row.place, row.expected, row.seen, status[row.ok])
        lines.append("| " + " | ".join(_cell(c) for c in cells) + " |")
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    if len(argv) != 1 or not TAG.match(argv[0]):
        print("usage: release_stores.py vX.Y.Z", file=sys.stderr)
        return 2
    print(summary(read_all(argv[0], fetch_url)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
