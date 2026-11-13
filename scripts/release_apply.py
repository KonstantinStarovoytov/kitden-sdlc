"""Put the release-prep agent's files into Kitden, and write the release pull request's body.

No model runs here; the files it reads were written by one, so they are only data. Commands:

  release_apply.py scenes SCENES_TXT IMAGES_DIR
      Prints the scenes the agent expects to change, keeping only names that have pictures.
  release_apply.py all-scenes IMAGES_DIR
      Prints every scene that has a picture, on one line.
  release_apply.py apply ROOT OUT --version X.Y.Z --lists DIR [--images DIR --results FILE]
                         [--context CONTEXT_JSON --given FILE ...]
      Copies the agent's files from OUT into the Kitden checkout ROOT, and the recorded
      pictures from --images: a still when its bytes differ, an animation when it is stale.
      Writes DIR/content.txt and DIR/policy.txt: the files of the first commit and of the
      second. Writes DIR/pictures.json: what became of each scene. Refuses, writing nothing,
      any file it does not know.
  release_apply.py body --findings F --development D --changed C --out BODY [--problems F
      --facts F --pictures F --results F --expected "a b" --fixed F --fix-result R --root ROOT
      --context CONTEXT_JSON --given FILE ...]
      The pull request's body: what is still wrong, what scripts checked, the agent's findings,
      the real-client checks from Kitden's docs/development.md that the changed files touch,
      and how to merge. R is the fix job's result (success, failure, cancelled, skipped or
      empty). A --problems, --pictures or --facts file that is given but cannot be read counts
      as a problem. Prints draft or ready. ROOT is the Kitden checkout.

A long random string in the agent's files or in the body's text must be in what the agent
read: ROOT's HEAD, the context.json it was given, or a --given file (the fix pass: the first
problems.md, which scripts wrote). A missing file knows nothing.
"""

import argparse
import contextlib
import json
import os
import re
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

from post_findings import SECRET_LIKE, WORD_JOINER, quiet_mentions
from release_bump import current_version
from secret_filter import in_git, in_text, unknown_runs

VERSION = re.compile(r"\d+\.\d+\.\d+\Z", re.ASCII)
# What the agent may write in out/, and where each file goes. "content" files go in the first
# commit, "policy" files in a second one, so the owner reads them apart. None: read by the
# workflow, never put into Kitden.
POLICY = ("PRIVACY.md", "SECURITY.md", "AI_POLICY.md", "listing.toml")
OUT_FILES: dict[str, tuple[str, str] | None] = {
    "notes.md": ("docs/releases/v{version}.md", "content"),
    "README.md": ("README.md", "content"),
    "guide.md": ("docs/guide.md", "content"),
    **{f"policy/{name}": (name, "policy") for name in POLICY},
    "plugin/README.md": ("plugins/kitden/README.md", "policy"),
    "findings.md": None,
    "version.txt": None,
    "scenes.txt": None,
}
# Every Kitden file this script may write. The bump job writes the version files and
# ROADMAP.md itself, from a script.
ALLOWED = (
    "docs/releases/",
    "README.md",
    "ROADMAP.md",
    "docs/guide.md",
    "plugins/kitden/README.md",
    *POLICY,
)
TEXT_MAX = 500_000
IMAGES = Path("docs/images/readme")
IMAGE_MAX = 20_000_000
SCENE = re.compile(r"[a-z][a-z0-9]*(-[a-z0-9]+)*\Z", re.ASCII)
THEMES = ("light", "dark")
IMAGE_TYPES = ("png", "webp")
RESULTS = "results.json"
# An animation is re-recorded only when it is older than a change to the code that draws it.
STALE_PATHS = (
    "src/kitden/web/",
    "src/kitden/demo/",
    "src/kitden/views/",
    "scripts/record_readme.py",
    "scripts/record_scenes.py",
    "scripts/readme_demo.py",
)
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
LINE_MAX = 300
# GitHub refuses a body over 65,536 characters, so the problems are capped.
PROBLEMS_MAX = 30
SAFE_PATH = re.compile(r"[\w./@+-]+\Z", re.ASCII)
STATES = ("changed", "the same", "not needed", "failed")
MODEL = re.compile(r"[\w.:-]{1,80}\Z", re.ASCII)

