import logging
import os
import sys
import types

import pytest

import watch_judge
import watch_trace
from tests.test_watch_judge import INP, LIST_TEXT, PID, piece
from watch_judge import Assessed, Refuted, RowCheck, Screened, judge

ROW = "the `skillOverrides` key"


@pytest.fixture(autouse=True)
def fresh():
    watch_trace._handler.cache_clear()
    yield
    watch_trace._handler.cache_clear()


def keys(monkeypatch):
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-test")


class Handler:
    pass


def fake_langfuse(monkeypatch, handler=Handler, get_client=None):
    lf = types.ModuleType("langfuse")
    lf.get_client = get_client or (lambda: types.SimpleNamespace(flush=lambda: None))
    lc = types.ModuleType("langfuse.langchain")
    lc.CallbackHandler = handler
    monkeypatch.setitem(sys.modules, "langfuse", lf)
    monkeypatch.setitem(sys.modules, "langfuse.langchain", lc)


def no_langfuse(monkeypatch):
    """Any import of langfuse fails, so a test sees whether one was tried."""
    monkeypatch.setitem(sys.modules, "langfuse", None)
    monkeypatch.setitem(sys.modules, "langfuse.langchain", None)


class Llm:
    """Stands in for ChatOpenAI: answers each schema and keeps the config of each call."""

    def __init__(self):
        self.calls = []

    def with_structured_output(self, schema, strict):
        llm = self

        class Bound:
            def invoke(self, messages, config=None):
                llm.calls.append((schema.__name__, messages, config))
                if schema is Screened:
                    return Screened(rows=[RowCheck(row="CC-01", quote="Changed skillOverrides.",
                                                   touched=True, title="t", changed="c")],
                                    gaps=[])
                if schema is Assessed:
                    return Assessed(kitden_reads="k", client_now="c", shown_wrong="s",
                                    effect="breaks", severity="major", sure=True, user_gets="u",
                                    systems="all", why="w", title="t")
                return Refuted(reason="r", holds=True)
        return Bound()


REAL_MODEL = watch_judge.OpenAIModel


def model():
    m = REAL_MODEL.__new__(REAL_MODEL)
    m.name, m.llm = "gpt-test", Llm()
    return m


def test_off_without_keys_nothing_is_imported_or_passed(monkeypatch, capsys):
    no_langfuse(monkeypatch)
    m = model()
    out = judge(INP, m)
    watch_trace.flush()
    assert [c[0] for c in m.llm.calls] == ["Screened", "Assessed", "Refuted"]
    assert all(config is None for _, _, config in m.llm.calls)
    assert len(out["findings"]) == 1 and capsys.readouterr().err == ""


def test_one_key_alone_is_off(monkeypatch):
    no_langfuse(monkeypatch)
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-test")
    assert not watch_trace.enabled() and watch_trace.config("screen", "m") is None


def test_on_with_keys_the_handler_goes_to_every_model_call(monkeypatch):
    keys(monkeypatch)
    monkeypatch.setenv("GITHUB_SHA", "abc1234def")
    fake_langfuse(monkeypatch)
    m = model()
    judge(INP, m)
    steps = ["screen", "assess", "refute"]
    configs = [config for _, _, config in m.llm.calls]
    assert len(configs) == 3
    handlers = {id(c["callbacks"][0]) for c in configs}
    assert len(handlers) == 1 and isinstance(configs[0]["callbacks"][0], Handler)
    for step, c in zip(steps, configs, strict=True):
        assert c["run_name"] == step
        assert c["metadata"]["langfuse_tags"] == [PID, "gpt-test", "abc1234def"]
        assert c["metadata"]["langfuse_session_id"] == f"{PID} gpt-test abc1234"
        assert c["metadata"]["step"] == step
        assert c["metadata"]["commit"] == "abc1234def"


def test_tracing_leaves_the_messages_and_the_findings_as_they_were(monkeypatch):
    off = model()
    plain = judge(INP, off)
    keys(monkeypatch)
    fake_langfuse(monkeypatch)
    on = model()
    assert judge(INP, on) == plain
    assert [c[1] for c in on.llm.calls] == [c[1] for c in off.llm.calls]
    assert on.llm.calls[0][1][0] == watch_judge.screen_messages(piece(), LIST_TEXT, ["old"])[0]


def test_a_broken_handler_prints_one_line_and_the_judge_goes_on(monkeypatch, capsys):
    keys(monkeypatch)

    def broken():
        raise ConnectionError("https://cloud.langfuse.com sk-test")

    fake_langfuse(monkeypatch, handler=broken)
    m = model()
    out = judge(INP, m)
    assert len(out["findings"]) == 1 and all(c is None for _, _, c in m.llm.calls)
    assert capsys.readouterr().err == "langfuse failed: ConnectionError\n"


