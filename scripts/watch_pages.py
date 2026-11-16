"""Read watched sources and cut them into hashed sections."""

import hashlib
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from html.parser import HTMLParser

import yaml

import doc_address

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


def _loose(key: str) -> str:
    """`key` with no spacing at all and in one case: how pick compares a second time."""
    return "".join(key.split()).casefold()


# The number _build adds to a heading found again on the page: "Example (2)".
NUMBERED = re.compile(r"(.*) \((?:[2-9]|[1-9][0-9]+)\)", re.DOTALL)


def pick(all_sections: list[Section], headings: list[str]) -> list[Section]:
    """The sections of a page that `headings` name, in page order, each once.

    A heading names every section whose key is the heading, or the heading with the number
    `sections()` adds to a repeat (" (2)", " (3)", ...): a page that gains a second
    "Example" has the new one as "Example (2)", and the feed names it "Example". When no key
    is the heading that way, it names those whose key reads the same ignoring case and
    spacing. A heading that is not on the page, or is blank, is skipped. Headings are only
    compared here.
    """
    exact: dict[str, list[int]] = {}
    loose: dict[str, list[int]] = {}
    for place, section in enumerate(all_sections):
        numbered = NUMBERED.fullmatch(section.key)
        names = {section.key, numbered.group(1)} if numbered else {section.key}
        for name in names:
            exact.setdefault(name, []).append(place)
        for name in {_loose(n) for n in names}:
            loose.setdefault(name, []).append(place)
    chosen: set[int] = set()
    for heading in headings:
        if not heading.strip():
            continue
        chosen.update(exact.get(heading) or loose.get(_loose(heading)) or [])
    return [all_sections[place] for place in sorted(chosen)]


def releases(payload: list[dict]) -> list[Section]:
    return _build([
        (r["tag_name"], r.get("body") or "")
        for r in payload
        if not r["prerelease"] and not r["draft"]
    ])


def get(url: str, limit: int | None = None) -> tuple[str, str]:
    """The body and content type of `url`. With `limit`, a body over `limit` bytes raises
    ValueError."""
    if not url.startswith("https://"):
        raise ValueError(f"only https URLs are allowed: {url}")
    # The check above has just made sure the address is https.
    request = urllib.request.Request(url, headers={"User-Agent": doc_address.USER_AGENT})  # noqa: S310
    with urllib.request.urlopen(request, timeout=20) as resp:  # noqa: S310
        if not resp.url.startswith("https://"):
            raise ValueError(f"redirected to a non-https URL: {resp.url}")
        charset = resp.headers.get_content_charset() or "utf-8"
        data = resp.read() if limit is None else resp.read(limit + 1)
        if limit is not None and len(data) > limit:
            raise ValueError(f"the body of {url} is over {limit} bytes")
        return data.decode(charset, errors="replace"), resp.headers.get_content_type()


MARKDOWN = ("text/markdown", "text/plain")
GONE = (404, 410)


def _markdown(address: str, hosts, opener) -> tuple[str, str, str] | None:
    """Read `address` as markdown. None when it is gone (404, 410) or has another type.

    Any other error goes out, so a timeout or a busy server leaves the page unread that day
    instead of reading it in a different format.
    """
    try:
        body, kind, read_from = doc_address.read(address, hosts, opener)
    except urllib.error.HTTPError as e:
        if e.code in GONE:
            return None
        raise
    return (body, kind, read_from) if kind in MARKDOWN else None


def get_doc(address: str, hosts, opener=None) -> tuple[str, str, str]:
    """Read a doc page as `<address>.md` first, and as the plain address when there is none.

    Gives the body, the content type and the address read from. The `.md` answer counts only
    when its type is text/markdown or text/plain; the plain address is read only when the
    `.md` one is gone (404, 410) or has another type. When the plain read was redirected, the
    `.md` of the address it ended at is tried once more under the same rule, and the page
    already read is kept when that one has none. Every other error goes out.
    """
    if address.endswith(".md"):
        return doc_address.read(address, hosts, opener)
    found = _markdown(address + ".md", hosts, opener)
    if found:
        return found
    page = doc_address.read(address, hosts, opener)
    read_from = page[2]
    if read_from != address and not read_from.endswith(".md"):
        found = _markdown(read_from + ".md", hosts, opener)
        if found:
            return found
    return page


def load_sources(path) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)
