"""Draw the README pictures in Kitden's own look: who does what in review, the client watcher
and the release.

Run: uv run --with fonttools --with brotli python scripts/make_picture.py [--font PATH]

Writes docs/images/<name>-light.svg and <name>-dark.svg for review, watcher and release. Each
picture has three columns: you, a model, and the bots and scripts. The steps go from top to
bottom, each card in the column of whoever does it. The look follows Kitden's docs/design.md:
the map's blocks, sockets and links, the Quiet Den colors and Inter. Text is drawn as outlines
from Kitden's Inter (SIL OFL 1.1), because GitHub shows the SVG through <img>, where no web
font loads. Motion follows Kitden's rule "point, don't move": the steps light one after
another and the links between them draw, then the picture rests. It is still under reduced
motion. The bots' marks are the app icons of docs/images/apps without their backgrounds.
"""

import argparse
import io
from pathlib import Path

from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen
from fontTools.ttLib import TTFont
from fontTools.varLib.instancer import instantiateVariableFont

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_FONT = (
    ROOT.parents[3] / "mcp-gateway/src/kitden/web/static/fonts/inter-latin-wght-normal.woff2"
)

# Kitden's tokens (docs/design.md, Color roles; style.css :root and the dark block).
THEMES = {
    "light": {
        "canvas": "#F5F6F8", "panel": "#FFFFFF", "wire": "#E1E4E9", "link": "#C3C8D0",
        "ink": "#161A21", "ink2": "#464D5B", "ink3": "#626977", "dim": "#EEF0F3",
        "route": "#A44226", "route_soft": "#F6E8E2", "off": "#80868F",
    },
    "dark": {
        "canvas": "#171A20", "panel": "#20242C", "wire": "#3B424D", "link": "#59616F",
        "ink": "#F2F3F5", "ink2": "#C1C6CF", "ink3": "#A5ADBA", "dim": "#1B1F26",
        "route": "#F09A7C", "route_soft": "#382A27", "off": "#707886",
    },
}

W = 720
MARGIN = 16
HEAD = 64  # the column titles
GAP_X = 14  # between columns
GAP_Y = 22  # between rows
STEP = 0.45  # seconds between steps
REST = 4.0  # seconds the picture rests at the end
TITLE, LINE = 16, 14  # text sizes

# The bots' marks, on a clear background: their <defs> go into the picture.
MARKS = ROOT / "docs/images/apps/marks.svg"
YOU = """<symbol id="you" viewBox="0 0 24 24"><circle cx="12" cy="8" r="4.2" fill="currentColor"/>
<path fill="currentColor" d="M4 21c0-4.4 3.6-7.5 8-7.5s8 3.1 8 7.5Z"/></symbol>"""

COLUMNS = (("you", "You", "you decide"), ("model", "A model", "reads, writes text only"),
           ("bot", "Bots and scripts", "post and publish, no model"))

