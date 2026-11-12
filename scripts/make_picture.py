"""Draw the README picture in Kitden's own look.

Run: uv run --with fonttools --with brotli python scripts/make_picture.py [--font PATH]

Writes docs/images/sdlc-light.svg and sdlc-dark.svg. The look follows Kitden's docs/design.md:
the map's blocks, sockets and links, the lamps, the Quiet Den colors and Inter. Text is drawn
as outlines from Kitden's Inter (SIL OFL 1.1), because GitHub shows the SVG through <img>,
where no web font loads. Motion follows Kitden's rule "point, don't move": each lane's path
lights up in the route color, its links draw from left to right, and the bot that acts there
nods; then the picture rests. Live lanes breathe. It is still under reduced motion. The bots'
marks are the app icons of docs/images/apps without their backgrounds.
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
        "canvas": "#F5F6F8",
        "panel": "#FFFFFF",
        "wire": "#E1E4E9",
        "link": "#C3C8D0",
        "ink": "#161A21",
        "ink2": "#464D5B",
        "ink3": "#626977",
        "dim": "#EEF0F3",
        "route": "#A44226",
        "route_soft": "#F6E8E2",
        "on": "#1C8A4C",
        "warn": "#97590A",
        "off": "#80868F",
    },
    "dark": {
        "canvas": "#171A20",
        "panel": "#20242C",
        "wire": "#3B424D",
        "link": "#59616F",
        "ink": "#F2F3F5",
        "ink2": "#C1C6CF",
        "ink3": "#A5ADBA",
        "dim": "#1B1F26",
        "route": "#F09A7C",
        "route_soft": "#382A27",
        "on": "#47C27A",
        "warn": "#EAC27C",
        "off": "#707886",
    },
}

W = 720
COLS = {"in": (16, 150), "model": (190, 164), "out": (388, 152), "next": (562, 142)}
WIDE = 316  # "out" stretched to the right edge
BORDER_X = 371
BLOCK_H = 78
CYCLE = 13.0  # seconds: three lanes light one after another, then the picture rests
LANE_STEP = 2.6  # seconds between lanes
STEP = 0.32  # seconds between the parts of one lane
ICON = 34  # a bot's mark in a block

# The bots' marks, on a clear background: their <defs> go into the picture.
MARKS = ROOT / "docs/images/apps/marks.svg"


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
    return text[text.index("<defs>") + len("<defs>"):text.index("</defs>")]


def fits(ink, text, size, weight, room):
    width = ink.width(text, size, weight)
    if width > room:
        raise SystemExit(f"{text!r} is {width:.0f} wide, room is {room}")


def block(ink, col, y, title, sub, lit, w=None, bot=None):
    x, width = COLS[col]
    width = w or width
    room = width - 28 - (ICON + 8 if bot else 0)
    fits(ink, title, 21, 600, room)
    fits(ink, sub, 18, 400, room)
    parts = [
        f'<rect class="block" x="{x}" y="{y}" width="{width}" height="{BLOCK_H}" rx="10"/>',
        f'<rect class="lit-block {lit}" x="{x}" y="{y}" width="{width}" '
        f'height="{BLOCK_H}" rx="10"/>',
        f'<path class="t" d="{ink.path(title, x + 14, y + 33, 21, 600)}"/>',
        f'<path class="s" d="{ink.path(sub, x + 14, y + 59, 18, 400)}"/>',
    ]
    if bot:
        ix, iy = x + width - 14 - ICON, y + (BLOCK_H - ICON) / 2
        parts.append(f'<circle class="halo {lit}" cx="{ix + ICON / 2}" cy="{iy + ICON / 2}" '
                     f'r="{ICON / 2 + 6}"/>')
        parts.append(f'<g class="bot {lit}-nod"><use href="#{bot}" x="{ix}" y="{iy}" '
                     f'width="{ICON}" height="{ICON}"/></g>')
    return parts


def link(x1, x2, y, cls):
    mid = (x1 + x2) / 2
    d = f"M{x1} {y}C{mid} {y} {mid} {y} {x2} {y}"
    return [
        f'<path class="link" d="{d}"/>',
        f'<path class="lit {cls}" pathLength="1" d="{d}"/>',
        f'<circle class="sock" cx="{x1}" cy="{y}" r="4.5"/>',
        f'<circle class="sock" cx="{x2}" cy="{y}" r="4.5"/>',
    ]


def lamp(kind, cx, cy):
    if kind == "on":
        return [f'<circle class="lamp-on" cx="{cx}" cy="{cy}" r="5"/>']
    cls = {"unk": "lamp-unk", "pv": "lamp-pv"}[kind]
    return [f'<circle class="{cls}" cx="{cx}" cy="{cy}" r="4.5"/>']


def lane(ink, top, name, state, lamp_kind):
    parts = lamp(lamp_kind, 22, top + 18)
    parts.append(f'<path class="t" d="{ink.path(name, 36, top + 26, 22, 600)}"/>')
    x = 36 + ink.width(name, 22, 600) + 10
    parts.append(f'<path class="s" d="{ink.path(state, x, top + 26, 19, 400)}"/>')
    return parts


def chip(ink, x, y, text, bot=None):
    pad = 12 + (22 if bot else 0)
    w = ink.width(text, 17, 400) + 12 + pad
    parts = [
        f'<rect class="chip" x="{x}" y="{y}" width="{w:.1f}" height="32" rx="16"/>',
        f'<path class="c" d="{ink.path(text, x + pad, y + 22, 17, 400)}"/>',
    ]
    if bot:
        parts.append(f'<use href="#{bot}" x="{x + 9}" y="{y + 6}" width="20" height="20"/>')
    return parts, w


def css(theme, lanes):
    c = THEMES[theme]
    rules = [
        f".bg{{fill:{c['canvas']};stroke:{c['wire']}}}",
        f".block{{fill:{c['panel']};stroke:{c['wire']};stroke-width:1.5}}",
        f".block.model{{fill:{c['panel']}}}",
        f".t{{fill:{c['ink']}}}.s{{fill:{c['ink3']}}}.h{{fill:{c['ink3']}}}.c{{fill:{c['ink2']}}}",
        f".link{{fill:none;stroke:{c['link']};stroke-width:1.5}}",
        f".sock{{fill:{c['panel']};stroke:{c['off']};stroke-width:1.5}}",
        f".border{{stroke:{c['wire']};stroke-width:1.5;stroke-dasharray:5 6}}",
        f".chip{{fill:{c['dim']};stroke:{c['wire']};stroke-width:1.5}}",
        f".group{{fill:none;stroke:{c['off']};stroke-opacity:.6;stroke-width:1.5;"
        "stroke-dasharray:5 4}",
        f".lamp-on{{fill:{c['on']}}}",
        f".lamp-unk{{fill:none;stroke:{c['warn']};stroke-width:1.5;stroke-dasharray:2.5 2}}",
        f".lamp-pv{{fill:none;stroke:{c['route']};stroke-width:1.5;stroke-dasharray:2.5 2}}",
        f".lit{{fill:none;stroke:{c['route']};stroke-width:2.5;stroke-linecap:round;"
        "stroke-dasharray:1;stroke-dashoffset:0;opacity:0}",
        f".lit-block{{fill:{c['route_soft']};fill-opacity:.6;stroke:{c['route']};stroke-width:1.5;opacity:0}}",
        f".halo{{fill:{c['route_soft']};opacity:0}}",
        ".bot{transform-box:fill-box;transform-origin:center}",
        "@keyframes lit{0%{opacity:0}3%{opacity:1}24%{opacity:1}30%,100%{opacity:0}}",
        "@keyframes draw{0%{opacity:1;stroke-dashoffset:1}5%{stroke-dashoffset:0}"
        "24%{opacity:1;stroke-dashoffset:0}30%,100%{opacity:0;stroke-dashoffset:0}}",
        "@keyframes nod{0%,100%{transform:scale(1)}4%{transform:scale(1.18)}"
        "9%{transform:scale(1)}}",
        "@keyframes breathe{0%,100%{opacity:1}50%{opacity:.4}}",
    ]
    moving = [".lamp-on{animation:breathe 3.2s ease-in-out infinite}"]
    for i, count in enumerate(lanes):
        for j in range(count):
            delay = 0.6 + i * LANE_STEP + j * STEP
            timing = f"{CYCLE}s {delay:.2f}s infinite ease-in-out"
            moving.append(f".p{i}-{j}{{animation:lit {timing}}}")
            moving.append(f"path.p{i}-{j}{{animation:draw {timing}}}")
            moving.append(f".p{i}-{j}-nod{{animation:nod {timing}}}")
    rules.append("@media (prefers-reduced-motion:no-preference){" + "".join(moving) + "}")
    return "\n".join(rules)


def draw(ink: Ink, theme: str) -> str:
    out = [f'<rect class="bg" x="0.75" y="0.75" width="{W - 1.5}" height="0" rx="12"/>']
    head_y = 34
    out.append(f'<path class="h" d="{ink.path("The model reads", 190, head_y, 19, 600)}"/>')
    out.append(f'<path class="h" d="{ink.path("A script writes", 388, head_y, 19, 600)}"/>')

    tops = [52, 186, 320]
    lanes = []

    # Review: live.
    t = tops[0]
    out += lane(ink, t, "Review", "· live", "on")
    by = t + 38
    out += block(ink, "in", by, "Pull request", "in Kitden", "p0-x")
    out += block(ink, "model", by, "Claude, Luna", "read only", "p0-1")
    out += block(ink, "out", by, "One comment", "posted by Lantern", "p0-3", w=WIDE,
                 bot="lantern")
    y = by + BLOCK_H / 2
    out += link(166, 190, y, "p0-0") + link(354, 388, y, "p0-2")
    lanes.append(4)

    # Client watcher: live.
    t = tops[1]
    out += lane(ink, t, "Client watcher", "· live", "on")
    by = t + 38
    out += block(ink, "in", by, "Client docs", "3 AI clients", "p1-x")
    out += block(ink, "model", by, "Claude", "judges", "p1-1")
    out += block(ink, "out", by, "Issue in Kitden", "opened by Lantern", "p1-3", w=WIDE,
                 bot="lantern")
    y = by + BLOCK_H / 2
    out += link(166, 190, y, "p1-0") + link(354, 388, y, "p1-2")
    lanes.append(4)

    # Release: ready, not run yet.
    t = tops[2]
    out += lane(ink, t, "Release", "· ready", "pv")
    by = t + 38
    out += block(ink, "in", by, "New work", "on main", "p2-x")
    out += block(ink, "model", by, "Claude", "drafts", "p2-1")
    out += block(ink, "out", by, "Release PR", "you merge", "p2-3")
    out += block(ink, "next", by, "Tag", "Beacon", "p2-5", bot="beacon")
    y = by + BLOCK_H / 2
    out += link(166, 190, y, "p2-0") + link(354, 388, y, "p2-2") + link(540, 562, y, "p2-4")
    # The stores: quiet chips in a dashed group (like Kitden's "Add a plugin" block),
    # fed from the tag.
    box_x, box_y, box_w, pad = 388, by + BLOCK_H + 24, W - 16 - 388, 12
    tag_x = COLS["next"][0] + COLS["next"][1] / 2
    d = f"M{tag_x} {by + BLOCK_H}C{tag_x} {box_y - 8} {tag_x} {box_y - 8} {tag_x} {box_y}"
    out.append(f'<path class="link" d="{d}"/><path class="lit p2-6" d="{d}"/>')
    names = ["PyPI", "Homebrew", "MCP Registry", "release branch", "Claude directory"]
    chips = []
    cx, row_y, right = box_x + pad, box_y + pad, box_x + box_w - pad
    for name in names:
        bot = "kettle" if name == "Homebrew" else None
        _, w = chip(ink, 0, 0, name, bot)
        if cx + w > right:
            cx, row_y = box_x + pad, row_y + 40
        parts, w = chip(ink, cx, row_y, name, bot)
        chips += parts
        cx += w + 8
    box_h = row_y + 32 + pad - box_y
    out.append(
        f'<rect class="group" x="{box_x}" y="{box_y}" width="{box_w}" height="{box_h}" rx="10"/>'
    )
    out += chips
    for sx, sy in ((tag_x, by + BLOCK_H), (tag_x, box_y)):
        out.append(f'<circle class="sock" cx="{sx}" cy="{sy}" r="4.5"/>')
    lanes.append(7)
    height = box_y + box_h + 16

    out.append(f'<line class="border" x1="{BORDER_X}" y1="46" x2="{BORDER_X}" y2="{height - 14}"/>')
    out[0] = out[0].replace('height="0"', f'height="{height - 1.5}"')
    desc = (
        "Three lanes in Kitden's look. Left of the dashed line the model only reads; right of "
        "it a script without a model writes. Review is live: Claude and Luna read a pull "
        "request, and the Lantern app posts one comment. The client watcher is live: Claude "
        "judges the three clients' docs, and Lantern opens an issue in Kitden. The release flow "
        "is ready: Claude drafts the release pull request, you merge it, the Kitden Beacon app "
        "tags it, and scripts update PyPI, Homebrew (kept current by the Kitden Kettle app), the "
        "MCP Registry, the Claude directory and the release branch."
    )
    head = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{height:.0f}" '
        f'viewBox="0 0 {W} {height:.0f}" role="img" aria-labelledby="title desc">\n'
        '<title id="title">What kitden-sdlc runs</title>\n'
        f'<desc id="desc">{desc}</desc>\n'
        "<!-- Made by scripts/make_picture.py. Text: Inter outlines, SIL OFL 1.1. -->\n"
        f"<style>\n{css(theme, lanes)}\n</style>\n"
        f"<defs>{symbols()}</defs>\n"
    )
    return head + "\n".join(out) + "\n</svg>\n"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--font", type=Path, default=DEFAULT_FONT, help="Kitden's Inter woff2")
    args = parser.parse_args(argv)
    ink = Ink(args.font)
    for theme in THEMES:
        target = ROOT / "docs/images" / f"sdlc-{theme}.svg"
        target.write_text(draw(ink, theme))
        print(f"wrote {target.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
