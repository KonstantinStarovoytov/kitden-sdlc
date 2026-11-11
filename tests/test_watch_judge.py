import copy
import json
import sys
from pathlib import Path

import watch_judge
from watch_judge import (
    FILE_CHARS,
    PART_CHARS,
    Assessed,
    Change,
    judge,
    named,
    screen_messages,
)
from watch_list import row_ids, short_list
from watch_route import EFFECTS, KEYS, TOP_KEYS, check

PIECE_URL = "https://example.com/changelog"
PID = "claude-code-changelog#2.1.320"
FILE = "src/kitden/clients/claude_code.py"
LIST_TEXT = (
    "## Claude Code\n\n| What | Kind | Files | Seen in | Systems | Source |\n"
    "|---|---|---|---|---|---|\n"
    f"| the `skillOverrides` key | setting | `{FILE}` | 2.1 | all | https://x |\n"
    "\n## Codex\n\n| What | Kind | Files | Seen in | Systems | Source |\n"
    "|---|---|---|---|---|---|\n"
    "| the `codexOnly` key | setting | `src/kitden/clients/codex.py` | 1 | all | https://y |\n"
)


def piece(pid=PID, text="Changed skillOverrides."):
    source, key = pid.split("#")
    return {"id": pid, "client": "claude-code", "kind": "release", "version": key,
            "url": PIECE_URL, "text": text, "source": source, "key": key, "hash": "h-" + key}


def inp_with_pieces(n):
    return {"pieces": [piece(f"claude-code-changelog#2.1.{i}") for i in range(n)],
            "list": LIST_TEXT,
            "files": {FILE: {"text": "y" * (FILE_CHARS + 10), "same_in_release": True}},
            "release": "v1", "known_titles": ["old"], "state": {}}


INP = inp_with_pieces(1)
INP["pieces"] = [piece()]
PIECE_A = piece()
PIECE_B = piece("claude-code-changelog#2.1.321", "Other text.")
SCREEN_ROW = [{"row": "the `skillOverrides` key", "title": "t", "changed": "c"}]
ASSESS_BREAK = {"effect": "breaks", "sure": True, "user_gets": "u",
                "systems": "not checked", "why": "w", "title": "t"}


class Fake:
    def __init__(self, screen=(), assess=None, refute=False):
        self.screen_out, self.assess_out, self.refute_out = list(screen), assess, refute
        self.screen_calls = self.assess_calls = self.refute_calls = 0
        self.seen_files = None
        self.seen_titles = []

    def screen(self, piece, list_text, known_titles):
        self.screen_calls += 1
        self.seen_titles.append(list(known_titles))
        return copy.deepcopy(self.screen_out)

    def assess(self, change, row, files):
        self.assess_calls += 1
        self.seen_files = files
        return dict(self.assess_out)

    def refute(self, finding, row, files):
        self.refute_calls += 1
        return self.refute_out


FAKE_BREAK = Fake(screen=SCREEN_ROW, assess=ASSESS_BREAK)


def test_matched_change_becomes_a_finding_with_code_filled_fields():
    model = Fake(screen=[{"row": "the `skillOverrides` key", "title": "t", "changed": "c"}],
                 assess={"effect": "breaks", "sure": True, "user_gets": "u",
                         "systems": "not checked", "why": "w", "title": "t"})
    out = judge(INP, model)
    f = out["findings"][0]
    assert (f["piece"], f["client"], f["version"], f["url"]) == (
        "claude-code-changelog#2.1.320", "claude-code", "2.1.320", PIECE_URL)
    assert f["files"] == ["src/kitden/clients/claude_code.py"]
    assert out["judged"] == ["claude-code-changelog#2.1.320"]


def test_assess_gets_the_row_files_cut():
    model = Fake(screen=SCREEN_ROW, assess=ASSESS_BREAK)
    judge(INP, model)
    assert model.seen_files == {FILE: "y" * FILE_CHARS}


def test_none_makes_no_finding_but_the_piece_is_judged():
    out = judge(INP, Fake(screen=[{"row": "none"}]))
    assert out["findings"] == [] and len(out["judged"]) == 1


def test_unknown_row_name_is_dropped():
    out = judge(INP, Fake(screen=[{"row": "a row that is not there"}]))
    assert out["findings"] == []


def test_row_of_another_client_is_dropped():
    model = Fake(screen=[{"row": "the `codexOnly` key", "title": "t", "changed": "c"}],
                 assess=ASSESS_BREAK)
    out = judge(INP, model)
    assert out["findings"] == [] and model.assess_calls == 0


def test_gap_needs_no_second_call():
    model = Fake(screen=[{"row": "gap", "title": "t", "changed": "c", "user_gets": "u",
                          "sure": True, "why": "w"}])
    out = judge(INP, model)
    assert out["findings"][0]["effect"] == "gap" and model.assess_calls == 0
    assert check(out, INP)


def test_call_limit_leaves_pieces_unjudged():
    out = judge(inp_with_pieces(3), Fake(screen=[{"row": "none"}]), max_calls=2)
    assert len(out["judged"]) == 2


