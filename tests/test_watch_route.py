import copy
import json
from datetime import date
from pathlib import Path

import pytest

from watch_route import (
    TEXT_MAX,
    TITLE_MAX,
    WORD_HITS_MAX,
    BadFindings,
    check,
    labels,
    route,
    word_hits,
)

URL = "https://example.com/changelog"
PID = "claude-code-changelog#2.1.320"
JUDGED = [PID]
LIST = (
    "## Claude Code\n\n| What | Kind | Files | Seen in | Systems | Source |\n"
    "|---|---|---|---|---|---|\n"
    "| the `skillOverrides` key | setting | `src/kitden/skills.py` | 2.1 | all | https://x |\n"
)


def piece(pid=PID, client="claude-code", text="nothing", url=URL):
    source, key = pid.split("#")
    return {"id": pid, "client": client, "kind": "release", "version": key, "url": url,
            "text": text, "source": source, "key": key, "hash": "h-" + key}


def make_inp(pieces=None):
    return {"pieces": pieces or [piece()], "list": LIST,
            "files": {"src/kitden/skills.py": {"text": "x", "same_in_release": True}},
            "release": "v1", "known_titles": [], "state": {}}


INP = make_inp()


def finding(**kw):
    base = {"piece": PID, "client": "claude-code", "title": "t", "changed": "c",
            "version": "2.1.320", "url": URL, "row": "the `skillOverrides` key",
            "files": ["src/kitden/skills.py"], "effect": "minor", "sure": True,
            "user_gets": "u", "systems": "not checked", "why": "w"}
    return {**base, **kw}


def base_state(**kw):
    return {"sources": {"claude-code-changelog": {}}, "fails": {}, "kept": [],
            "urgent": {"week": "", "count": 0}, **kw}


def with_text(text):
    return {"judged": JUDGED, "findings": [finding(why=text)]}


def ok(**kw):
    return {"judged": JUDGED, "findings": [finding(**kw)]}


def inp_piece_text(text, client="claude-code"):
    return make_inp([piece(text=text, client=client)])


def judged_ids(n):
    return [f"claude-code-changelog#v{i}" for i in range(n)]


def inp_pieces_with_word(n):
    return make_inp([piece(pid, text="skillOverrides") for pid in judged_ids(n)])


# check

def test_fixture_is_accepted_and_matches_schema():
    data = json.loads(Path("tests/fixtures/watch_findings_ok.json").read_text())
    inp = make_inp([piece(url=URL)])
    assert check(data, inp) == data["findings"]
    try:
        import jsonschema
    except ImportError:
        return
    jsonschema.validate(data, json.loads(Path("schemas/watch-findings.schema.json").read_text()))


@pytest.mark.parametrize("bad", [
    {"judged": JUDGED},
    {"judged": JUDGED, "findings": [], "extra": 1},
    {"judged": "x", "findings": []},
    {"judged": [1], "findings": []},
    {"judged": JUDGED, "findings": {}},
    {"judged": JUDGED, "findings": ["x"]},
])
def test_wrong_top_level_is_refused(bad):
    with pytest.raises(BadFindings):
        check(bad, INP)


def test_not_a_dict_is_refused():
    with pytest.raises(BadFindings):
        check([], INP)


@pytest.mark.parametrize("change", [
    {"extra": 1},
    {"sure": "yes"},
    {"files": "a"},
    {"files": [1]},
    {"title": 3},
    {"effect": "bad"},
])
def test_wrong_keys_or_types_are_refused(change):
    data = ok()
    data["findings"][0].update(change)
    with pytest.raises(BadFindings):
        check(data, INP)


def test_missing_key_is_refused():
    data = ok()
    del data["findings"][0]["why"]
    with pytest.raises(BadFindings):
        check(data, INP)


def test_piece_not_in_input_is_refused():
    with pytest.raises(BadFindings):
        check({"judged": ["a#1"], "findings": [finding(piece="a#1")]}, INP)


def test_piece_not_judged_is_refused():
    with pytest.raises(BadFindings):
        check({"judged": [], "findings": [finding()]}, INP)


def test_judged_not_in_input_is_refused():
    with pytest.raises(BadFindings):
        check({"judged": ["a#1"], "findings": []}, INP)


def test_url_of_another_address_is_refused():
    with pytest.raises(BadFindings):
        check(ok(url="https://evil.example"), INP)


def test_client_of_another_piece_is_refused():
    with pytest.raises(BadFindings):
        check(ok(client="cursor"), INP)


def test_file_not_in_input_is_refused():
    with pytest.raises(BadFindings):
        check(ok(files=["nope.py"]), INP)


def test_secret_like_text_is_refused():
    with pytest.raises(BadFindings):
        check(with_text("ghp_" + "a" * 20), INP)


def test_long_text_is_cut_and_mentions_are_quiet():
    out = check(ok(title="@bob " + "t" * 200, why="w" * 700), INP)[0]
    assert len(out["title"]) == TITLE_MAX and len(out["why"]) == TEXT_MAX
    assert out["title"].startswith("@⁠bob")


# route

NOW = date(2026, 11, 11)  # Wednesday, ISO week 2026-W46


