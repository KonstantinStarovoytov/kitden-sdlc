"""The map's names, What and Why, taken from the workflow files.

Each workflow file starts with a `# What:` and a `# Why:` comment and has a `name:`. The map
(docs/map/index.html) keeps those three texts in one JSON block, `<script id="wf-text">`, and
its script puts them on each entry of `WF`. This command checks the block against the files,
or writes it again from them.

    map_text.py --check [--local]   print each difference; end with 1 when there is one
    map_text.py --write [--local]   write the block from the files, then check

This repository's files are read from the checkout. Kitden's and the tap's are read from
`main` on GitHub (raw.githubusercontent.com, and the contents API for their file lists); with
`--local` they are left out. A file that cannot be read is a difference too, so a check that
read nothing never passes.
"""

import argparse
import http.client
import json
import re
import sys
import urllib.request
from collections.abc import Callable
from pathlib import Path

Fetch = Callable[[str], str]

ROOT = Path(__file__).resolve().parent.parent
PAGE = ROOT / "docs/map/index.html"
HERE = "s"
FIELDS = ("name", "what", "why")
FETCH_SECONDS = 15
UNREADABLE = (OSError, ValueError, http.client.HTTPException)

BLOCK = re.compile(r'(<script type="application/json" id="wf-text">\n)(.*?)(\n</script>)', re.S)
WF_LIST = re.compile(r"\nconst WF = \[\n(.*?)\n\];", re.S)
ENTRY = re.compile(r"\{id:'([\w-]+)', r:'(\w)', file:'([\w.-]+)'")
JOB = re.compile(r"\{n:'([\w-]+)'")
DIRECTIVE = re.compile(r"#\s*(?:(?:zizmor|actionlint)\s*:|(?:yamllint|shellcheck)\s+disable)")
REPO = re.compile(r"(\w):\{name:'([\w.-]+)', url:'https://github\.com/([\w.-]+/[\w.-]+)'\}")


def fetch_url(url: str) -> str:
    """The text at an https address. No token goes along: this only reads public files."""
    if not url.startswith("https://"):
        raise ValueError("only https addresses")
    request = urllib.request.Request(url, headers={"User-Agent": "kitden-sdlc-map"})  # noqa: S310
    with urllib.request.urlopen(request, timeout=FETCH_SECONDS) as response:  # noqa: S310
        return response.read().decode()


def header(text: str) -> dict[str, str]:
    """The workflow's name, and its What and Why comments, each on one line.

    Only the comment lines at the top of the file count. What runs from `# What:` to
    `# Why:`, its paragraphs joined with a space. Why runs to the first bare `#`, the first
    line that is not a comment, or a tool's directive such as `# zizmor: ignore[...]`. In all
    22 workflows of the map today, Why ends at a bare `#` or at the `name:` line. A field that
    is not found is "", and the caller treats that as a problem."""
    found = re.search(r"^name:(.*)$", text, re.M)
    parts: dict[str, list[str]] = {"what": [], "why": []}
    part = None
    for line in text.splitlines():
        if not line.startswith("#") or DIRECTIVE.match(line):
            break
        if line.rstrip() == "#":
            if part == "why":
                break
            continue
        words = line[1:].strip()
        if words.startswith("What:"):
            part, words = "what", words[len("What:"):].strip()
        elif words.startswith("Why:"):
            part, words = "why", words[len("Why:"):].strip()
        if part:
            parts[part].append(words)
    return {"name": _yaml_text(found.group(1)) if found else "",
            "what": " ".join(w for w in parts["what"] if w),
            "why": " ".join(w for w in parts["why"] if w)}


def _yaml_text(value: str) -> str:
    """A one-line YAML value as text: spaces and quotes off, a trailing ` # comment` dropped."""
    value = value.strip()
    if value[:1] in ("'", '"'):
        end = value.find(value[0], 1)
        return value[1:end] if end > 0 else value
    return re.sub(r"\s+#.*$", "", value)


def _entries(html: str) -> list[tuple[str, str, str, str]]:
    """Each entry of `WF`: its id, repository letter, file name and source text."""
    found = WF_LIST.search(html)
    if not found:
        raise ValueError("the page has no `const WF = [` list")
    body = found.group(1)
    starts = list(ENTRY.finditer(body))
    ends = [m.start() for m in starts[1:]] + [len(body)]
    return [(m.group(1), m.group(2), m.group(3), body[m.start():end])
            for m, end in zip(starts, ends, strict=True)]


def map_ids(html: str) -> dict[str, tuple[str, str]]:
    """Each id of `WF`, with its repository letter and file name."""
    return {wf_id: (repo, file) for wf_id, repo, file, _ in _entries(html)}


def map_jobs(html: str) -> dict[str, list[str]]:
    """Each id of `WF`, with the names of the jobs the map lists for it."""
    return {wf_id: JOB.findall(source) for wf_id, _, _, source in _entries(html)}


def repos(html: str) -> dict[str, tuple[str, str]]:
    """Each repository letter, with its short name and owner/name on GitHub."""
    return {letter: (name, slug) for letter, name, slug in REPO.findall(html)}


