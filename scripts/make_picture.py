"""Draw the README pictures in Kitden's own look: who does what in review, the client watcher
and the release.

Run: uv run --with fonttools --with brotli python scripts/make_picture.py [--font PATH]

Writes docs/images/<name>-light.svg and <name>-dark.svg for review, watcher and release. The
steps run as a snake, left to right and back; each card shows who does it: your steps are
filled, a model's are dashed, a bot shows its mark. Only Kitden's own colors are used; the
pictures tell apart by their title, when they run and the shape of the snake. The look
follows Kitden's docs/design.md: the map's blocks and links, the Quiet Den colors and Inter.
Text is drawn as outlines from Kitden's Inter (SIL OFL 1.1), because GitHub shows the SVG
through <img>, where no web font loads. Motion follows Kitden's rule "point, don't move": the
steps light one after another and the links between them draw, then the picture rests. It is
still under reduced motion. The bots' marks are the app icons of docs/images/apps without
their backgrounds.
"""

import argparse
import base64
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
TURN = 22  # room at each side for the snake's turn
GAP_X = 26  # between cards in a row
GAP_Y = 30  # between rows
HEAD = 70  # the title band and the legend
STEP = 0.4  # seconds between steps
REST = 4.0  # seconds the picture rests at the end
TITLE, LINE = 15, 13.5  # text sizes

# The bots' marks, on a clear background: their <defs> go into the picture.
MARKS = ROOT / "docs/images/apps/marks.svg"
YOU = """<symbol id="you" viewBox="0 0 24 24"><circle cx="12" cy="8" r="4.2" fill="currentColor"/>
<path fill="currentColor" d="M4 21c0-4.4 3.6-7.5 8-7.5s8 3.1 8 7.5Z"/></symbol>"""

