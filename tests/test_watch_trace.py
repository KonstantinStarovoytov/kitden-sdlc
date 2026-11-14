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
    watch_trace._traces.clear()
    yield
    watch_trace._handler.cache_clear()
    watch_trace._traces.clear()


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
                                    systems="all", why="w", fix="f", title="t")
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
        assert c["metadata"]["langfuse_tags"] == ["claude-code", "gpt-test"]
        assert c["metadata"]["langfuse_session_id"] == f"{PID} gpt-test abc1234"
        assert c["metadata"]["step"] == step
        assert c["metadata"]["piece"] == PID
        assert c["metadata"]["client"] == "claude-code"
        assert c["metadata"]["version"] == "2.1.320"
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


def span_langfuse(monkeypatch, log, inside=None):
    """A stand-in SDK that keeps what it is asked. `inside` is the trace the call is already
    in, as in an experiment."""
    lf = types.ModuleType("langfuse")

    def start(**kw):
        log.append(("start", kw))
        return Observation(log, **kw)

    def propagate(**kw):
        log.append(("attrs", kw))
        return Observation(log)

    lf.get_client = lambda: types.SimpleNamespace(
        start_as_current_observation=start, flush=lambda: None,
        get_current_trace_id=lambda: inside,
        create_trace_id=lambda seed: f"trace of {seed.split(' ', 1)[1]}",
        create_score=lambda **kw: log.append(("score", kw)),
        get_trace_url=lambda trace_id: f"https://langfuse.test/{trace_id}")
    lf.propagate_attributes = propagate
    monkeypatch.setitem(sys.modules, "langfuse", lf)


def test_a_direct_call_is_a_span_with_the_same_session_and_tags(monkeypatch):
    keys(monkeypatch)
    monkeypatch.setenv("GITHUB_SHA", "abc1234def")
    log = []
    span_langfuse(monkeypatch, log)
    with watch_trace.piece(PID, "claude-code", "2.1.320"), \
            watch_trace.call("screen", "claude-x medium", ["m"]) as rec:
        rec(output={"a": 1})
    (_, attrs), (_, start), (_, update) = log
    assert attrs["session_id"] == f"{PID} claude-x medium abc1234"
    assert attrs["tags"] == ["claude-code", "claude-x medium"]
    assert attrs["metadata"] == {"step": "screen", "piece": PID, "client": "claude-code",
                                 "version": "2.1.320", "model": "claude-x medium",
                                 "commit": "abc1234def"}
    assert start["as_type"] == "span" and start["name"] == "screen"
    assert update == {"output": {"a": 1}}


def daily(monkeypatch):
    keys(monkeypatch)
    monkeypatch.setenv("LANGFUSE_TRACING_ENVIRONMENT", "daily")
    monkeypatch.setenv("GITHUB_RUN_NUMBER", "57")
    monkeypatch.setenv("GITHUB_RUN_ID", "900")
    monkeypatch.setenv("GITHUB_REPOSITORY", "o/kitden-sdlc")
    monkeypatch.setattr(watch_trace, "_day", lambda: "2026-11-14")


def test_a_daily_run_is_one_session_and_each_piece_is_one_trace_named_by_it(monkeypatch):
    daily(monkeypatch)
    log = []
    span_langfuse(monkeypatch, log)
    for piece_id, step in ((PID, "screen"), (PID, "assess"), ("codex#0.168.0", "screen")):
        with watch_trace.piece(piece_id, piece_id.split("-ch")[0].split("#")[0], "1"), \
                watch_trace.call(step, "claude-x medium", ["m"]):
            pass
    attrs = [kw for what, kw in log if what == "attrs"]
    starts = [kw for what, kw in log if what == "start"]
    assert {a["session_id"] for a in attrs} == {"daily 2026-11-14 #57"}
    assert [a["trace_name"] for a in attrs] == [PID, PID, "codex#0.168.0"]
    assert attrs[0]["tags"] == ["daily", "claude-code", "claude-x medium"]
    assert attrs[2]["tags"] == ["daily", "codex", "claude-x medium"]
    assert attrs[0]["metadata"]["run"] == "https://github.com/o/kitden-sdlc/actions/runs/900"
    traces = [s["trace_context"]["trace_id"] for s in starts]
    assert traces[0] == traces[1] == f"trace of {PID}" and traces[2] == "trace of codex#0.168.0"


def test_inside_an_experiment_the_call_stays_in_the_experiments_trace(monkeypatch):
    daily(monkeypatch)
    log = []
    span_langfuse(monkeypatch, log, inside="experiment-trace")
    with watch_trace.piece(PID, "claude-code", "1"), watch_trace.call("screen", "m", ["m"]):
        pass
    (_, attrs), (_, start) = log
    assert "trace_name" not in attrs and "trace_context" not in start
    assert watch_trace._traces == {}


def test_the_report_scores_each_piece_and_prints_its_link(monkeypatch, capsys):
    daily(monkeypatch)
    log = []
    span_langfuse(monkeypatch, log)
    for piece_id in (PID, "codex#0.168.0"):
        with watch_trace.piece(piece_id, "c", "1"), watch_trace.call("screen", "m", ["m"]):
            pass
    watch_trace.report({"judged": [PID], "findings": [{"piece": PID}, {"piece": PID}]})
    scores = {(kw["trace_id"], kw["name"]): kw["value"] for what, kw in log if what == "score"}
    assert scores == {(f"trace of {PID}", "judged"): 1, (f"trace of {PID}", "findings"): 2,
                      ("trace of codex#0.168.0", "judged"): 0,
                      ("trace of codex#0.168.0", "findings"): 0}
    assert capsys.readouterr().out.splitlines() == [
        f"Trace of {PID}: https://langfuse.test/trace of {PID}",
        "Trace of codex#0.168.0: https://langfuse.test/trace of codex#0.168.0"]


def test_the_report_does_nothing_without_keys_or_without_its_own_traces(monkeypatch, capsys):
    no_langfuse(monkeypatch)
    watch_trace.report({"judged": [PID], "findings": []})
    keys(monkeypatch)
    watch_trace.report({"judged": [PID], "findings": []})
    out = capsys.readouterr()
    assert out.out == "" and out.err == ""


def test_a_direct_call_without_keys_imports_nothing_and_a_failure_does_not_stop_it(
        monkeypatch, capsys):
    no_langfuse(monkeypatch)
    with watch_trace.call("screen", "m", []) as rec:
        rec(output=1)
    keys(monkeypatch)
    with watch_trace.call("screen", "m", []) as rec:
        rec(output=1)
    assert capsys.readouterr().err == "langfuse failed: ModuleNotFoundError\n"