# A step: (id, column, mark or None, title, detail lines). A row holds one or more steps; two
# steps in one column of a row run side by side. Edges join steps, top to bottom.
PICTURES = {
    "review": {
        "title": "Review: two models read every pull request, one comment comes back",
        "widths": (152, 318, 190),
        "rows": [
            [("open", "you", "you", "Open a PR", ["to main in Kitden"])],
            [("cap", "bot", None, "A daily cap", ["at most 10 reviews a day"])],
            [("claude", "model", None, "Claude", ["Sonnet 5.5 reads", "the change; tools",
                                                  "only read"]),
             ("luna", "model", None, "GPT-6 Luna", ["reads it on its own,", "with no network"])],
            [("post", "bot", "lantern", "Lantern", ["merges both reviews", "into one comment;",
                                                    "fixed ones stay, marked"])],
            [("merge", "you", "you", "Fix or merge", ["it never approves", "or blocks"])],
        ],
        "edges": [("open", "cap"), ("cap", "claude"), ("cap", "luna"), ("claude", "post"),
                  ("luna", "post"), ("post", "merge")],
    },
    "watcher": {
        "title": "Client watcher: every day, it checks what Claude Code, Codex and Cursor changed",
        "widths": (160, 236, 264),
        "rows": [
            [("fetch", "bot", None, "Fetch, 05:17 UTC", ["new parts of the release notes",
                                                          "and docs of the three clients"])],
            [("screen", "model", None, "Claude Sonnet 5.5", ["checks every row of Kitden's",
                                                              "list, with a quote"])],
            [("assess", "model", None, "Reads Kitden's code", ["gives a type and a severity:",
                                                               "major, medium or minor"])],
            [("second", "model", None, "A second look", ["checks a sure break",
                                                         "or wrong data again"])],
            [("issue", "bot", "lantern", "Lantern", ["a sure major one: an issue",
                                                     "at once, two a week at most;",
                                                     "the rest: Monday's summary"])],
            [("decide", "you", "you", "Confirm it", ["or close it as", "a false alarm"])],
        ],
        "edges": [("fetch", "screen"), ("screen", "assess"), ("assess", "second"),
                  ("second", "issue"), ("issue", "decide")],
    },
    "release": {
        "title": "Release: you start it and merge one pull request; the rest runs on its own",
        "widths": (160, 190, 310),
        "rows": [
            [("start", "you", "you", "Start", ["Release prep", "in Kitden's Actions"])],
            [("gather", "bot", None, "Gather the changes", ["log, merged pull requests,",
                                                           "diff since the last tag"])],
            [("draft", "model", None, "Claude drafts", ["the release notes,",
                                                        "README, policy edits"])],
            [("prep", "bot", None, "Check and prepare", ["set the version, record the",
                                                         "README pictures on macOS"])],
            [("pr", "bot", "beacon", "Beacon", ["opens the pull request", "Kitden X.Y.Z"])],
            [("merge", "you", "you", "Review", ["and merge it"])],
            [("tag", "bot", "beacon", "Beacon", ["tags vX.Y.Z"])],
            [("build", "bot", None, "Build and test", ["on Linux and macOS, then PyPI",
                                                       "and the GitHub release"])],
            [("stores", "bot", "beacon", "Beacon", ["moves the release branch (Claude",
                                                    "directory, marketplaces), opens",
                                                    "the Homebrew pull request"])],
            [("registry", "bot", None, "MCP Registry", ["published with GitHub's token,",
                                                       "then one table of every store"])],
            [("kettle", "bot", "kettle", "Kettle, every day", ["keeps the Homebrew formula",
                                                               "up to date"])],
            [("watch", "bot", "lantern", "Lantern, every day", ["an issue when a store is",
                                                                "behind or a release is due"])],
        ],
        "edges": [("start", "gather"), ("gather", "draft"), ("draft", "prep"), ("prep", "pr"),
                  ("pr", "merge"), ("merge", "tag"), ("tag", "build"), ("build", "stores"),
                  ("stores", "registry")],
    },
}


class Ink:
    """Inter outlines at two weights, as SVG path data."""

    def __init__(self, font_path: Path):
        data = font_path.read_bytes()
        self.faces = {}
        for weight in (400, 600):
            font = TTFont(io.BytesIO(data))
            self.faces[weight] = instantiateVariableFont(font, {"wght": weight})

    def width(self, text: str, size: float, weight: int) -> float:
        font = self.faces[weight]
        cmap, hmtx = font.getBestCmap(), font["hmtx"]
        upem = font["head"].unitsPerEm
        return sum(hmtx[cmap[ord(c)]][0] for c in text) * size / upem

    def path(self, text: str, x: float, y: float, size: float, weight: int) -> str:
        font = self.faces[weight]
        cmap, hmtx, glyphs = font.getBestCmap(), font["hmtx"], font.getGlyphSet()
        scale = size / font["head"].unitsPerEm
        pen = SVGPathPen(glyphs, ntos=lambda v: f"{v:.1f}".rstrip("0").rstrip("."))
        cursor = x
        for char in text:
            name = cmap[ord(char)]
            glyphs[name].draw(TransformPen(pen, (scale, 0, 0, -scale, cursor, y)))
            cursor += hmtx[name][0] * scale
        return pen.getCommands()


