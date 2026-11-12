"""Helpers to update the Homebrew formula when Kitden's runtime dependencies did not change.

No model and no network. `deps_changed` says whether `project.dependencies` differ between two
pyproject.toml texts. `bump_formula` rewrites only the top desc, url and sha256 of the formula;
`resource` and `bottle` blocks are never touched.
"""

import re
import tomllib


def _normal(requirement: str) -> str:
    return re.sub(r"\s+", "", requirement).lower()


def _dependencies(pyproject: str) -> set[str]:
    deps = tomllib.loads(pyproject).get("project", {}).get("dependencies", [])
    return {_normal(dep) for dep in deps}


def deps_changed(old_pyproject: str, new_pyproject: str) -> bool:
    """True if the two `project.dependencies` lists differ. Order and spacing do not count."""
    return _dependencies(old_pyproject) != _dependencies(new_pyproject)


def bump_formula(text: str, url: str, sha256: str, desc: str) -> str:
    """The formula with its top url, sha256 and desc replaced; unchanged if already at `url`.

    The top lines are the ones with two spaces of indent before the first `bottle do` or
    `resource`, so nothing in those blocks (deeper indent, later in the file) can match.
    """
    # Only look above the first bottle or resource block.
    stops = [m.start() for m in re.finditer(r"(?m)^  (bottle do|resource )", text)]
    split = min(stops) if stops else len(text)
    head, tail = text[:split], text[split:]

    if re.search(rf'(?m)^  url "{re.escape(url)}"$', head):
        return text

    for key, value in (("url", url), ("sha256", sha256), ("desc", desc)):
        pattern = rf'(?m)^(  {key} ").*(")$'
        if len(re.findall(pattern, head)) != 1:
            raise ValueError(f"formula: expected one top {key} line")
        head = re.sub(pattern, lambda m, v=value: f"{m.group(1)}{v}{m.group(2)}", head)
    return head + tail
