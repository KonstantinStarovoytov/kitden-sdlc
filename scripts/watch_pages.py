"""Read watched sources and cut them into hashed sections."""

import hashlib
import re
import urllib.request
from dataclasses import dataclass
from html.parser import HTMLParser

import yaml

DROPPED = {"script", "style", "nav", "header", "footer"}
HEADINGS = {f"h{i}" for i in range(1, 7)}
BLOCKS = {"p", "div", "li", "br", "tr", "td", "th", "dt", "dd", "blockquote", "pre", "table",
          "ul", "ol", "section", *HEADINGS}


@dataclass
class Section:
    key: str
    text: str
    hash: str


def _build(parts: list[tuple[str, str]]) -> list[Section]:
    """Number a repeated heading; drop a section that repeats an earlier one exactly."""
    out, seen, done = [], {}, set()
    for key, text in parts:
        if not key and not text.strip():
            continue
        flat = re.sub(r"\s+", " ", text).strip()
        digest = hashlib.sha256(flat.encode()).hexdigest()
        if (key, digest) in done:
            continue
        done.add((key, digest))
        seen[key] = seen.get(key, 0) + 1
        if seen[key] > 1:
            key = f"{key} ({seen[key]})"
        out.append(Section(key, text.strip(), digest))
    return out


class _Html(HTMLParser):
    """Cut at the headings up to `level`, or, with `split`, at each `split` tag.

    With `split`, the key is the first heading inside the tag, a header or footer inside it
    is kept, and text outside the tags goes to the first section.
    """

    def __init__(self, level: int, split: str | None = None):
        super().__init__()
        self.headings = {f"h{i}" for i in range(1, level + 1)}
        self.split = split
        self.parts = [["", ""]]
        self.skip = 0
        self.inside = 0
        self.keyed = False
        self.in_heading = False

    def _dropped(self, tag):
        return tag in DROPPED and not (self.inside and tag in ("header", "footer"))

    def handle_starttag(self, tag, attrs):
        if self._dropped(tag):
            self.skip += 1
        elif self.skip:
            pass
        elif tag == self.split:
            self.inside += 1
            if self.inside == 1:
                self.parts.append(["", ""])
                self.keyed = False
        elif self.split:
            if self.inside and not self.keyed and tag in HEADINGS:
                self.in_heading = True
        elif tag in self.headings:
            self.parts.append(["", ""])
            self.in_heading = True
        self._block(tag)

    def handle_endtag(self, tag):
        if self._dropped(tag):
            self.skip = max(0, self.skip - 1)
        elif tag == self.split and self.inside:
            self.inside -= 1
        elif self.in_heading and tag in (HEADINGS if self.split else self.headings):
            self.in_heading = False
            self.keyed = True
        self._block(tag)

    def _part(self):
        return self.parts[-1] if self.inside or not self.split else self.parts[0]

    def _block(self, tag):
        if tag in BLOCKS and not self.skip:
            self._part()[1] += "\n"

    def handle_data(self, data):
        if self.skip:
            return
        if self.in_heading:
            self._part()[0] += data
        self._part()[1] += data


def sections(body: str, content_type: str, level: int = 3,
             split: str | None = None) -> list[Section]:
    if "html" in content_type:
        parser = _Html(level, split)
        parser.feed(body)
        return _build([(re.sub(r"\s+", " ", k).strip(), t) for k, t in parser.parts])
    parts = [["", ""]]
    fenced = False
    for line in body.splitlines():
        if line.startswith(("```", "~~~")):
            fenced = not fenced
        m = None if fenced else re.match(rf"#{{1,{level}}}\s+(.*)", line)
        if m:
            parts.append([m.group(1).strip(), ""])
        parts[-1][1] += line + "\n"
    return _build([(k, t) for k, t in parts])


def releases(payload: list[dict]) -> list[Section]:
    return _build([
        (r["tag_name"], r.get("body") or "")
        for r in payload
        if not r["prerelease"] and not r["draft"]
    ])


def get(url: str) -> tuple[str, str]:
    if not url.startswith("https://"):
        raise ValueError(f"only https URLs are allowed: {url}")
    with urllib.request.urlopen(url, timeout=20) as resp:  # noqa: S310
        if not resp.url.startswith("https://"):
            raise ValueError(f"redirected to a non-https URL: {resp.url}")
        charset = resp.headers.get_content_charset() or "utf-8"
        return resp.read().decode(charset, errors="replace"), resp.headers.get_content_type()


def load_sources(path) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)