CHECKS_HEADING = "## Check before a release"
CHECKS_START = "Before a release that"
# Which changed files under src/ make each check due: a plain match on the path, generous on
# purpose. A check whose area is not here is always listed.
AREAS = (
    (
        "the Kitden gateway",
        ("local_gateway/", "gateway_api", "gateways.py", "mcp_server", "proxy"),
    ),
    ("puts back items", ("kitden/changes/", "kitden/clients/", "add-panel", "changes.js")),
    ("secrets", ("keychain", "keyring", "secret", "oauth", "sign_in", "redact")),
    ("Details or the preview tray", ("details", "dock", "tray", "preview", "changes", "review")),
    (
        "the Gateway map",
        (
            "gateway-drag",
            "gateway_view",
            "gateway-map",
            "gateway.js",
            "/map-view.js",
            "/map.js",
            "/map-drag.js",
        ),
    ),
)


def target_for(name: str, version: str) -> tuple[Path, str] | None:
    """Where out/`name` goes in Kitden and in which commit; None for the workflow's own files.
    Raises ValueError for any other name."""
    if name not in OUT_FILES:
        raise ValueError("a file in out/ has a name that is not allowed")
    target = OUT_FILES[name]
    if target is None:
        return None
    path = Path(target[0].format(version=version))
    if not any(str(path) == allowed or str(path).startswith(allowed) for allowed in ALLOWED):
        raise ValueError(f"{path} is not allowed")  # a mistake in OUT_FILES
    return path, target[1]


def _files(folder: Path) -> list[str]:
    """Every file under `folder`, as relative POSIX names. Refuses links and odd files,
    counting them: the agent chooses the names, and a refusal must not show them."""
    if folder.is_symlink():
        raise ValueError(f"{folder} is a link")
    names: list[str] = []
    odd = 0
    for top, dirs, files in os.walk(folder, followlinks=False):
        for name in [*dirs, *files]:
            path = Path(top, name)
            if path.is_symlink() or (name in files and not path.is_file()):
                odd += 1
        names += [Path(top, name).relative_to(folder).as_posix() for name in files]
    if odd:
        raise ValueError(
            f"{folder.name}/ holds links or other files that are not plain ({odd}): refused"
        )
    return sorted(names)


def refuse_unknown_names(names: list[str]) -> None:
    """Raises ValueError when a name in `names` is not in OUT_FILES. The message counts the
    names and shows none of them: the agent chose them, and the job log is public."""
    unknown = [name for name in names if name not in OUT_FILES]
    if unknown:
        raise ValueError(f"out/ holds files whose names are not allowed ({len(unknown)}): refused")


def _no_link(root: Path, target: Path) -> None:
    path = root / target
    while path != root:
        if path.is_symlink():
            raise ValueError(f"{path.relative_to(root)} in Kitden is a link")
        path = path.parent


def apply(
    root: Path, out: Path, version: str | None = None, context: str = ""
) -> tuple[list[Path], list[Path]]:
    """Copy the agent's files from `out` into `root`. Returns (content files, policy files),
    relative to `root`, leaving out files that did not change. Raises ValueError, writing
    nothing, for any file outside OUT_FILES, a link, a file that is too large, or text that
    looks like a secret: a token, or a long random string that neither Kitden's HEAD nor
    `context` (the text the agent was given besides Kitden) holds."""
    version = version or current_version(root)
    if not VERSION.match(version):
        raise ValueError(f"version {version!r} is not X.Y.Z")
    in_kitden = given(root, context)
    names = _files(out) if out.exists() else []
    refuse_unknown_names(names)
    targets = {name: target_for(name, version) for name in names}
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
        unknown = unknown_runs([text], in_kitden)
        if unknown:
            raise ValueError(
                f"out/{name} holds long random strings that are not in what the agent was "
                f"given ({len(unknown)}): not committed"
            )
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