# A step: (id, who, mark or None, title, detail lines); who is you, model, bot or script. A
# list of two steps is one slot with two steps side by side in time (stacked). The steps run
# as a snake: left to right, then right to left, `per_row` slots a row.
PICTURES = {
    "review": {
        "name": "Review",
        "when": "on every pull request",
        "tile": "lantern",
        "groups": [{"per_row": 5, "gap": 18, "steps": [
            ("open", "you", "you", "You", ["open a pull", "request"]),
            ("cap", "script", None, "Daily cap", ["10 reviews", "a day at most"]),
            [("claude", "model", None, "Claude", ["Sonnet 5.5"]),
             ("luna", "model", None, "Luna", ["GPT-6, offline"])],
            ("post", "bot", "lantern", "Lantern", ["merges both", "into one", "comment"]),
            ("merge", "you", "you", "You", ["fix or merge;", "no approvals"]),
        ]}],
    },
    "watcher": {
        "name": "Client watcher",
        "when": "every day, 05:17 UTC",
        "tile": "clients",
        "groups": [{"per_row": 3, "steps": [
            ("fetch", "script", None, "Fetch", ["new release notes, docs", "of 3 AI clients"]),
            ("screen", "model", None, "Claude Sonnet 5.5", ["checks every row of",
                                                             "Kitden's list, with a quote"]),
            ("assess", "model", None, "Reads Kitden's code", ["type and severity:",
                                                               "major, medium, minor"]),
            ("second", "model", None, "A second look", ["at a sure break", "or wrong data"]),
            ("issue", "bot", "lantern", "Lantern", ["sure major: an issue now;",
                                                    "others: Monday's summary"]),
            ("decide", "you", "you", "You", ["confirm it, or close", "it as a false alarm"]),
        ]}],
    },
    "release": {
        "name": "Release",
        "when": "when you start it",
        "tile": "beacon",
        "groups": [
            {"label": "1 · Prepare", "note": "with Claude; it ends in a pull request you review",
             "per_row": 3, "steps": [
                 ("start", "you", "you", "You", ["start Release prep", "in Kitden's Actions"]),
                 ("gather", "script", None, "Gather", ["what changed since", "the last tag"]),
                 ("draft", "model", None, "Claude", ["drafts the release",
                                                     "notes, README, policy"]),
                 ("prep", "script", None, "Prepare", ["sets the version, records",
                                                      "the README pictures"]),
                 ("pr", "bot", "beacon", "Beacon", ["opens the pull", "request Kitden X.Y.Z"]),
                 ("merge", "you", "you", "You", ["review it, edit", "if you like, merge"]),
             ]},
            {"label": "2 · Publish", "note": "no model; it runs on its own after your merge",
             "per_row": 4, "steps": [
                 ("tag", "bot", "beacon", "Beacon", ["tags vX.Y.Z"]),
                 ("build", "script", None, "Build, test", ["then PyPI and", "GitHub release"]),
                 ("stores", "bot", "beacon", "Beacon", ["release branch,", "Homebrew PR"]),
                 ("registry", "script", None, "MCP Registry", ["and a table of", "every store"]),
             ]},
            {"label": "Every day", "note": "no model", "per_row": 4, "chain": False, "steps": [
                ("kettle", "bot", "kettle", "Kettle", ["keeps Homebrew", "up to date"]),
                ("watch", "bot", "lantern", "Lantern", ["an issue if a store", "is behind"]),
            ]},
        ],
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


GROUP_HEAD = 30  # a group's label, above its cards
GROUP_PAD = 12  # inside a group's frame


def gap(group) -> float:
    return group.get("gap", GAP_X)


def slot_w(group) -> float:
    per_row = group["per_row"]
    return (W - 2 * (MARGIN + TURN) - (per_row - 1) * gap(group)) / per_row


def card_h(steps) -> float:
    def need(step):
        return 36 + LINE * 1.3 * len(step[4]) + 8
    singles = [need(s) for s in steps if isinstance(s, tuple)]
    stacked = [2 * (need(s) - 6) + 6 for pair in steps if isinstance(pair, list) for s in pair[:1]]
    return max(singles + stacked)


def layout(pic):
    """Every slot in order as (x, y, w, h, row, group), and each group's frame."""
    slots, frames, y = [], [], HEAD + 16
    labelled = any(g.get("label") for g in pic["groups"])
    h = max(card_h(g["steps"]) for g in pic["groups"])
    for gi, group in enumerate(pic["groups"]):
        top = y
        if labelled:
            y += GROUP_HEAD
        per, w = group["per_row"], slot_w(group)
        rows = (len(group["steps"]) + per - 1) // per
        for n in range(len(group["steps"])):
            r, c = divmod(n, per)
            col = c if r % 2 == 0 else per - 1 - c
            x = MARGIN + TURN + col * (w + gap(group))
            slots.append((x, y + r * (h + GAP_Y), w, h, (gi, r), gi))
        y += rows * h + (rows - 1) * GAP_Y
        if labelled:
            frames.append((group, top, y + GROUP_PAD))
            y += GROUP_PAD + 18
        else:
            y += GAP_Y
    return slots, frames, y - (18 if labelled else GAP_Y) + 18


def card(ink, step, box, cls):
    _, who, mark, title, lines = step
    x, y, w, h = box
    shift = 26 if mark else 0
    fits(ink, title, TITLE, 600, w - 22 - shift)
    for line in lines:
        fits(ink, line, LINE, 400, w - 22)
    style = {"you": "you", "model": "model"}.get(who, "block")
    out = [
        f'<rect class="{style}" x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" rx="9"/>',
        f'<rect class="lit-block {cls}" x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" '
        f'height="{h:.1f}" rx="9"/>',
    ]
    if mark:
        tint = ' class="who-you"' if mark == "you" else ""
        out.append(f'<use{tint} href="#{mark}" x="{x + 10:.1f}" y="{y + 8:.1f}" width="20" '
                   'height="20"/>')
    out.append(f'<path class="t" d="{ink.path(title, x + 11 + shift, y + 24, TITLE, 600)}"/>')
    for n, line in enumerate(lines):
        text = ink.path(line, x + 11, y + 44 + n * LINE * 1.3, LINE, 400)
        out.append(f'<path class="s" d="{text}"/>')
    return out


def joint(a, b, cls):
    """From slot a to slot b: across in a row, around the end into the next row, or down into
    the next group."""
    ax, ay, aw, ah, arow, ag = a
    bx, by, bw, bh, brow, bg = b
    if ag != bg and not (arow[1] % 2 == 1 and abs(ax - bx) < 1):
        x1, y1, x2, y2 = ax + aw / 2, ay + ah, bx + bw / 2, by
        mid = (y1 + y2) / 2
        d = f"M{x1:.1f} {y1:.1f}C{x1:.1f} {mid:.1f} {x2:.1f} {mid:.1f} {x2:.1f} {y2:.1f}"
    elif arow == brow:
        right = bx > ax
        x1 = ax + aw if right else ax
        x2 = bx if right else bx + bw
        y = ay + ah / 2
        d = f"M{x1:.1f} {y:.1f}L{x2:.1f} {y:.1f}"
    else:
        at_right = arow[1] % 2 == 0  # into the next group: it ends on the left, see above
        x = ax + aw if at_right else ax
        y1, y2 = ay + ah / 2, by + bh / 2
        out_x = x + TURN * (1 if at_right else -1)
        d = (f"M{x:.1f} {y1:.1f}C{out_x:.1f} {y1:.1f} {out_x:.1f} {y1:.1f} {out_x:.1f} "
             f"{y1 + 12:.1f}L{out_x:.1f} {y2 - 12:.1f}C{out_x:.1f} {y2:.1f} {out_x:.1f} "
             f"{y2:.1f} {x:.1f} {y2:.1f}")
    return [f'<path class="link" d="{d}"/>', f'<path class="lit {cls}" pathLength="1" d="{d}"/>']


def legend(ink, y):
    out, x = [], MARGIN + 4
    items = [("you", "you decide"), ("model", "a model: reads, writes text"),
             ("bots", "a bot or script: posts, no model")]
    for kind, text in items:
        if kind == "you":
            out.append(f'<use class="who-you" href="#you" x="{x}" y="{y - 12}" width="15" '
                       'height="15"/>')
            x += 19
        elif kind == "model":
            out.append(f'<rect class="model" x="{x}" y="{y - 12}" width="22" height="15" rx="4"/>')
            x += 27
        else:
            for m in ("lantern", "beacon", "kettle"):
                out.append(f'<use href="#{m}" x="{x}" y="{y - 13}" width="16" height="16"/>')
                x += 17
            x += 2
        out.append(f'<path class="c" d="{ink.path(text, x, y, 13, 400)}"/>')
        x += ink.width(text, 13, 400) + 18
    if x > W - MARGIN:
        raise SystemExit(f"the legend is {x:.0f} wide, room is {W - MARGIN}")
    return out


def css(theme, name, count):
    c = THEMES[theme]
    accent = c["route"]
    cycle = count * STEP + REST
    rules = [
        f".bg{{fill:{c['canvas']};stroke:{c['wire']}}}",
        f".band{{fill:{accent}}}",
        f".when{{fill:none;stroke:{accent};stroke-width:1.5}}.w{{fill:{accent}}}",
        f".block{{fill:{c['panel']};stroke:{c['wire']};stroke-width:1.5}}",
        f".frame{{fill:none;stroke:{c['wire']};stroke-width:1.5;stroke-dasharray:6 5}}",
        f".model{{fill:{c['panel']};stroke:{c['off']};stroke-width:1.5;stroke-dasharray:4 3}}",
        f".you{{fill:{c['route_soft']};stroke:{c['route']};stroke-width:1.5}}",
        f".t{{fill:{c['ink']}}}.s{{fill:{c['ink3']}}}.c{{fill:{c['ink3']}}}",
        f".who-you{{color:{c['route']}}}",
        f".link{{fill:none;stroke:{c['link']};stroke-width:2;stroke-linecap:round}}",
        f".lit{{fill:none;stroke:{accent};stroke-width:2.5;stroke-linecap:round;"
        "stroke-dasharray:1;stroke-dashoffset:0;opacity:0}",
        f".lit-block{{fill:none;stroke:{accent};stroke-width:2;opacity:0}}",
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


def data_uri(path: Path, kind: str) -> str:
    return f"data:{kind};base64," + base64.b64encode(path.read_bytes()).decode()


def tile(name: str, theme: str, x: float, y: float) -> list[str]:
    """The picture's mark in its title: the app icon of the bot it is about, or for the
    watcher the three clients it reads."""
    size = 36
    if name in ("lantern", "beacon"):
        icon = data_uri(ROOT / f"docs/images/apps/{name}.svg", "image/svg+xml")
        return [f'<clipPath id="tile"><rect x="{x}" y="{y}" width="{size}" height="{size}" '
                'rx="9"/></clipPath>',
                f'<image href="{icon}" x="{x}" y="{y}" width="{size}" height="{size}" '
                'clip-path="url(#tile)"/>']
    out = [f'<rect class="block" x="{x}" y="{y}" width="{3 * 24 + 12}" height="{size}" rx="9"/>']
    for n, client in enumerate(("claude", "codex", "cursor")):
        file = f"{client}-dark" if theme == "dark" and client != "claude" else client
        logo = data_uri(ROOT / f"docs/images/clients/{file}.png", "image/png")
        out.append(f'<image href="{logo}" x="{x + 8 + n * 24}" y="{y + 9}" width="18" '
                   'height="18"/>')
    return out


def draw(ink: Ink, name: str, theme: str) -> str:
    pic = PICTURES[name]
    slots, frames, height = layout(pic)
    out = [f'<rect class="bg" x="0.75" y="0.75" width="{W - 1.5}" height="{height - 1.5:.1f}" '
           'rx="12"/>']
    out += tile(pic["tile"], theme, MARGIN, 12)
    tx = MARGIN + (36 if pic["tile"] != "clients" else 84) + 12
    out.append(f'<path class="t" d="{ink.path(pic["name"], tx, 37, 21, 600)}"/>')
    px = tx + ink.width(pic["name"], 21, 600) + 12
    pw = ink.width(pic["when"], 13, 600) + 20
    out.append(f'<rect class="when" x="{px:.1f}" y="19" width="{pw:.1f}" height="22" rx="11"/>')
    out.append(f'<path class="w" d="{ink.path(pic["when"], px + 10, 34.5, 13, 600)}"/>')
    out += legend(ink, 68)
    for group, top, bottom in frames:
        out.append(f'<rect class="frame" x="{MARGIN + 6}" y="{top:.1f}" '
                   f'width="{W - 2 * MARGIN - 12}" height="{bottom - top:.1f}" rx="12"/>')
        label, note = group["label"], group.get("note", "")
        out.append(f'<path class="t" d="{ink.path(label, MARGIN + 18, top + 21, 14, 600)}"/>')
        nx = MARGIN + 18 + ink.width(label, 14, 600) + 10
        out.append(f'<path class="c" d="{ink.path(note, nx, top + 21, 13, 400)}"/>')
    steps = [st for g in pic["groups"] for st in g["steps"]]
    chained = [g.get("chain", True) for g in pic["groups"] for _ in g["steps"]]
    for n in range(1, len(slots)):
        if chained[n]:
            out += joint(slots[n - 1], slots[n], f"q{n}")
    for n, (step, box) in enumerate(zip(steps, slots, strict=True)):
        x, y, w, h = box[:4]
        if isinstance(step, list):
            half = (h - 6) / 2
            out += card(ink, step[0], (x, y, w, half), f"q{n}")
            out += card(ink, step[1], (x, y + half + 6, w, half), f"q{n}")
        else:
            out += card(ink, step, (x, y, w, h), f"q{n}")
    flat = [s for st in steps for s in (st if isinstance(st, list) else [st])]
    words = "; ".join(f"{s[3]}: {' '.join(s[4])}" for s in flat)
    head = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{height:.0f}" '
        f'viewBox="0 0 {W} {height:.0f}" role="img" aria-labelledby="title desc">\n'
        f'<title id="title">{pic["name"]}, {pic["when"]}</title>\n'
        f'<desc id="desc">The steps in order, with who does each. {words}.</desc>\n'
        "<!-- Made by scripts/make_picture.py. Text: Inter outlines, SIL OFL 1.1. Client logos:\n"
        "     Kitden's own copies, as Kitden shows them. -->\n"
        f"<style>\n{css(theme, name, len(slots))}\n</style>\n"
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