def test_piece_with_unfinished_calls_is_not_judged():
    model = Fake(screen=SCREEN_ROW, assess=ASSESS_BREAK, refute=False)
    out = judge(INP, model, max_calls=2)
    assert out == {"judged": [], "findings": [], "failed": []}
    assert (model.screen_calls, model.assess_calls, model.refute_calls) == (1, 1, 0)


def test_output_passes_check():
    out = judge(INP, FAKE_BREAK)
    assert check(out, INP)


def test_refuted_break_stays_but_is_not_sure():
    out = judge(INP, Fake(screen=SCREEN_ROW, assess=ASSESS_BREAK, refute=True))
    f = out["findings"][0]
    assert f["effect"] == "breaks" and f["sure"] is False
    assert f["why"].endswith("A second look disagreed.")


def test_break_that_holds_stays_sure():
    model = Fake(screen=SCREEN_ROW, assess=ASSESS_BREAK, refute=False)
    f = judge(INP, model)["findings"][0]
    assert f["sure"] is True and f["why"] == "w" and model.refute_calls == 1


def test_minor_and_unsure_findings_get_no_second_look():
    model = Fake(screen=SCREEN_ROW, assess={**ASSESS_BREAK, "effect": "minor"})
    judge(INP, model)
    assert model.refute_calls == 0
    model = Fake(screen=SCREEN_ROW, assess={**ASSESS_BREAK, "sure": False})
    judge(INP, model)
    assert model.refute_calls == 0


def test_screen_requests_share_their_start():
    a = screen_messages(PIECE_A, LIST_TEXT, [])
    b = screen_messages(PIECE_B, LIST_TEXT, ["x"])
    assert a[0] == b[0] and short_list(LIST_TEXT) in a[0]["content"]
    assert PIECE_A["text"] not in a[0]["content"] and PIECE_A["text"] in a[1]["content"]


class Breaks(Fake):
    def screen(self, piece, list_text, known_titles):
        if self.screen_calls == 1:
            self.screen_calls += 1
            raise TimeoutError("request data")
        return super().screen(piece, list_text, known_titles)


GAP = [{"row": "gap", "title": "t", "changed": "c", "user_gets": "u", "sure": True, "why": "w"}]


def test_failed_piece_is_skipped_and_the_next_pieces_are_judged(capsys):
    model = Breaks(screen=GAP)
    out = judge(inp_with_pieces(3), model)
    assert out["judged"] == ["claude-code-changelog#2.1.0", "claude-code-changelog#2.1.2"]
    assert out["failed"] == ["claude-code-changelog#2.1.1"]
    assert len(out["findings"]) == 2 and model.screen_calls == 3
    err = capsys.readouterr().err
    assert "claude-code-changelog#2.1.1" in err and "TimeoutError" in err
    assert "request data" not in err
    assert check(out, inp_with_pieces(3))


class BadAssess(Fake):
    def assess(self, change, row, files):
        raise ValueError("x")


def test_failed_assess_drops_the_piece_and_its_findings():
    out = judge(INP, BadAssess(screen=[*GAP, *SCREEN_ROW]))
    assert out == {"judged": [], "findings": [], "failed": [PID]}


def test_three_failed_pieces_in_a_row_stop_the_run():
    model = BadAssess(screen=SCREEN_ROW)
    out = judge(inp_with_pieces(5), model)
    assert len(out["failed"]) == 3 and out["judged"] == [] and model.screen_calls == 3


def test_later_screens_see_the_titles_found_earlier_in_the_run():
    model = Fake(screen=GAP)
    judge(inp_with_pieces(2), model)
    assert model.seen_titles == [["old"], ["old", "t"]]


def test_screen_first_message_stays_the_same_with_new_titles():
    a = screen_messages(PIECE_A, LIST_TEXT, ["old"])
    b = screen_messages(PIECE_A, LIST_TEXT, ["old", "t"])
    assert a[0] == b[0] and '"t"' in b[1]["content"]


def test_deadline_stops_the_run_like_the_call_limit():
    ticks = iter([0, 0] + [1000] * 5)
    out = judge(inp_with_pieces(3), Fake(screen=GAP), deadline=600, clock=lambda: next(ticks))
    assert len(out["judged"]) == 1 and out["failed"] == []


def test_cli_writes_findings_and_says_so_when_nothing_was_judged(tmp_path, monkeypatch, capsys):
    (tmp_path / "input.json").write_text(json.dumps(inp_with_pieces(2)))
    monkeypatch.setenv("WATCH_MODEL", "m")
    monkeypatch.setattr(watch_judge, "OpenAIModel", lambda name: BadAssess(screen=SCREEN_ROW))
    monkeypatch.setattr(sys, "argv", ["watch_judge.py", "--input", str(tmp_path / "input.json"),
                                      "--out", str(tmp_path / "findings.json")])
    watch_judge.main()
    out = json.loads((tmp_path / "findings.json").read_text())
    assert out["judged"] == [] and len(out["failed"]) == 2
    assert "No piece was judged" in capsys.readouterr().err