def given(root: Path | None, context: str) -> Callable[[str], bool]:
    """Knows a run that Kitden's HEAD in `root` (when given) or the text `context` holds."""
    in_context = in_text(context)
    in_kitden = in_git(root, "HEAD") if root else in_text()
    return lambda run: in_kitden(run) or in_context(run)


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


def all_scenes(images: Path) -> list[str]:
    """Every scene in `images` that has a light picture, sorted."""
    found: set[str] = set()
    if images.is_dir():
        for kind in IMAGE_TYPES:
            for path in images.glob(f"*-light.{kind}"):
                name = path.name.removesuffix(f"-light.{kind}")
                if SCENE.match(name):
                    found.add(name)
    return sorted(found)


def _git(root: Path, *args: str) -> str:
    done = subprocess.run(  # noqa: S603
        ["git", "-C", str(root), *args],  # noqa: S607
        check=True,
        capture_output=True,
        text=True,
    )
    return done.stdout.strip()


def is_stale(root: Path, picture: Path) -> bool:
    """True when the code that draws `picture` (STALE_PATHS) changed on this branch after the
    picture last arrived on it, or when the picture was never committed. Only the branch's own
    line counts (--first-parent): the merge that brings a picture is the moment it arrived, so
    that merge, and work merged before it, do not make the picture stale."""
    with contextlib.suppress(ValueError):
        picture = picture.relative_to(root)
    last = _git(root, "log", "--first-parent", "-1", "--format=%H", "--", str(picture))
    if not last:
        return True
    later = _git(root, "log", "--first-parent", "--format=%H", f"{last}..HEAD", "--", *STALE_PATHS)
    return bool(later)


def apply_images(
    root: Path,
    images: Path,
    results: dict[str, str] | None,
    stale: Callable[[Path], bool] | None = None,
) -> tuple[list[Path], dict[str, str]]:
    """Copy the recorded pictures from `images` into Kitden's docs/images/readme. `results`
    is the record job's results.json (scene -> "" or the end of its error); None: it is
    missing. A still goes in when its bytes differ, an animation when `stale` says so
    (default: is_stale). Returns the copied paths and, for every scene Kitden has, one of
    "changed", "the same", "not needed", "failed". Raises ValueError, writing nothing, for
    any file that is not results.json or a picture of a known scene."""
    scene_list = all_scenes(root / IMAGES)
    states = {scene: "failed" for scene in scene_list}
    if not images.exists():
        return [], states
    if stale is None:

        def stale(picture: Path) -> bool:
            return is_stale(root, picture)

    allowed = {
        f"{scene}-{theme}.{kind}"
        for scene in scene_list
        for theme in THEMES
        for kind in IMAGE_TYPES
    }
    names = _files(images)
    for name in names:
        if name != RESULTS and name not in allowed:
            raise ValueError(f"{name} is not a picture of a known scene")
    planned: list[tuple[Path, bytes]] = []
    for scene in scene_list:
        if results is None or results.get(scene) != "":
            continue
        kind = "png" if (root / IMAGES / f"{scene}-light.png").is_file() else "webp"
        files = [f"{scene}-{theme}.{kind}" for theme in THEMES]
        if not all(file in names for file in files):
            continue  # the job said it recorded this scene, but the pictures are not there
        data = {file: (images / file).read_bytes() for file in files}
        for file, content in data.items():
            if len(content) > IMAGE_MAX:
                raise ValueError(f"{file} is too large ({len(content)} bytes)")
            _no_link(root, IMAGES / file)
        if kind == "png":
            differs = [
                file
                for file, content in data.items()
                if not (root / IMAGES / file).is_file()
                or (root / IMAGES / file).read_bytes() != content
            ]
            states[scene] = "changed" if differs else "the same"
        else:
            differs = list(data) if stale(root / IMAGES / files[0]) else []
            states[scene] = "changed" if differs else "not needed"
        if differs:
            planned += [(IMAGES / file, data[file]) for file in files]
    for target, content in planned:
        (root / target).parent.mkdir(parents=True, exist_ok=True)
        (root / target).write_bytes(content)
    return [target for target, _ in planned], states


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


