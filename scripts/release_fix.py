"""Decide what the release-prep fix pass may keep.

No model runs here. The fix pass runs on a copy of out/; this compares the folder before and
after it. Command:

  release_fix.py settle BEFORE AFTER --version X.Y.Z --changed FILE
      Puts back what the pass must not change: version.txt and scenes.txt, and any file it
      deleted. Writes the Kitden paths of the other files it changed or added to FILE, one per
      line, sorted. Refuses, changing nothing, a file release_apply does not know.
"""

import argparse
import shutil
import sys
from pathlib import Path

from release_apply import _files, refuse_unknown_names, target_for

SETTLED = ("version.txt", "scenes.txt")


def _same(a: Path, b: Path) -> bool:
    return b.is_file() and a.read_bytes() == b.read_bytes()


def settle(before: Path, after: Path, version: str) -> list[str]:
    """Put back in `after` the files the pass must not change: SETTLED (copied from `before`,
    or deleted when `before` has none) and any file it deleted. Returns the sorted Kitden paths
    of the other files whose bytes differ or that are new; findings.md is not listed. Raises
    ValueError, changing nothing, for a link or a name target_for does not know."""
    old = _files(before)
    new = _files(after)
    refuse_unknown_names(new)
    targets = {name: target_for(name, version) for name in new}
    for name in SETTLED:
        if name in old:
            (after / name).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(before / name, after / name)
        elif name in new:
            (after / name).unlink()
    for name in old:
        if name not in new and name not in SETTLED:
            (after / name).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(before / name, after / name)
    changed: set[str] = set()
    for name, target in targets.items():
        if target is None or name in SETTLED:
            continue
        if not _same(after / name, before / name):
            changed.add(target[0].as_posix())
    return sorted(changed)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    settle_cmd = commands.add_parser("settle")
    settle_cmd.add_argument("before", type=Path)
    settle_cmd.add_argument("after", type=Path)
    settle_cmd.add_argument("--version", required=True)
    settle_cmd.add_argument("--changed", type=Path, required=True)
    args = parser.parse_args(argv)

    try:
        paths = settle(args.before, args.after, args.version)
    except ValueError as error:
        print(error, file=sys.stderr)  # no message shows a name the agent chose
        return 1
    args.changed.write_text("".join(f"{path}\n" for path in paths))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
