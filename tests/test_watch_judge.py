import copy

from watch_judge import FILE_CHARS, judge, screen_messages
from watch_route import check

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

    def screen(self, piece, list_text, known_titles):
        self.screen_calls += 1
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
    assert out == {"judged": [], "findings": []}
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
    assert a[0] == b[0] and LIST_TEXT in a[0]["content"]
    assert PIECE_A["text"] not in a[0]["content"] and PIECE_A["text"] in a[1]["content"]