def _quiet(text: str) -> str:
    """`text` with no mention that pings anyone, no closing keyword that closes an issue, and
    no heading above level 4."""
    text = CLOSING.sub(lambda m: m.group(1) + WORD_JOINER, quiet_mentions(text))
    return HEADING.sub(lambda m: "#" * max(4, len(m.group(1))), text)


def quiet_findings(text: str) -> str:
    """The agent's findings, made safe to show in the PR body: no mention pings anyone, no
    closing keyword closes an issue, and every heading is level 4 or lower, inside a quote, so
    none passes for this body's own "Hand checks" or "Merge" sections."""
    return "\n".join(f"> {line}" if line else ">" for line in _quiet(text).splitlines())


def _one_line(text: str) -> str:
    """`text` as one quiet line of at most LINE_MAX characters."""
    text = " ".join(text.split())
    if len(text) > LINE_MAX:
        text = text[: LINE_MAX - 1] + "\u2026"
    return _quiet(text)


def is_draft(problems: list[str], pictures: dict[str, str]) -> bool:
    """True when the pull request should be a draft: a problem is left, or a scene failed."""
    return bool(problems) or "failed" in pictures.values()


def _names(names: list[str]) -> str:
    return ", ".join(f"`{name}`" for name in names)


def _fix_pass(fixed: list[str] | None, fix_result: str = "") -> str:
    if fix_result in ("failure", "cancelled"):
        return "One fix pass ran and failed; the first files are used."
    if fix_result != "success" or fixed is None:
        return "No fix pass was needed."
    paths = [f"`{path}`" for path in fixed if SAFE_PATH.match(path)]
    if not paths:
        return "One fix pass ran and changed nothing."
    listed = paths[0] if len(paths) == 1 else ", ".join(paths[:-1]) + " and " + paths[-1]
    return f"One fix pass changed {listed}."


def _count(facts: dict, key: str) -> int | None:
    value = facts.get(key)
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _facts_bullets(
    facts: dict | None, pictures: dict[str, str] | None, expected: list[str]
) -> list[str]:
    bullets: list[str] = []
    facts = facts or {}
    readme: list[str] = []
    if (lines := _count(facts, "readme_lines")) is not None:
        readme.append(f"README: {lines} lines.")
    for key, label in (("docs_tests", "Kitden's docs tests"), ("release_check", "Release check")):
        if facts.get(key) in ("pass", "fail"):
            readme.append(f"{label}: {facts[key]}.")
    if readme:
        bullets.append(" ".join(readme))
    notes: list[str] = []
    for named, total, what in (
        ("prs_named", "prs_total", "pull requests named"),
        ("authors_named", "authors_total", "authors"),
    ):
        if (a := _count(facts, named)) is not None and (b := _count(facts, total)) is not None:
            notes.append(f"{a} of {b} {what}")
    if facts.get("links") == "ok":
        notes.append("all links point at files")
    elif facts.get("links") == "broken":
        notes.append("some links point at no file")
    if notes:
        bullets.append("Notes: " + ", ".join(notes) + ".")
    pictures = {k: v for k, v in (pictures or {}).items() if SCENE.match(k)}
    groups = []
    for state in STATES:
        names = sorted(k for k, v in pictures.items() if v == state)
        if names:
            groups.append(f"{_names(names)} {state}")
    if groups:
        bullets.append("Pictures: " + " \u00b7 ".join(groups))
    same = sorted(k for k in set(expected) if pictures.get(k) == "the same")
    if same:
        bullets.append(
            f"Expected by the agent but the same: {_names(same)}. "
            "That scene does not show the change."
        )
    return bullets


