import sys
import types

import pytest

import watch_claude
import watch_judge
from tests.test_watch_judge import FILE, LIST_TEXT, PIECE_A
from watch_judge import Assessed, Refuted, RowCheck, Screened
from watch_list import parse_list


class Client:
    """Stands in for anthropic.Anthropic: answers each schema and keeps each request."""

    def __init__(self, stop="end_turn", **kw):
        self.kw, self.calls, self.stop = kw, [], stop
        self.messages = types.SimpleNamespace(parse=self.parse)

    def parse(self, **request):
        self.calls.append(request)
        schema = request["output_format"]
        out = {
            Screened: Screened(rows=[RowCheck(row="CC-01", quote="q", touched=True, title="t",
                                              changed="c")], gaps=[]),
            Assessed: Assessed(kitden_reads="k", client_now="c", shown_wrong="s",
                               effect="breaks", severity="major", sure=True,
                               user_gets="u", systems="s",
                               why="w", title="t"),
            Refuted: Refuted(reason="r", holds=False),
        }[schema]
        usage = types.SimpleNamespace(input_tokens=1000, cache_creation_input_tokens=2000,
                                      cache_read_input_tokens=10000, output_tokens=500)
        return types.SimpleNamespace(stop_reason=self.stop, parsed_output=out, usage=usage,
                                     model=request["model"])


@pytest.fixture
def client(monkeypatch):
    made = []

    def anthropic_client(**kw):
        made.append(Client(**kw))
        return made[-1]

    monkeypatch.setitem(sys.modules, "anthropic", types.SimpleNamespace(Anthropic=anthropic_client))
    for name in ("LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY", "WATCH_EFFORT"):
        monkeypatch.delenv(name, raising=False)
    return made


ROW = parse_list(LIST_TEXT)[0]


def test_a_claude_name_gets_the_claude_model_with_effort_medium_unless_set(client, monkeypatch):
    model = watch_judge.chat_model("claude-sonnet-5-5")
    assert isinstance(model, watch_claude.ClaudeModel) and model.name == "claude-sonnet-5-5 medium"
    monkeypatch.setenv("WATCH_EFFORT", "high")
    assert watch_judge.chat_model("claude-opus-5-5").effort == "high"


def test_screen_caches_the_prompt_and_list_and_sends_the_piece_after(client):
    model = watch_claude.ClaudeModel("claude-sonnet-5-5")
    got = model.screen(PIECE_A, LIST_TEXT, [])
    request = client[0].calls[0]
    (system,) = request["system"]
    assert system["cache_control"] == {"type": "ephemeral"} and "CC-01" in system["text"]
    (user,) = request["messages"][0]["content"]
    assert "cache_control" not in user and PIECE_A["text"] in user["text"]
    assert request["output_config"] == {"effort": "medium"} and request["output_format"] is Screened
    assert got[0]["row"] == "the `skillOverrides` key"


def test_assess_and_refute_cache_the_files_and_send_the_change_after(client):
    model = watch_claude.ClaudeModel("claude-opus-5-5")
    files = {FILE: "code"}
    assert model.assess({"title": "t"}, ROW, files)["effect"] == "breaks"
    assert model.refute({"title": "t"}, ROW, files) is True
    for request in client[0].calls:
        cached, rest = request["messages"][0]["content"]
        assert cached["cache_control"] == {"type": "ephemeral"} and FILE in cached["text"]
        assert "cache_control" not in rest and '"row"' in rest["text"]
        assert "cache_control" not in request["system"][0]


def test_tokens_and_cost_are_counted(client):
    model = watch_claude.ClaudeModel("claude-sonnet-5-5")
    model.screen(PIECE_A, LIST_TEXT, [])
    model.screen(PIECE_A, LIST_TEXT, [])
    # Two calls: 2,000 input at $2, 4,000 written at $2.50, 20,000 read at $0.10, 1,000 out at $10.
    assert model.tokens == {"input": 2000, "cache_write": 4000, "cache_read": 20000,
                            "output": 1000}
    assert "about $0.03" in model.summary()


def test_a_refusal_or_a_cut_answer_fails_the_call(client, monkeypatch):
    model = watch_claude.ClaudeModel("claude-sonnet-5-5")
    model.client = Client(stop="refusal")
    with pytest.raises(RuntimeError, match="refusal"):
        model.screen(PIECE_A, LIST_TEXT, [])
    model.client = Client(stop="max_tokens")
    with pytest.raises(RuntimeError, match="max_tokens"):
        model.assess({}, ROW, {})
