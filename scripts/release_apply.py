"""Put the release-prep agent's files into Kitden, and write the release pull request's body.

No model runs here; the files it reads were written by one, so they are only data. Commands:

  release_apply.py scenes SCENES_TXT IMAGES_DIR
      Prints the scenes to record, keeping only names that already have pictures.
  release_apply.py apply ROOT OUT --version X.Y.Z --lists DIR [--images DIR --scenes "a b"]
      Copies the agent's files from OUT into the Kitden checkout ROOT, and the recorded
      pictures from --images. Writes DIR/content.txt and DIR/policy.txt: the files of the
      first commit and of the second. Refuses, writing nothing, any file it does not know.
  release_apply.py body --findings F --development D --changed C --out BODY
      The pull request's body: the agent's findings, the real-client checks from Kitden's
      docs/development.md that the changed files touch, and how to merge.
"""

import argparse
import os
import re
import sys
from pathlib import Path

from post_findings import SECRET_LIKE, WORD_JOINER, quiet_mentions
from release_bump import current_version

VERSION = re.compile(r"\d+\.\d+\.\d+\Z", re.ASCII)
# What the agent may write in out/, and where each file goes. "content" files go in the first
# commit, "policy" files in a second one, so the owner reads them apart. None: read by the
# workflow, never put into Kitden.
POLICY = ("PRIVACY.md", "SECURITY.md", "AI_POLICY.md", "listing.toml")
OUT_FILES: dict[str, tuple[str, str] | None] = {
    "notes.md": ("docs/releases/v{version}.md", "content"),
    "README.md": ("README.md", "content"),
    **{f"policy/{name}": (name, "policy") for name in POLICY},
    "findings.md": None,
    "version.txt": None,
    "scenes.txt": None,
}
# Every Kitden file this script may write. The bump job writes the version files and
# ROADMAP.md itself, from a script.
ALLOWED = ("docs/releases/", "README.md", "ROADMAP.md", *POLICY)
TEXT_MAX = 500_000
IMAGES = Path("docs/images/readme")
IMAGE_MAX = 20_000_000
SCENE = re.compile(r"[a-z][a-z0-9]*(-[a-z0-9]+)*\Z", re.ASCII)
THEMES = ("light", "dark")
IMAGE_TYPES = ("png", "webp")
FINDINGS_MAX = 40_000
# "Fixes #12", "closes: owner/repo#3", "Resolved https://github.com/o/r/issues/4": GitHub would
# close that issue when the PR merges. A word joiner after the keyword breaks the pattern.
CLOSING = re.compile(
    r"\b(close[sd]?|fix(?:e[sd])?|resolve[sd]?)"
    r"(?=[ \t]*:?[ \t]*(?:[\w.-]+/[\w.-]+)?#\d|[ \t]*:?[ \t]*https?://github\.com/)",
    re.IGNORECASE,
)
# A Markdown heading of any level, which could pass for one of this body's own sections.
HEADING = re.compile(r"^ {0,3}(#{1,6})(?=[ \t]|$)", re.MULTILINE)
MODEL = re.compile(r"[\w.:-]{1,80}\Z", re.ASCII)

CHECKS_HEADING = "## Check before a release"
CHECKS_START = "Before a release that"
# Which changed files under src/ make each check due: a plain match on the path, generous on
# purpose. A check whose area is not here is always listed.
AREAS = (
    ("the Kitden gateway", ("gateway", "mcp_server", "proxy")),
    ("puts back items", ("kitden/changes/", "kitden/clients/", "add-panel", "changes.js")),
    ("secrets", ("keychain", "keyring", "secret", "oauth", "sign_in", "redact")),
    ("Details or the preview tray", ("details", "dock", "tray", "preview", "changes", "review")),
    ("the Gateway map", ("gateway-drag", "gateway_view", "gateway-map", "gateway.js")),
)


def target_for(name: str, version: str) -> tuple[Path, str] | None:
    """Where out/`name` goes in Kitden and in which commit; None for the workflow's own files.
    Raises ValueError for any other name."""
    if name not in OUT_FILES:
        raise ValueError(f"out/{name} is not allowed")
    target = OUT_FILES[name]
    if target is None:
        return None
    path = Path(target[0].format(version=version))
    if not any(str(path) == allowed or str(path).startswith(allowed) for allowed in ALLOWED):
        raise ValueError(f"{path} is not allowed")  # a mistake in OUT_FILES
    return path, target[1]


