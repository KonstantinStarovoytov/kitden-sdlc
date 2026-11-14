import base64
import re
import sys
from pathlib import Path
from urllib.parse import unquote

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import bot_style as style


def urls(badge: str) -> tuple[str, str]:
    """The light and the dark address of a badge."""
    dark = re.search(r'srcset="([^"]+)"', badge).group(1)
    light = re.search(r'<img src="([^"]+)"', badge).group(1)
    return light, dark


def test_a_badge_has_a_light_and_a_dark_picture_and_its_text():
    badge = style.version("Claude Code", "2.1.325")
    light, dark = urls(badge)
    assert light == "https://img.shields.io/badge/Claude_Code-2.1.325-B34B2D?labelColor=E4E7EC"
    assert dark == "https://img.shields.io/badge/Claude_Code-2.1.325-B34B2D?labelColor=282D36"
    assert '<source media="(prefers-color-scheme: dark)"' in badge
    assert 'alt="Claude Code: 2.1.325"' in badge  # what the reader sees without the picture


def test_risk_is_three_bars_with_one_to_three_filled():
    for level, color, filled in (("high", "B23434", 3), ("medium", "97590A", 2),
                                 ("low", "626977", 1)):
        badge = style.risk(level)
        light, dark = urls(badge)
        assert f"/risk-{level}-{color}?" in light and f'alt="risk: {level}"' in badge
        for url, ink in ((light, "#161A21"), (dark, "#F2F3F5")):
            icon = unquote(url.split("&logo=")[1]).removeprefix("data:image/svg+xml;base64,")
            svg = base64.b64decode(icon).decode()
            assert svg.count(f'fill="{ink}" opacity="1"') == filled and svg.count("<rect") == 3
    assert 'alt="risk: low"' in style.risk("no such level")


def test_sure_is_a_check_or_a_question_mark():
    yes, no = style.sure(True), style.sure(False)
    assert 'alt="sure: yes"' in yes and "/sure-yes-177A42?" in urls(yes)[0]
    assert 'alt="sure: no"' in no and "/sure-no-626977?" in urls(no)[0]
    assert urls(yes)[0].split("&logo=")[1] != urls(no)[0].split("&logo=")[1]


def test_a_badge_shows_plain_text_only():
    text = 'x" onerror="y <b>@bob</b>\n## Head [a](http://evil) ' + "9" * 80
    badge = style.info(text, text)
    assert badge.count("<picture>") == 1 and badge.count('"') == 8  # no attribute of its own
    assert "@" not in badge and "\n" not in badge
    shown = style.plain(text)
    assert shown == "x onerrory bbobb Head ahttp:evil 9999999"
    assert len(shown) == 40 and style.plain("") == "?"
    light, _ = urls(style.info("a-b_c d", "1-2"))
    assert "/a--b__c_d-1--2-626977?" in light  # shields.io reads - and _ as separators


def test_the_marks_of_a_check():
    assert "/checks-pass-177A42?" in urls(style.ok("checks"))[0]
    assert "/checks-2_to_fix-B23434?" in urls(style.bad("checks", "2 to fix"))[0]
    assert "/Luna-no_answer-97590A?" in urls(style.warn("Luna", "no answer"))[0]
    assert "&logo=" not in urls(style.info("commit", "abc1234"))[0]


def test_a_row_a_box_and_the_small_print():
    assert style.row("a", "", "b") == "a b"
    assert style.box("IMPORTANT", "Do this.\n\nThen that.") == (
        "> [!IMPORTANT]\n> Do this.\n>\n> Then that.")
    with pytest.raises(ValueError, match="no such box"):
        style.box("CAUTION", "x")
    assert style.small("a", "", "[b](c)") == "<sub>a · [b](c)</sub>"


def test_a_mark_is_one_part_and_a_wide_name_keeps_its_column():
    mark = style.mark("ok", style.GREEN, "check")
    assert mark.startswith('<img src="https://img.shields.io/badge/ok-177A42?logo=')
    assert mark.endswith('alt="ok">') and "<picture>" not in mark  # the same in both themes
    assert style.mark("not measured") == (
        '<img src="https://img.shields.io/badge/not_measured-626977" alt="not measured">')
    assert style.wide("Risk", 2) == "&nbsp;&nbsp;Risk&nbsp;&nbsp;"
