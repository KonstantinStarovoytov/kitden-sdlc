"""Draw the README picture in Kitden's own look.

Run: uv run --with fonttools --with brotli python scripts/make_picture.py [--font PATH]

Writes docs/images/sdlc-light.svg and sdlc-dark.svg. The look follows Kitden's docs/design.md:
the map's blocks, sockets and links, the lamps, the Quiet Den colors and Inter. It shows who
does what: you decide, a model only reads and writes text, a bot posts and publishes. Text is drawn
as outlines from Kitden's Inter (SIL OFL 1.1), because GitHub shows the SVG through <img>,
where no web font loads. Motion follows Kitden's rule "point, don't move": each lane's path
lights up in the route color, its links draw from left to right, and whoever acts there
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
CYCLE = 13.0  # seconds: three lanes light one after another, then the picture rests
LANE_STEP = 2.6  # seconds between lanes
STEP = 0.32  # seconds between the parts of one lane

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
        f".who-you{{color:{c['ink2']}}}.who-model{{color:{c['route']}}}",
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


# Two more marks for the legend and the cards: you, and a model. They take the text color.
PEOPLE = """
<symbol id="you" viewBox="0 0 24 24"><circle cx="12" cy="8" r="4.2" fill="currentColor"/>
<path fill="currentColor" d="M4 21c0-4.4 3.6-7.5 8-7.5s8 3.1 8 7.5Z"/></symbol>
<symbol id="model" viewBox="0 0 24 24"><path fill="currentColor" d="M12 2.5c.6 4.6 2.9 6.9
7.5 7.5-4.6.6-6.9 2.9-7.5 7.5-.6-4.6-2.9-6.9-7.5-7.5 4.6-.6 6.9-2.9 7.5-7.5Z"/>
<circle cx="19" cy="18.5" r="2" fill="currentColor"/></symbol>
"""
CARD_H = 92
GAP = 22
MARGIN = 16


def mark(who, x, y, size, cls):
    """The mark of whoever acts: a bot's icon, a model's spark or a person."""
    kind = {"you": "who-you", "model": "who-model"}.get(who, "")
    use = f'<use class="{kind}" href="#{who}" x="{x}" y="{y}" width="{size}" height="{size}"/>'
    return f'<g class="bot {cls}-nod">{use}</g>'


def card(ink, x, y, w, who, name, lines, cls):
    room = w - 24
    fits(ink, name, 17, 600, room - 34)
    for line in lines:
        fits(ink, line, 16, 400, room)
    out = [
        f'<rect class="block" x="{x}" y="{y}" width="{w:.1f}" height="{CARD_H}" rx="10"/>',
        f'<rect class="lit-block {cls}" x="{x}" y="{y}" width="{w:.1f}" height="{CARD_H}" '
        'rx="10"/>',
        mark(who, x + 12, y + 12, 26, cls),
        f'<path class="t" d="{ink.path(name, x + 46, y + 31, 17, 600)}"/>',
    ]
    for n, line in enumerate(lines):
        out.append(f'<path class="s" d="{ink.path(line, x + 12, y + 60 + n * 21, 16, 400)}"/>')
    return out


def row(ink, top, steps, lane_no):
    """Cards from left to right with links between them; returns parts and their count."""
    count = len(steps)
    w = (W - 2 * MARGIN - (count - 1) * GAP) / count
    out, part = [], 0
    for n, (who, name, lines) in enumerate(steps):
        x = MARGIN + n * (w + GAP)
        if n:
            out += link(x - GAP, x, top + CARD_H / 2, f"p{lane_no}-{part}")
            part += 1
        out += card(ink, x, top, w, who, name, lines, f"p{lane_no}-{part}")
        part += 1
    return out, part


def heading(ink, top, name, when, lamp_kind):
    parts = lamp(lamp_kind, MARGIN + 6, top + 13)
    parts.append(f'<path class="t" d="{ink.path(name, MARGIN + 20, top + 21, 20, 600)}"/>')
    x = MARGIN + 20 + ink.width(name, 20, 600) + 10
    parts.append(f'<path class="s" d="{ink.path(when, x, top + 21, 17, 400)}"/>')
    return parts


def legend(ink, y):
    items = [(["you"], "You decide"), (["model"], "A model reads, writes text"),
             (["lantern", "beacon", "kettle"], "A bot posts, no model")]
    out, x = [], MARGIN
    for marks, text in items:
        for m in marks:
            out.append(mark(m, x, y - 16, 20, "legend"))
            x += 22
        out.append(f'<path class="h" d="{ink.path(text, x + 4, y, 15, 400)}"/>')
        x += 4 + ink.width(text, 15, 400) + 22
    if x - 22 > W - MARGIN:
        raise SystemExit(f"the legend is {x - 22:.0f} wide, room is {W - MARGIN}")
    return out


def draw(ink: Ink, theme: str) -> str:
    out = [f'<rect class="bg" x="0.75" y="0.75" width="{W - 1.5}" height="0" rx="12"/>']
    out += legend(ink, 34)
    out.append(f'<line class="border" x1="{MARGIN}" y1="50" x2="{W - MARGIN}" y2="50"/>')
    lanes = []

    top = 66
    out += heading(ink, top, "Review", "· on every pull request", "on")
    parts, count = row(ink, top + 32, [
        ("model", "Claude, Luna", ["read the change"]),
        ("lantern", "Lantern", ["posts one comment"]),
        ("you", "You", ["fix or merge"]),
    ], 0)
    out += parts
    lanes.append(count)

    top += 32 + CARD_H + 26
    out += heading(ink, top, "Client watcher", "· every day", "on")
    parts, count = row(ink, top + 32, [
        ("model", "Claude", ["reads the release notes", "of 3 AI clients"]),
        ("lantern", "Lantern", ["opens an issue in Kitden"]),
        ("you", "You", ["confirm it or close it", "as a false alarm"]),
    ], 1)
    out += parts
    lanes.append(count)

    top += 32 + CARD_H + 26
    out += heading(ink, top, "Release", "· when you start it", "pv")
    parts, count = row(ink, top + 32, [
        ("you", "You", ["start", "Release prep"]),
        ("model", "Claude", ["drafts the notes", "and the README"]),
        ("beacon", "Beacon", ["opens the", "release PR"]),
        ("you", "You", ["review it", "and merge"]),
    ], 2)
    out += parts
    # After the merge, on their own: a strip under the cards.
    sy = top + 32 + CARD_H + 22
    lines = ["Then on their own: Beacon tags it and publishes to PyPI, the GitHub release,",
             "the MCP Registry and the release branch; Kettle updates Homebrew."]
    for line in lines:
        fits(ink, line, 16, 400, W - 2 * MARGIN - 24 - 54)
    sh = 20 + 21 * len(lines)
    last_x = W - MARGIN - ((W - 2 * MARGIN - 3 * GAP) / 4) / 2
    d = f"M{last_x} {sy - 22}L{last_x} {sy}"
    out.append(f'<path class="link" d="{d}"/><path class="lit p2-{count}" pathLength="1" d="{d}"/>')
    out.append(f'<rect class="group" x="{MARGIN}" y="{sy}" width="{W - 2 * MARGIN}" '
               f'height="{sh}" rx="10"/>')
    out.append(f'<rect class="lit-block p2-{count}" x="{MARGIN}" y="{sy}" '
               f'width="{W - 2 * MARGIN}" height="{sh}" rx="10"/>')
    out.append(mark("beacon", MARGIN + 12, sy + (sh - 24) / 2, 24, f"p2-{count}"))
    out.append(mark("kettle", MARGIN + 38, sy + (sh - 24) / 2, 24, f"p2-{count}"))
    for n, line in enumerate(lines):
        text = ink.path(line, MARGIN + 74, sy + 26 + n * 21, 16, 400)
        out.append(f'<path class="s" d="{text}"/>')
    lanes.append(count + 1)
    height = sy + sh + 16

    out[0] = out[0].replace('height="0"', f'height="{height - 1.5}"')
    desc = (
        "Who does what in kitden-sdlc. You decide; a model (Claude, Luna) only reads and writes "
        "text; a bot (Lantern, Kitden Beacon, Kitden Kettle) posts and publishes, with no model. "
        "Review, on every pull request: Claude and Luna read the change, Lantern posts one "
        "comment, you fix or merge. Client watcher, every day: Claude reads what Claude Code, "
        "Codex and Cursor changed, Lantern opens an issue in Kitden, you confirm it or close it "
        "as a false alarm. Release, when you start it: you start Release prep, Claude drafts the "
        "notes and the README, Beacon opens the release pull request, you review and merge it; "
        "then Beacon tags it and publishes it, and Kettle updates Homebrew."
    )
    head = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{height:.0f}" '
        f'viewBox="0 0 {W} {height:.0f}" role="img" aria-labelledby="title desc">\n'
        '<title id="title">Who does what in kitden-sdlc</title>\n'
        f'<desc id="desc">{desc}</desc>\n'
        "<!-- Made by scripts/make_picture.py. Text: Inter outlines, SIL OFL 1.1. -->\n"
        f"<style>\n{css(theme, lanes)}\n</style>\n"
        f"<defs>{symbols()}{PEOPLE}</defs>\n"
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