def symbols() -> str:
    """The gradients and symbols of the bots' marks, from docs/images/apps/marks.svg."""
    text = MARKS.read_text()
    return text[text.index("<defs>") + len("<defs>"):text.index("</defs>")] + YOU


def fits(ink, text, size, weight, room):
    width = ink.width(text, size, weight)
    if width > room:
        raise SystemExit(f"{text!r} is {width:.0f} wide, room is {room:.0f}")


def card_height(lines) -> float:
    return 40 + LINE * 1.35 * len(lines) + 4


def layout(pic):
    """Each step's box: x, y, width, height, column."""
    widths = pic["widths"]
    if sum(widths) + GAP_X * (len(widths) - 1) != W - 2 * MARGIN:
        raise SystemExit(f"the columns are {sum(widths)} wide; with the gaps they must fill "
                         f"{W - 2 * MARGIN}")
    xs, x = {}, MARGIN
    for (key, *_), width in zip(COLUMNS, widths, strict=True):
        xs[key] = (x, width)
        x += width + GAP_X
    boxes, y = {}, HEAD + 12
    for row in pic["rows"]:
        h = max(card_height(step[4]) for step in row)
        by_col = {}
        for step in row:
            by_col.setdefault(step[1], []).append(step)
        for col, steps in by_col.items():
            cx, cw = xs[col]
            w = (cw - GAP_X * (len(steps) - 1)) / len(steps)
            for n, step in enumerate(steps):
                boxes[step[0]] = (cx + n * (w + GAP_X), y, w, h, col)
        y += h + GAP_Y
    return xs, boxes, y - GAP_Y + 18


def card(ink, step, box, cls):
    sid, col, mark, title, lines = step
    x, y, w, h, _ = box
    shift = 30 if mark else 0
    fits(ink, title, TITLE, 600, w - 24 - shift)
    for line in lines:
        fits(ink, line, LINE, 400, w - 24)
    kind = "you" if col == "you" else "block"
    out = [
        f'<rect class="{kind}" x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" rx="10"/>',
        f'<rect class="lit-block {cls}" x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" '
        f'height="{h:.1f}" rx="10"/>',
    ]
    if mark:
        tint = ' class="who-you"' if mark == "you" else ""
        out.append(f'<use{tint} href="#{mark}" x="{x + 12:.1f}" y="{y + 9:.1f}" width="22" '
                   'height="22"/>')
    out.append(f'<path class="t" d="{ink.path(title, x + 12 + shift, y + 26, TITLE, 600)}"/>')
    for n, line in enumerate(lines):
        text = ink.path(line, x + 12, y + 48 + n * LINE * 1.35, LINE, 400)
        out.append(f'<path class="s" d="{text}"/>')
    return out


def edge(a, b, cls):
    ax, ay = a[0] + a[2] / 2, a[1] + a[3]
    bx, by = b[0] + b[2] / 2, b[1]
    mid = (ay + by) / 2
    d = f"M{ax:.1f} {ay:.1f}C{ax:.1f} {mid:.1f} {bx:.1f} {mid:.1f} {bx:.1f} {by:.1f}"
    return [
        f'<path class="link" d="{d}"/>',
        f'<path class="lit {cls}" pathLength="1" d="{d}"/>',
        f'<circle class="sock" cx="{ax:.1f}" cy="{ay:.1f}" r="4"/>',
        f'<circle class="sock" cx="{bx:.1f}" cy="{by:.1f}" r="4"/>',
    ]


