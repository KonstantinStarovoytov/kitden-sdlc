"""Send the judge's model calls to Langfuse, only when LANGFUSE_PUBLIC_KEY and
LANGFUSE_SECRET_KEY are set (LANGFUSE_HOST gives the region). Without them nothing is
imported. A Langfuse error prints one line with its type and the run goes on.

How to find a run there (docs/watcher-design.md, part 9): LANGFUSE_TRACING_ENVIRONMENT is the
kind of run (`daily` or `eval`) and Langfuse's environment filter. A daily run is one session,
and each piece of it is one trace named by the piece, with a span for each model call. In an
eval the experiment owns the traces, one a task."""

import logging
import os
import sys
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime
from functools import cache

_piece: ContextVar[dict | None] = ContextVar("watch_piece", default=None)
_traces: dict[str, str] = {}  # piece id -> the id of the trace this run made for it
_RUN = uuid.uuid4().hex  # so a second run on the same day never writes into the first's traces


def enabled() -> bool:
    return bool(os.environ.get("LANGFUSE_PUBLIC_KEY") and os.environ.get("LANGFUSE_SECRET_KEY"))


def warn(e: Exception) -> None:
    print(f"langfuse failed: {type(e).__name__}", file=sys.stderr)


def setup() -> None:
    """Call before any langfuse import: GitHub gives "" for an unset variable, and an empty
    host would replace the SDK's default. The SDK's own log lines (messages, tracebacks) are
    silenced; warn() says what failed."""
    if os.environ.get("LANGFUSE_HOST") == "":
        del os.environ["LANGFUSE_HOST"]
    for name in ("langfuse", "opentelemetry"):
        logging.getLogger(name).setLevel(logging.CRITICAL)


def commit() -> str:
    return os.environ.get("GITHUB_SHA", "")


def kind() -> str:
    """`daily` or `eval` when the workflow says so; the SDK reads the same variable."""
    return os.environ.get("LANGFUSE_TRACING_ENVIRONMENT", "")


def run_url() -> str:
    run, repo = os.environ.get("GITHUB_RUN_ID"), os.environ.get("GITHUB_REPOSITORY")
    server = os.environ.get("GITHUB_SERVER_URL", "https://github.com")
    return f"{server}/{repo}/actions/runs/{run}" if run and repo else ""


@cache
def _day() -> str:
    return f"{datetime.now(UTC):%Y-%m-%d}"


def _ascii(text: str) -> str:
    return text.encode("ascii", "ignore").decode()[:200]


@contextmanager
def piece(piece_id: str, client: str = "", version: str = ""):
    """The piece whose model calls run inside, so their traces are grouped by it."""
    token = _piece.set({"id": piece_id, "client": client, "version": version})
    try:
        yield
    finally:
        _piece.reset(token)


@cache
def _handler():
    try:
        setup()
        from langfuse.langchain import CallbackHandler

        return CallbackHandler()
    except Exception as e:  # noqa: BLE001 - Langfuse must never stop the judge
        warn(e)
        return None


def _attrs(step: str, model: str) -> tuple[list[str], dict, str | None]:
    """The tags, metadata and session of one model call. The tags are the few things to filter
    by (the kind of run, the client, the model); what names one piece or one run is metadata."""
    now = _piece.get() or {}
    piece_id = now.get("id", "")
    tags = [t for t in (kind(), now.get("client"), model) if t]
    metadata = {"step": step, "piece": piece_id, "client": now.get("client"),
                "version": now.get("version"), "model": model, "commit": commit(),
                "run": run_url()}
    metadata = {k: _ascii(v) for k, v in metadata.items() if v}
    if kind() == "daily":  # one session a daily run: every piece it read, in order
        number = os.environ.get("GITHUB_RUN_NUMBER")
        return tags, metadata, f"daily {_day()} #{number}" if number else f"daily {_day()}"
    # One session per piece, model setting and commit, so other runs do not pile into it.
    session = f"{piece_id} {model} {commit()[:7]}".strip()
    return tags, metadata, _ascii(session) if piece_id else None


def _own_trace(client) -> dict:
    """Outside an experiment, every call of one piece goes into one trace named by the piece.
    Inside one the experiment's trace is kept, so nothing is returned."""
    piece_id = (_piece.get() or {}).get("id", "")
    if not piece_id or client.get_current_trace_id() is not None:
        return {}
    if piece_id not in _traces:
        _traces[piece_id] = client.create_trace_id(seed=f"{_RUN} {piece_id}")
    return {"trace_name": _ascii(piece_id), "trace_id": _traces[piece_id]}


def config(step: str, model: str) -> dict | None:
    """The LangChain config of one model call: Langfuse's handler and the call's tags."""
    if not enabled() or (handler := _handler()) is None:
        return None
    tags, metadata, session = _attrs(step, model)
    metadata["langfuse_tags"] = tags
    if session:
        metadata["langfuse_session_id"] = session
    return {"callbacks": [handler], "run_name": step, "metadata": metadata}


def _nothing(**_) -> None:
    pass


@contextmanager
def call(step: str, model: str, messages: list):
    """A Langfuse span around one call made without LangChain (Claude through Anthropic's SDK),
    with the same tags and session as config(). The SDK traces the request itself, with the
    model, the tokens and the cost, so this span holds only the step and the parsed answer.
    Yields a function that records the answer; without the keys it does nothing."""
    if not enabled():
        yield _nothing
        return
    try:
        setup()
        from langfuse import get_client, propagate_attributes

        tags, metadata, session = _attrs(step, model)
        client, where, named = get_client(), {}, {}
        if own := _own_trace(client):
            where = {"trace_context": {"trace_id": own["trace_id"]}}
            named = {"trace_name": own["trace_name"]}
        attrs = propagate_attributes(session_id=session, tags=tags, metadata=metadata, **named)
        gen = client.start_as_current_observation(
            name=step, as_type="span", input=messages, **where)
    except Exception as e:  # noqa: BLE001 - Langfuse must never stop the judge
        warn(e)
        yield _nothing
        return
    with attrs, gen as observation:
        def record(**details) -> None:
            try:
                observation.update(**details)
            except Exception as e:  # noqa: BLE001
                warn(e)

        yield record


def report(out: dict) -> None:
    """After a run: each piece's trace gets the scores `judged` (1 or 0) and `findings` (a
    count), so Langfuse can list the pieces that found something, and the log gets a link to
    each trace. Only for the traces this run made itself."""
    if not enabled() or not _traces:
        return
    try:
        setup()
        from langfuse import get_client

        client = get_client()
        found: dict[str, int] = {}
        for finding in out.get("findings", []):
            found[finding["piece"]] = found.get(finding["piece"], 0) + 1
        for piece_id, trace_id in _traces.items():
            client.create_score(trace_id=trace_id, name="judged", data_type="BOOLEAN",
                                value=int(piece_id in out.get("judged", [])))
            client.create_score(trace_id=trace_id, name="findings", data_type="NUMERIC",
                                value=found.get(piece_id, 0))
            if url := client.get_trace_url(trace_id=trace_id):
                print(f"Trace of {piece_id}: {url}")
    except Exception as e:  # noqa: BLE001
        warn(e)


def flush() -> None:
    if not enabled():
        return
    try:
        setup()
        from langfuse import get_client

        get_client().flush()
    except Exception as e:  # noqa: BLE001
        warn(e)