def pr_body(
    findings: str,
    checks: list[str],
    *,
    model: str = "",
    problems: list[str] = (),
    facts: dict | None = None,
    pictures: dict[str, str] | None = None,
    expected: list[str] = (),
    errors: dict[str, str] | None = None,
    fixed: list[str] | None = None,
    fix_result: str = "",
    known: Callable[[str], bool] | None = None,
) -> str:
    """The release pull request's body. Raises ValueError when the findings, a problem, an
    error or a fixed path look like they hold a secret: a token, or a long random string that
    `known` does not know (by default none is known)."""
    errors = errors or {}
    texts = (findings, *problems, *errors.values(), *(fixed or ()))
    for text in texts:
        if SECRET_LIKE.search(text):
            raise ValueError("the findings, a problem or an error look like they hold a secret")
    unknown = unknown_runs(texts, known or in_text())
    if unknown:
        raise ValueError(
            f"the findings, a problem or an error hold long random strings that are not in "
            f"what the agent was given ({len(unknown)}): not posted"
        )
    findings = findings.strip()
    if len(findings) > FINDINGS_MAX:
        findings = findings[:FINDINGS_MAX] + "\n\n[cut: the rest is in the run's artifact]"
    who = f"`{model}`" if MODEL.match(model) else "a model"
    parts = [
        f"Automated: prepared by kitden-sdlc's release-prep. The notes, the README and the "
        f"policy edits were written by {who}; the version, the commits and this text by "
        f"scripts. The first commit holds the notes, the guide, the README, the version and "
        f"the pictures; the second, if there is one, the policy files, the plugin README "
        f"and `listing.toml`. " + _fix_pass(fixed, fix_result),
    ]
    to_fix = [f"- {_one_line(problem)}" for problem in problems[:PROBLEMS_MAX]]
    if len(problems) > PROBLEMS_MAX:
        to_fix.append(
            f"- and {len(problems) - PROBLEMS_MAX} more: see the run's `release-verdict` artifact."
        )
    for scene, state in sorted((pictures or {}).items()):
        if state == "failed" and SCENE.match(scene):
            error = _one_line(errors.get(scene, "")) or "no reason was kept"
            to_fix.append(
                f"- Pictures: `{scene}` could not be recorded: {error.rstrip('.')}. Fix the "
                f"scene in Kitden, or run `uv run --with playwright==1.64.1 python "
                f"scripts/record_readme.py --only {scene}` and push the pictures to this branch."
            )
    if to_fix:
        parts += ["## Fix before merge", "\n".join(to_fix)]
    if bullets := _facts_bullets(facts, pictures, list(expected)):
        parts += ["## Checked by scripts", "\n".join(f"- {bullet}" for bullet in bullets)]
    parts += [
        "## Findings",
        quiet_findings(findings) if findings else "No findings from the agent.",
        "## Hand checks",
        "\n\n---\n\n".join(checks)
        if checks
        else "No real-client check in docs/development.md matches the files this release changed.",
        "## Merge",
        "Merge with a merge commit, not squash: the release notes link this branch's commits.",
    ]
    return "\n\n".join(parts) + "\n"


def _read(path: Path | None) -> str:
    if path is None:
        return ""
    try:
        return path.read_text()
    except FileNotFoundError:
        return ""


def _results(path: Path | None) -> dict | None:
    """A JSON object from `path`; None when the path is not given, the file is missing or it
    is not a JSON object."""
    if path is None:
        return None
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _fixed(path: Path | None) -> list[str] | None:
    """The paths in fixed.txt; None when no fix pass ran (no file)."""
    if path is None or not path.is_file():
        return None
    return [line.strip() for line in path.read_text().splitlines() if line.strip()]