def test_screen_tells_the_kind_only_in_the_last_message():
    doc = {**PIECE_A, "kind": "doc", "version": ""}
    a = screen_messages(PIECE_A, LIST_TEXT, [])
    b = screen_messages(doc, LIST_TEXT, [])
    assert a[0] == b[0]
    assert json.loads(a[-1]["content"])["piece"]["kind"] == "release"
    assert json.loads(b[-1]["content"])["piece"]["kind"] == "doc"


def test_schema_keys_match_check_and_the_judge_models():
    schema = json.loads(Path("schemas/watch-findings.schema.json").read_text())
    item = schema["properties"]["findings"]["items"]
    assert set(schema["required"]) == set(schema["properties"]) == TOP_KEYS
    assert set(item["required"]) == set(item["properties"]) == KEYS
    assert item["properties"]["effect"]["enum"] == list(EFFECTS)
    for model in (Change, Assessed):
        assert set(model.model_fields) <= KEYS


def test_a_change_the_code_shows_as_none_makes_no_finding():
    model = Fake(screen=SCREEN_ROW, assess={**ASSESS_BREAK, "effect": "none"})
    out = judge(INP, model)
    assert out["findings"] == [] and out["judged"] == [PID] and model.refute_calls == 0


def _change(row):
    return Change(row=row, title="t", changed="c", user_gets="", sure=False, why="")


def test_the_model_names_a_row_by_its_id():
    ids = row_ids(LIST_TEXT)
    assert ids == {"CC-01": ("claude-code", "the `skillOverrides` key"),
                   "CX-01": ("codex", "the `codexOnly` key")}
    got = named([_change("CC-01"), _change(" CC-01 "), _change("gap")], "claude-code", LIST_TEXT)
    assert [c["row"] for c in got] == ["the `skillOverrides` key"] * 2 + ["gap"]


def test_an_id_of_another_client_or_no_row_is_none():
    got = named([_change("CX-01"), _change("CC-99"), _change("the key")], "claude-code",
                LIST_TEXT)
    assert [c["row"] for c in got] == ["none"] * 3


def test_the_model_reads_a_short_list_with_ids_and_no_file_names():
    text = short_list(LIST_TEXT)
    assert "CC-01 | the `skillOverrides` key | setting | seen in: 2.1" in text
    assert "## Codex (client `codex`)" in text and FILE not in text


class Parts(Fake):
    """Remembers the text of each screen call; the row is named only in the last part."""

    def __init__(self, **kw):
        super().__init__(**kw)
        self.texts = []

    def screen(self, piece, list_text, known_titles):
        self.texts.append(piece["text"])
        out = super().screen(piece, list_text, known_titles)
        return out if "LAST" in piece["text"] else []


def long_inp():
    lines = [f"- line {n} " + "x" * 90 + "\n" for n in range(100)]
    inp = copy.deepcopy(INP)
    inp["pieces"] = [piece(text="".join(lines) + "- LAST line\n")]
    return inp, "".join(lines) + "- LAST line\n"


def test_a_long_piece_is_screened_in_parts_cut_at_line_ends():
    inp, text = long_inp()
    model = Parts(screen=SCREEN_ROW, assess={**ASSESS_BREAK, "effect": "minor"})
    out = judge(inp, model)
    assert len(model.texts) == 3 and "".join(model.texts) == text
    assert all(len(t) <= PART_CHARS and t.endswith("\n") for t in model.texts)
    assert len(out["findings"]) == 1 and out["judged"] == [PID]
    assert model.assess_calls == 1


def test_each_part_counts_as_a_model_call():
    inp, _ = long_inp()
    out = judge(inp, Parts(screen=SCREEN_ROW, assess=ASSESS_BREAK), max_calls=2)
    assert out["judged"] == [] and out["findings"] == []


def test_a_short_piece_is_one_part():
    model = Parts(screen=[])
    judge(INP, model)
    assert model.texts == [INP["pieces"][0]["text"]]


def test_effort_comes_from_the_environment_and_shows_in_the_name(monkeypatch):
    from watch_judge import OpenAIModel

    monkeypatch.setenv("OPENAI_API_KEY", "test")
    monkeypatch.setenv("WATCH_EFFORT", "high")
    model = OpenAIModel("gpt-x")
    assert model.name == "gpt-x high" and model.llm.reasoning_effort == "high"
    monkeypatch.setenv("WATCH_EFFORT", "")
    model = OpenAIModel("gpt-x")
    assert model.name == "gpt-x" and model.llm.reasoning_effort is None


def test_the_deadline_can_come_from_the_environment(monkeypatch):
    ticks = iter(range(0, 10_000, 100))
    monkeypatch.setenv("WATCH_DEADLINE_SECONDS", "150")
    out = judge(inp_with_pieces(5), Fake(screen=[]), clock=lambda: next(ticks))
    assert len(out["judged"]) == 1