def css(theme, count):
    c = THEMES[theme]
    cycle = count * STEP + REST
    rules = [
        f".bg{{fill:{c['canvas']};stroke:{c['wire']}}}",
        f".block{{fill:{c['panel']};stroke:{c['wire']};stroke-width:1.5}}",
        f".you{{fill:{c['panel']};stroke:{c['route']};stroke-opacity:.55;stroke-width:1.5}}",
        f".lane{{fill:{c['dim']}}}",
        f".t{{fill:{c['ink']}}}.s{{fill:{c['ink3']}}}.h{{fill:{c['ink2']}}}.c{{fill:{c['ink3']}}}",
        f".who-you{{color:{c['route']}}}",
        f".link{{fill:none;stroke:{c['link']};stroke-width:1.5}}",
        f".sock{{fill:{c['panel']};stroke:{c['off']};stroke-width:1.5}}",
        f".lit{{fill:none;stroke:{c['route']};stroke-width:2.5;stroke-linecap:round;"
        "stroke-dasharray:1;stroke-dashoffset:0;opacity:0}",
        f".lit-block{{fill:{c['route_soft']};fill-opacity:.55;stroke:{c['route']};"
        "stroke-width:1.5;opacity:0}",
    ]
    on, off = 100 * 0.15 / cycle, 100 * (count * STEP + 1.2) / cycle
    rules.append(f"@keyframes lit{{0%{{opacity:0}}{on:.1f}%{{opacity:1}}{off:.1f}%{{opacity:1}}"
                 f"{off + 4:.1f}%,100%{{opacity:0}}}}")
    rules.append(f"@keyframes draw{{0%{{opacity:1;stroke-dashoffset:1}}{on * 2:.1f}%"
                 f"{{stroke-dashoffset:0}}{off:.1f}%{{opacity:1;stroke-dashoffset:0}}"
                 f"{off + 4:.1f}%,100%{{opacity:0;stroke-dashoffset:0}}}}")
    moving = []
    for n in range(count):
        timing = f"{cycle:.2f}s {0.5 + n * STEP:.2f}s infinite ease-in-out"
        moving.append(f".q{n}{{animation:lit {timing}}}path.q{n}{{animation:draw {timing}}}")
    rules.append("@media (prefers-reduced-motion:no-preference){" + "".join(moving) + "}")
    return "\n".join(rules)


def draw(ink: Ink, name: str, theme: str) -> str:
    pic = PICTURES[name]
    xs, boxes, height = layout(pic)
    out = [f'<rect class="bg" x="0.75" y="0.75" width="{W - 1.5}" height="{height - 1.5:.1f}" '
           'rx="12"/>']
    for key, label, note in COLUMNS:
        x, w = xs[key]
        out.append(f'<rect class="lane" x="{x}" y="{HEAD - 50}" width="{w}" '
                   f'height="{height - HEAD + 36:.1f}" rx="10"/>')
        fits(ink, label, 15, 600, w - 20)
        fits(ink, note, 13, 400, w - 20)
        out.append(f'<path class="h" d="{ink.path(label, x + 10, HEAD - 28, 15, 600)}"/>')
        out.append(f'<path class="c" d="{ink.path(note, x + 10, HEAD - 10, 13, 400)}"/>')
    order = [step[0] for row in pic["rows"] for step in row]
    step_no = {sid: n for n, sid in enumerate(order)}
    for a, b in pic["edges"]:
        out += edge(boxes[a], boxes[b], f"q{step_no[b]}")
    for row in pic["rows"]:
        for step in row:
            out += card(ink, step, boxes[step[0]], f"q{step_no[step[0]]}")
    steps = "; ".join(f"{s[3]}: {' '.join(s[4])}" for row in pic["rows"] for s in row)
    head = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{height:.0f}" '
        f'viewBox="0 0 {W} {height:.0f}" role="img" aria-labelledby="title desc">\n'
        f'<title id="title">{pic["title"]}</title>\n'
        f'<desc id="desc">Three columns: you, a model, and the bots and scripts. {steps}.</desc>\n'
        "<!-- Made by scripts/make_picture.py. Text: Inter outlines, SIL OFL 1.1. -->\n"
        f"<style>\n{css(theme, len(order))}\n</style>\n"
        f"<defs>{symbols()}</defs>\n"
    )
    return head + "\n".join(out) + "\n</svg>\n"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--font", type=Path, default=DEFAULT_FONT, help="Kitden's Inter woff2")
    args = parser.parse_args(argv)
    ink = Ink(args.font)
    for name in PICTURES:
        for theme in THEMES:
            target = ROOT / "docs/images" / f"{name}-{theme}.svg"
            target.write_text(draw(ink, name, theme))
            print(f"wrote {target.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