def _files(folder: Path) -> list[str]:
    """Every file under `folder`, as relative POSIX names. Refuses links and odd files."""
    if folder.is_symlink():
        raise ValueError(f"{folder} is a link")
    names: list[str] = []
    for top, dirs, files in os.walk(folder, followlinks=False):
        for name in [*dirs, *files]:
            path = Path(top, name)
            if path.is_symlink():
                raise ValueError(f"{path.relative_to(folder)} is a link")
            if name in files and not path.is_file():
                raise ValueError(f"{path.relative_to(folder)} is not a plain file")
        names += [Path(top, name).relative_to(folder).as_posix() for name in files]
    return sorted(names)


def _no_link(root: Path, target: Path) -> None:
    path = root / target
    while path != root:
        if path.is_symlink():
            raise ValueError(f"{path.relative_to(root)} in Kitden is a link")
        path = path.parent


def apply(root: Path, out: Path, version: str | None = None) -> tuple[list[Path], list[Path]]:
    """Copy the agent's files from `out` into `root`. Returns (content files, policy files),
    relative to `root`, leaving out files that did not change. Raises ValueError, writing
    nothing, for any file outside OUT_FILES, a link, or a file that is too large."""
    version = version or current_version(root)
    if not VERSION.match(version):
        raise ValueError(f"version {version!r} is not X.Y.Z")
    names = _files(out) if out.exists() else []
    targets = {name: target_for(name, version) for name in names}  # refuses unknown names
    planned: list[tuple[Path, str, bytes]] = []
    for name in sorted(targets, key=list(OUT_FILES).index):
        target = targets[name]
        if target is None:
            continue
        path, kind = target
        data = (out / name).read_bytes()
        if len(data) > TEXT_MAX:
            raise ValueError(f"out/{name} is too large ({len(data)} bytes)")
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError as error:
            raise ValueError(f"out/{name} is not UTF-8 text") from error
        if SECRET_LIKE.search(text):
            raise ValueError(f"out/{name} looks like it holds a secret: not committed")
        _no_link(root, path)
        if (root / path).is_file() and (root / path).read_bytes() == data:
            continue
        planned.append((path, kind, data))

    for path, _, data in planned:
        (root / path).parent.mkdir(parents=True, exist_ok=True)
        (root / path).write_bytes(data)
    content = [path for path, kind, _ in planned if kind == "content"]
    policy = [path for path, kind, _ in planned if kind == "policy"]
    return content, policy


def scenes(text: str, images: Path) -> list[str]:
    """The scene names in `text` that already have a picture in `images`, each once."""
    found: list[str] = []
    for line in text.splitlines():
        name = line.strip()
        if not SCENE.match(name) or name in found:
            continue
        if any((images / f"{name}-light.{kind}").is_file() for kind in IMAGE_TYPES):
            found.append(name)
    return found


def apply_images(root: Path, images: Path, scene_list: list[str]) -> list[Path]:
    """Copy the recorded pictures of `scene_list` into Kitden's docs/images/readme. Raises
    ValueError, writing nothing, for any other file."""
    if not images.exists():
        return []
    allowed = {
        f"{scene}-{theme}.{kind}"
        for scene in scene_list
        if SCENE.match(scene)
        for theme in THEMES
        for kind in IMAGE_TYPES
    }
    planned: list[tuple[Path, bytes]] = []
    for name in _files(images):
        if name not in allowed:
            raise ValueError(f"{name} is not a picture of a listed scene")
        data = (images / name).read_bytes()
        if len(data) > IMAGE_MAX:
            raise ValueError(f"{name} is too large ({len(data)} bytes)")
        target = IMAGES / name
        _no_link(root, target)
        if (root / target).is_file() and (root / target).read_bytes() == data:
            continue
        planned.append((target, data))
    for target, data in planned:
        (root / target).parent.mkdir(parents=True, exist_ok=True)
        (root / target).write_bytes(data)
    return [target for target, _ in planned]


def _section(doc: str) -> str:
    start = doc.find(f"\n{CHECKS_HEADING}\n")
    if start < 0:
        return ""
    rest = doc[start + len(CHECKS_HEADING) + 2 :]
    end = rest.find("\n## ")
    return rest if end < 0 else rest[:end]