GIVEN_HELP = "another file scripts wrote that the agent read (the fix pass: the first problems.md)"


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    scenes_cmd = commands.add_parser("scenes")
    scenes_cmd.add_argument("scenes_txt", type=Path)
    scenes_cmd.add_argument("images", type=Path)
    all_cmd = commands.add_parser("all-scenes")
    all_cmd.add_argument("images", type=Path)
    apply_cmd = commands.add_parser("apply")
    apply_cmd.add_argument("root", type=Path)
    apply_cmd.add_argument("out", type=Path)
    apply_cmd.add_argument("--version", required=True)
    apply_cmd.add_argument("--images", type=Path)
    apply_cmd.add_argument("--results", type=Path)
    apply_cmd.add_argument("--lists", type=Path, required=True)
    apply_cmd.add_argument("--context", type=Path, help="the context.json the agent read")
    apply_cmd.add_argument("--given", type=Path, action="append", default=[], help=GIVEN_HELP)
    body_cmd = commands.add_parser("body")
    body_cmd.add_argument("--findings", type=Path, required=True)
    body_cmd.add_argument("--development", type=Path, required=True)
    body_cmd.add_argument("--changed", type=Path, required=True)
    body_cmd.add_argument("--problems", type=Path)
    body_cmd.add_argument("--facts", type=Path)
    body_cmd.add_argument("--pictures", type=Path)
    body_cmd.add_argument("--results", type=Path)
    body_cmd.add_argument("--expected", default="")
    body_cmd.add_argument("--fixed", type=Path)
    body_cmd.add_argument("--fix-result", default="")
    body_cmd.add_argument("--model", default="")
    body_cmd.add_argument("--out", type=Path, required=True)
    body_cmd.add_argument("--root", type=Path, help="the Kitden checkout the agent read")
    body_cmd.add_argument("--context", type=Path, help="the context.json the agent read")
    body_cmd.add_argument("--given", type=Path, action="append", default=[], help=GIVEN_HELP)
    args = parser.parse_args(argv)

    # Runs never cross a line, so the texts can be read as one.
    given_files = [getattr(args, "context", None), *getattr(args, "given", [])]
    context = "\n".join(_read(path) for path in given_files if path)
    try:
        if args.command == "scenes":
            print(" ".join(scenes(_read(args.scenes_txt), args.images)))
        elif args.command == "all-scenes":
            print(" ".join(all_scenes(args.images)))
        elif args.command == "apply":
            content, policy = apply(args.root, args.out, args.version, context)
            pictures: dict[str, str] = {}
            if args.images:
                results = _results(args.results)
                paths, pictures = apply_images(args.root, args.images, results)
                content += paths
            args.lists.mkdir(parents=True, exist_ok=True)
            for name, paths in (("content.txt", content), ("policy.txt", policy)):
                (args.lists / name).write_text("".join(f"{path}\n" for path in paths))
            (args.lists / "pictures.json").write_text(json.dumps(pictures, indent=2) + "\n")
            print(f"First commit: {len(content)} files. Policy commit: {len(policy)} files.")
        else:
            checks = hand_checks(_read(args.development), _read(args.changed).split())
            problems = [
                line.removeprefix("- ")
                for line in _read(args.problems).splitlines()
                if line.startswith("- ")
            ]
            pictures = _results(args.pictures)
            facts = _results(args.facts)
            # A file that is given but cannot be read must not look like a clean result.
            unreadable = [
                path.name
                for path, data in (
                    (args.problems, "" if args.problems and args.problems.is_file() else None),
                    (args.pictures, pictures),
                    (args.facts, facts),
                )
                if path is not None and data is None
            ]
            problems += [f"The checks' result could not be read: {name}." for name in unreadable]
            body = pr_body(
                _read(args.findings),
                checks,
                model=args.model,
                problems=problems,
                facts=facts,
                pictures=pictures,
                expected=args.expected.split(),
                errors=_results(args.results),
                fixed=_fixed(args.fixed),
                fix_result=args.fix_result,
                known=given(args.root, context),
            )
            args.out.write_text(body)
            print("draft" if is_draft(problems, pictures or {}) else "ready")
    except ValueError as error:
        # stderr: the workflow keeps stdout (draft or ready, the scenes) in a variable, and the
        # reason must reach the log. No message holds the agent's text or a name it chose.
        print(error, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
