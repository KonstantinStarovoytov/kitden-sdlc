import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
# Markdown links and images, and the src and srcset of HTML tags such as <picture>.
LINK = re.compile(r"\]\(([^)\s]+)\)|\b(?:src|srcset)=\"([^\"]+)\"")


def test_python_is_313_or_newer():
    assert sys.version_info >= (3, 13)


def relative_links(path: Path) -> list[str]:
    links = []
    for match in LINK.finditer(path.read_text()):
        target = match.group(1) or match.group(2)
        if re.match(r"[a-z]+:", target) or target.startswith("#"):
            continue  # a web address or a heading on the same page
        links.append(target.split("#")[0])
    return links


@pytest.mark.parametrize(
    "name", ["README.md", "docs/agents.md", "docs/setup.md", "docs/release-setup.md"]
)
def test_readme_links_exist(name):
    page = ROOT / name
    links = relative_links(page)
    assert links, f"{name} has no relative links: the pattern is broken"
    missing = [link for link in links if not (page.parent / link).exists()]
    assert not missing, f"{name} links to files that do not exist: {missing}"
