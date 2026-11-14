"""One look for everything the bots post: a row of badges, a box that says what to do, and
the small print. The colors are Kitden's own (docs/design.md in the Kitden repo).

A badge is a picture drawn by shields.io, in a light and a dark form; GitHub shows the one
that fits the reader's theme. When the picture cannot be loaded the reader sees its text."""

import base64
import html
import re
from urllib.parse import quote

SHIELDS = "https://img.shields.io/badge/"
# The name part of a badge and its icon, by the reader's theme: (fill, ink).
THEMES = {"light": ("E4E7EC", "#161A21"), "dark": ("282D36", "#F2F3F5")}
ORANGE = "B34B2D"  # a version
GREEN = "177A42"  # passed, sure
RED = "B23434"  # failed, high risk
AMBER = "97590A"  # needs a look, medium risk
GREY = "626977"  # a plain fact, low risk, not sure
RISK = {"high": (RED, 3), "medium": (AMBER, 2), "low": (GREY, 1)}
BOXES = ("NOTE", "IMPORTANT", "WARNING")  # nothing needed, you must act, something is wrong
UNSAFE = re.compile(r"[^\w .:+-]", re.ASCII)
TEXT_MAX = 40


def _icon(body: str) -> str:
    svg = f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 14 14">{body}</svg>'
    return "data:image/svg+xml;base64," + base64.b64encode(svg.encode()).decode()


def _line(ink: str) -> str:
    return (f'fill="none" stroke="{ink}" stroke-width="1.8" stroke-linecap="round" '
            'stroke-linejoin="round"')


def _bars(filled: int, ink: str) -> str:
    bars = ((1, 9, 4), (5.5, 5.5, 7.5), (10, 2, 11))
    return "".join(
        f'<rect x="{x}" y="{y}" width="3" height="{h}" rx=".6" fill="{ink}" '
        f'opacity="{"1" if n < filled else ".3"}"/>' for n, (x, y, h) in enumerate(bars))


ICONS = {
    "bars-1": lambda ink: _bars(1, ink),
    "bars-2": lambda ink: _bars(2, ink),
    "bars-3": lambda ink: _bars(3, ink),
    "check": lambda ink: f'<path d="M2.5 7.5l3 3 6-6.5" {_line(ink)}/>',
    "cross": lambda ink: f'<path d="M3.5 3.5l7 7M10.5 3.5l-7 7" {_line(ink)}/>',
    "ask": lambda ink: (f'<path d="M4.3 4.6a2.8 2.8 0 1 1 4.2 2.4c-.9.5-1.5 1-1.5 2" '
                        f'{_line(ink)}/><circle cx="7" cy="12" r="1.1" fill="{ink}"/>'),
}


def plain(text: str) -> str:
    """Text a badge can show: letters, digits and a few signs, cut short. A badge's text may
    come from a client's notes, so nothing in it can add markup or reach another address."""
    return " ".join(UNSAFE.sub("", str(text)).split())[:TEXT_MAX] or "?"


def _part(text: str) -> str:
    # shields.io reads "-" and "_" as separators: double them, then spaces become "_".
    return quote(text.replace("-", "--").replace("_", "__").replace(" ", "_"), safe="")


def _url(label: str, message: str, color: str, icon: str, theme: str) -> str:
    fill, ink = THEMES[theme]
    url = f"{SHIELDS}{_part(label)}-{_part(message)}-{color}?labelColor={fill}"
    if icon:
        url += "&logo=" + quote(_icon(ICONS[icon](ink)), safe="")
    return url


def badge(label: str, message: str, color: str = GREY, icon: str = "") -> str:
    """One badge: the name on a quiet fill, the value on `color`."""
    label, message = plain(label), plain(message)
    light, dark = (_url(label, message, color, icon, theme) for theme in ("light", "dark"))
    alt = html.escape(f"{label}: {message}", quote=True)
    return (f'<picture><source media="(prefers-color-scheme: dark)" srcset="{dark}">'
            f'<img src="{light}" alt="{alt}"></picture>')


def version(name: str, number: str) -> str:
    """A version: the name, and the number on orange."""
    return badge(name, number, ORANGE)


def risk(level: str) -> str:
    """The risk for a Kitden user: three bars, one to three filled."""
    color, filled = RISK.get(level, RISK["low"])
    return badge("risk", level if level in RISK else "low", color, f"bars-{filled}")


def sure(yes: bool) -> str:
    return badge("sure", "yes", GREEN, "check") if yes else badge("sure", "no", GREY, "ask")


def ok(label: str, message: str = "pass") -> str:
    return badge(label, message, GREEN, "check")


def bad(label: str, message: str) -> str:
    return badge(label, message, RED, "cross")


def warn(label: str, message: str) -> str:
    return badge(label, message, AMBER, "ask")


def info(label: str, message: str) -> str:
    return badge(label, message, GREY)


def row(*badges: str) -> str:
    """The first line of a bot's text: its badges, side by side."""
    return " ".join(b for b in badges if b)


def box(kind: str, text: str) -> str:
    """GitHub's coloured box. IMPORTANT: the reader must do something. NOTE: nothing is
    needed. WARNING: something is wrong."""
    if kind not in BOXES:
        raise ValueError(f"no such box: {kind}")
    return f"> [!{kind}]\n" + "\n".join(f"> {line}".rstrip() for line in text.splitlines())


def small(*parts: str) -> str:
    """The small print at the end: sources and how it works."""
    return "<sub>" + " · ".join(p for p in parts if p) + "</sub>"