def test_a_failed_flush_prints_one_line(monkeypatch, capsys):
    keys(monkeypatch)

    def get_client():
        raise PermissionError("sk-test")

    fake_langfuse(monkeypatch, get_client=get_client)
    watch_trace.flush()
    assert capsys.readouterr().err == "langfuse failed: PermissionError\n"


def test_the_cli_flushes_at_the_end(tmp_path, monkeypatch):
    import json

    keys(monkeypatch)
    flushed = []
    fake_langfuse(monkeypatch, get_client=lambda: types.SimpleNamespace(
        flush=lambda: flushed.append(1)))
    (tmp_path / "input.json").write_text(json.dumps(INP))
    monkeypatch.setenv("WATCH_MODEL", "m")
    monkeypatch.setattr(watch_judge, "OpenAIModel", lambda name: model())
    monkeypatch.setattr(sys, "argv", ["watch_judge.py", "--input", str(tmp_path / "input.json"),
                                      "--out", str(tmp_path / "findings.json")])
    watch_judge.main()
    assert flushed == [1]


def test_without_a_commit_the_session_is_the_piece_and_model_cut_to_200_ascii(monkeypatch):
    keys(monkeypatch)
    fake_langfuse(monkeypatch)
    with watch_trace.piece("p" * 300 + "é"):
        session = watch_trace.config("screen", "m")["metadata"]["langfuse_session_id"]
    assert session == "p" * 200
    with watch_trace.piece(PID):
        assert watch_trace.config("screen", "m")["metadata"]["langfuse_session_id"] == f"{PID} m"


def test_an_empty_host_is_dropped_before_langfuse_is_imported(monkeypatch):
    keys(monkeypatch)
    monkeypatch.setenv("LANGFUSE_HOST", "")
    seen = []

    class Seeing:
        def __init__(self):
            seen.append(os.environ.get("LANGFUSE_HOST"))

    fake_langfuse(monkeypatch, handler=Seeing)
    watch_trace.config("screen", "m")
    assert seen == [None] and "LANGFUSE_HOST" not in os.environ


def test_a_set_host_is_kept(monkeypatch):
    monkeypatch.setenv("LANGFUSE_HOST", "https://us.cloud.langfuse.com")
    watch_trace.setup()
    assert os.environ["LANGFUSE_HOST"] == "https://us.cloud.langfuse.com"


def test_the_sdk_log_lines_are_silenced(capsys):
    watch_trace.setup()
    logging.getLogger("langfuse").error("Item 0 failed: sk-test")
    logging.getLogger("opentelemetry.sdk").error("export failed: sk-test")
    assert capsys.readouterr().err == ""


class Observation:
    def __init__(self, log, **kw):
        self.log, self.kw = log, kw

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def update(self, **details):
        self.log.append(("update", details))


def span_langfuse(monkeypatch, log):
    lf = types.ModuleType("langfuse")

    def start(**kw):
        log.append(("start", kw))
        return Observation(log, **kw)

    def propagate(**kw):
        log.append(("attrs", kw))
        return Observation(log)

    lf.get_client = lambda: types.SimpleNamespace(start_as_current_observation=start,
                                                  flush=lambda: None)
    lf.propagate_attributes = propagate
    monkeypatch.setitem(sys.modules, "langfuse", lf)


def test_a_direct_call_is_a_span_with_the_same_session_and_tags(monkeypatch):
    keys(monkeypatch)
    monkeypatch.setenv("GITHUB_SHA", "abc1234def")
    log = []
    span_langfuse(monkeypatch, log)
    with watch_trace.piece(PID), watch_trace.call("screen", "claude-x medium", ["m"]) as rec:
        rec(output={"a": 1})
    (_, attrs), (_, start), (_, update) = log
    assert attrs["session_id"] == f"{PID} claude-x medium abc1234"
    assert attrs["tags"] == [PID, "claude-x medium", "abc1234def"]
    assert start["as_type"] == "span" and start["name"] == "screen"
    assert update == {"output": {"a": 1}}


def test_a_direct_call_without_keys_imports_nothing_and_a_failure_does_not_stop_it(
        monkeypatch, capsys):
    no_langfuse(monkeypatch)
    with watch_trace.call("screen", "m", []) as rec:
        rec(output=1)
    keys(monkeypatch)
    with watch_trace.call("screen", "m", []) as rec:
        rec(output=1)
    assert capsys.readouterr().err == "langfuse failed: ModuleNotFoundError\n"