def hand_checks(doc: str, changed: list[str]) -> list[str]:
    """The groups of real-client checks in development.md's "Check before a release" whose
    area the changed files touch. A group whose area this script does not know is kept."""
    groups: list[list[str]] = []
    for paragraph in re.split(r"\n\s*\n", _section(doc).strip()):
        if CHECKS_START in paragraph:
            groups.append([paragraph[paragraph.index(CHECKS_START) :]])
        elif groups:
            groups[-1].append(paragraph)
    code = [path.lower() for path in changed if path.startswith("src/")]
    picked: list[str] = []
    for group in groups:
        intro = group[0].split(".")[0]
        keywords = next((words for phrase, words in AREAS if phrase in intro), None)
        if keywords is None or any(word in path for path in code for word in keywords):
            picked.append("\n\n".join(group))
    return picked


def quiet_findings(text: str) -> str:
    """The agent's findings, made safe to show in the PR body: no mention pings anyone, no
    closing keyword closes an issue, and every heading is level 4 or lower, inside a quote, so
    none passes for this body's own "Hand checks" or "Merge" sections."""
    text = CLOSING.sub(lambda m: m.group(1) + WORD_JOINER, quiet_mentions(text))
    text = HEADING.sub(lambda m: "#" * max(4, len(m.group(1))), text)
    return "\n".join(f"> {line}" if line else ">" for line in text.splitlines())


def pr_body(findings: str, checks: list[str], unrecorded: list[str], model: str = "") -> str:
    """The release pull request's body. Raises ValueError when the findings look like they
    hold a secret."""
    if SECRET_LIKE.search(findings):
        raise ValueError("the findings look like they hold a secret: not posted")
    findings = findings.strip()
    if len(findings) > FINDINGS_MAX:
        findings = findings[:FINDINGS_MAX] + "\n\n[cut: the rest is in the run's artifact]"
    who = f"`{model}`" if MODEL.match(model) else "a model"
    parts = [
        f"Automated: prepared by kitden-sdlc's release-prep. The notes, the README and the "
        f"policy edits were written by {who}; the version, the commits and this text by "
        f"scripts. The first commit holds the notes, the README, the version and the "
        f"pictures; the second, if there is one, the policy files and `listing.toml`.",
        "## Findings",
        quiet_findings(findings) if findings else "No findings from the agent.",
        "## Hand checks",
        "\n\n---\n\n".join(checks)
        if checks
        else "No real-client check in docs/development.md matches the files this release changed.",
    ]
    if unrecorded:
        names = ", ".join(f"`{name}`" for name in unrecorded if SCENE.match(name))
        parts += [
            "## Pictures to record by hand",
            f"The record job could not make these scenes: {names}. Run "
            "`uv run --with playwright==1.64.1 python scripts/record_readme.py --only <scene>` "
            "for each and push the pictures to this branch.",
        ]
    parts += [
        "## Merge",
        "Merge with a merge commit, not squash: the release notes link this branch's commits.",
    ]
    return "\n\n".join(parts) + "\n"


def _read(path: Path) -> str:
    try:
        return path.read_text()
    except FileNotFoundError:
        return ""


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    scenes_cmd = commands.add_parser("scenes")
    scenes_cmd.add_argument("scenes_txt", type=Path)
    scenes_cmd.add_argument("images", type=Path)
    apply_cmd = commands.add_parser("apply")
    apply_cmd.add_argument("root", type=Path)
    apply_cmd.add_argument("out", type=Path)
    apply_cmd.add_argument("--version", required=True)
    apply_cmd.add_argument("--images", type=Path)
    apply_cmd.add_argument("--scenes", default="")
    apply_cmd.add_argument("--lists", type=Path, required=True)
    body_cmd = commands.add_parser("body")
    body_cmd.add_argument("--findings", type=Path, required=True)
    body_cmd.add_argument("--development", type=Path, required=True)
    body_cmd.add_argument("--changed", type=Path, required=True)
    body_cmd.add_argument("--unrecorded", default="")
    body_cmd.add_argument("--model", default="")
    body_cmd.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)

    try:
        if args.command == "scenes":
            print(" ".join(scenes(_read(args.scenes_txt), args.images)))
        elif args.command == "apply":
            content, policy = apply(args.root, args.out, args.version)
            if args.images:
                content += apply_images(args.root, args.images, args.scenes.split())
            args.lists.mkdir(parents=True, exist_ok=True)
            for name, paths in (("content.txt", content), ("policy.txt", policy)):
                (args.lists / name).write_text("".join(f"{path}\n" for path in paths))
            print(f"First commit: {len(content)} files. Policy commit: {len(policy)} files.")
        else:
            checks = hand_checks(_read(args.development), _read(args.changed).split())
            body = pr_body(_read(args.findings), checks, args.unrecorded.split(), model=args.model)
            args.out.write_text(body)
    except ValueError as error:
        print(error)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