def test_rule1_new_week_resets_urgent_count():
    state = base_state(urgent={"week": "2026-W45", "count": 2})
    plan = route([finding(effect="breaks")], state, JUDGED, INP, NOW)
    assert len(plan.urgent) == 1 and plan.state["urgent"] == {"week": "2026-W46", "count": 1}


def test_rule2_known_or_kept_title_is_dropped():
    inp = {**INP, "known_titles": ["t"]}
    assert route([finding()], base_state(), JUDGED, inp, NOW).state["kept"] == []
    state = base_state(kept=[finding(title="t")])
    assert len(route([finding()], state, JUDGED, INP, NOW).state["kept"]) == 1


def test_rule2_same_title_twice_in_one_run_is_kept_once():
    plan = route([finding(), finding()], base_state(), JUDGED, INP, NOW)
    assert len(plan.state["kept"]) == 1


def test_rule3_sure_break_is_urgent():
    plan = route([finding(effect="wrong-data")], base_state(), JUDGED, INP, NOW)
    assert len(plan.urgent) == 1 and plan.state["kept"] == []
    assert plan.state["urgent"]["count"] == 1


def test_third_urgent_in_a_week_goes_to_the_summary():
    state = base_state(urgent={"week": "2026-W46", "count": 2})
    plan = route([finding(effect="breaks", sure=True)], state, JUDGED, INP, NOW)
    assert plan.urgent == [] and plan.state["kept"][0]["overflow"] is True


def test_unsure_break_is_not_urgent():
    plan = route([finding(effect="breaks", sure=False)], base_state(), JUDGED, INP, NOW)
    assert plan.urgent == [] and len(plan.state["kept"]) == 1


def test_rule4_other_effects_are_kept():
    plan = route([finding(effect="gap")], base_state(), JUDGED, INP, NOW)
    assert plan.urgent == [] and "overflow" not in plan.state["kept"][0]


def test_rule5_judged_piece_is_marked_seen():
    plan = route([], base_state(), JUDGED, INP, NOW)
    assert plan.state["sources"]["claude-code-changelog"]["2.1.320"] == "h-2.1.320"


def test_unjudged_piece_is_not_marked_seen():
    plan = route([], base_state(), [], INP, NOW)
    assert "2.1.320" not in plan.state["sources"]["claude-code-changelog"]


def test_rule6_monday_empties_kept_into_one_summary():
    state = base_state(kept=[finding(effect="minor"), finding(effect="gap", title="g")])
    plan = route([], state, [], INP, date(2026, 11, 16))
    assert [f["effect"] for f in plan.summary] == ["gap", "minor"] and plan.state["kept"] == []


def test_summary_order_and_kept_items_without_piece():
    unreadable = {k: v for k, v in finding(title="u").items() if k != "piece"}
    kept = [
        finding(effect="minor", title="a"), unreadable, finding(effect="gap", title="b"),
        finding(effect="wrong-data", title="c"), finding(effect="breaks", title="d"),
        finding(effect="breaks", sure=False, title="e"),
        finding(effect="minor", title="f", overflow=True),
    ]
    plan = route([], base_state(kept=kept), [], INP, date(2026, 11, 16))
    assert [f["title"] for f in plan.summary] == ["f", "e", "d", "c", "b", "a", "u"]


def test_no_summary_on_other_days_or_when_nothing_kept():
    state = base_state(kept=[finding()])
    assert route([], state, [], INP, NOW).summary is None
    assert route([], base_state(), [], INP, date(2026, 11, 16)).summary is None


def test_route_does_not_change_its_inputs():
    state = base_state(kept=[finding(title="k")])
    args = ([finding(effect="breaks")], state, list(JUDGED), copy.deepcopy(INP))
    before = copy.deepcopy(args)
    route(*args, date(2026, 11, 16))
    assert args == before


# labels and word hits

def test_labels_for_an_unsure_gap():
    assert labels(finding(effect="gap", sure=False, client="cursor")) == [
        "client-change", "cursor", "kitden-gap", "unsure"]


def test_labels_for_a_sure_break():
    assert labels(finding(effect="breaks")) == ["client-change", "claude-code", "breaks"]


def test_word_the_model_passed_over_becomes_an_unsure_item():
    hits = word_hits([], JUDGED, inp_piece_text("Renamed skillOverrides to skills.overrides"))
    assert len(hits) == 1 and hits[0]["sure"] is False and hits[0]["effect"] == "minor"
    assert hits[0]["row"] == "the `skillOverrides` key"
    assert hits[0]["title"] == "Mentions `skillOverrides`" and hits[0]["files"] == [
        "src/kitden/skills.py"]


def test_no_word_hit_when_the_model_named_the_row():
    inp = inp_piece_text("Renamed skillOverrides")
    assert word_hits([finding(row="the `skillOverrides` key")], JUDGED, inp) == []


def test_no_word_hit_for_an_unjudged_piece_or_another_client():
    inp = inp_piece_text("Renamed skillOverrides")
    assert word_hits([], [], inp) == []
    assert word_hits([], JUDGED, inp_piece_text("Renamed skillOverrides", client="cursor")) == []


def test_word_hits_stop_at_the_cap():
    assert len(word_hits([], judged_ids(9), inp_pieces_with_word(9))) == WORD_HITS_MAX == 5