def read_block(html: str) -> dict:
    """The texts in the page's `wf-text` block; {} when it has none."""
    found = BLOCK.search(html)
    return json.loads(found.group(2)) if found else {}


def _json(texts: dict) -> str:
    rows = [f" {json.dumps(wf_id)}: {json.dumps(value, ensure_ascii=False)}"
            for wf_id, value in texts.items()]
    text = "{\n" + ",\n".join(rows) + "\n}"
    # `<` and `>` as escapes, so no text can end the script element it sits in.
    return text.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")


def write_block(html: str, texts: dict) -> str:
    """The page with its `wf-text` block holding `texts`, put before the page's script."""
    found = BLOCK.search(html)
    if found:
        return html[:found.start(2)] + _json(texts) + html[found.end(2):]
    at = html.index("\n<script>\n") + 1
    block = '<script type="application/json" id="wf-text">\n' + _json(texts) + "\n</script>\n"
    return html[:at] + block + html[at:]


def _read_files(html: str, root: Path, fetch: Fetch | None):
    """The header of each workflow on the map, and the problems met reading them.

    Returns (texts by id, lines). An id whose file could not be read, or has an empty name,
    What or Why, is not in texts: it gets a line instead."""
    ids, names = map_ids(html), repos(html)
    texts: dict[str, dict[str, str]] = {}
    lines: list[str] = []
    # The repositories come from the map's own entries, so none of them can be left out.
    others = sorted({repo for repo, _ in ids.values()} - {HERE})
    for letter in [HERE] + (others if fetch else []):
        if letter != HERE and letter not in names:
            lines.append(f"{letter}: its repository is not in REPO")
            continue
        name, slug = names.get(letter, (letter, ""))
        on_map = {file: wf_id for wf_id, (r, file) in ids.items() if r == letter}
        if letter == HERE:
            folder = root / ".github/workflows"
            listed = {p.name for p in folder.iterdir() if p.suffix in (".yml", ".yaml")}
        else:
            try:
                answer = json.loads(fetch(
                    f"https://api.github.com/repos/{slug}/contents/.github/workflows?ref=main"))
                listed = {item["name"] for item in answer if item.get("type") == "file"
                          and item["name"].endswith((".yml", ".yaml"))}
            except (*UNREADABLE, KeyError, TypeError, AttributeError):
                listed = None
                lines.append(f"{name}: its list of workflow files could not be read")
        if listed is not None:
            lines += [f"{name}: {file} is not on the map" for file in sorted(listed - set(on_map))]
        for file, wf_id in on_map.items():
            if listed is not None and file not in listed:
                lines.append(f"{wf_id}: {name} has no {file}")
                continue
            try:
                if letter == HERE:
                    text = (root / ".github/workflows" / file).read_text()
                else:
                    text = fetch(
                        f"https://raw.githubusercontent.com/{slug}/main/.github/workflows/{file}")
            except UNREADABLE:
                lines.append(f"{wf_id}: its file could not be read")
                continue
            said = header(text)
            empty = [field for field in FIELDS if not said[field]]
            lines += [f"{wf_id}: its file has no {field}" for field in empty]
            if not empty:
                texts[wf_id] = said
    return texts, lines


def differences(html: str, root: Path, fetch: Fetch | None) -> list[str]:
    """One line for each text on the map that differs from its file, each workflow on the map
    with no file, each workflow file not on the map, and each file that could not be read.

    With `fetch` None only this repository's workflows are checked."""
    block = read_block(html)
    texts, lines = _read_files(html, root, fetch)
    for wf_id, said in texts.items():
        shown = block.get(wf_id, {})
        for field in FIELDS:
            if shown.get(field) != said[field]:
                now = f'is "{shown[field]}"' if field in shown else "is missing"
                lines.append(f'{wf_id}: {field} {now}, the file says "{said[field]}"')
    lines += [f"{wf_id}: the text block has it, the map does not"
              for wf_id in block if wf_id not in map_ids(html)]
    return lines


def written(html: str, root: Path, fetch: Fetch | None) -> str:
    """The page with the block written from the files. A workflow whose file could not be read
    or has an empty text, or whose repository was left out, keeps what the block had."""
    block = read_block(html)
    texts, _ = _read_files(html, root, fetch)
    new = {wf_id: texts.get(wf_id) or block.get(wf_id) for wf_id in map_ids(html)}
    return write_block(html, {wf_id: value for wf_id, value in new.items() if value})


def main(argv: list[str] | None = None, fetch: Fetch = fetch_url) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    what = parser.add_mutually_exclusive_group(required=True)
    what.add_argument("--check", action="store_true", help="print the differences")
    what.add_argument("--write", action="store_true", help="write the block from the files")
    parser.add_argument("--local", action="store_true", help="leave Kitden and the tap out")
    args = parser.parse_args(argv)
    use = None if args.local else fetch
    html = PAGE.read_text()
    if args.write:
        html = written(html, ROOT, use)
        PAGE.write_text(html)
    lines = differences(html, ROOT, use)
    for line in lines:
        print(line)
    return 1 if lines else 0


if __name__ == "__main__":
    sys.exit(main())
