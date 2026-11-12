"""Send the judge's model calls to Langfuse, only when LANGFUSE_PUBLIC_KEY and
LANGFUSE_SECRET_KEY are set (LANGFUSE_HOST gives the region). Without them nothing is
imported. A Langfuse error prints one line with its type and the run goes on."""

import logging
import os
import sys
from contextlib import contextmanager
from contextvars import ContextVar
from functools import cache

_piece = ContextVar("watch_piece", default="")


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


@contextmanager
def piece(piece_id: str):
    """The piece whose model calls run inside, so their traces are grouped by it."""
    token = _piece.set(piece_id)
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
    """The tags, metadata and session of one model call."""
    piece_id = _piece.get()
    tags = [t for t in (piece_id, model, commit()) if t]
    metadata = {"step": step, "piece": piece_id, "model": model, "commit": commit()}
    # One session per piece, model setting and commit, so other runs do not pile into it.
    session = f"{piece_id} {model} {commit()[:7]}".strip()
    return tags, metadata, session.encode("ascii", "ignore").decode()[:200] if piece_id else None


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
        attrs = propagate_attributes(session_id=session, tags=tags, metadata=metadata)
        gen = get_client().start_as_current_observation(
            name=step, as_type="span", input=messages)
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


def flush() -> None:
    if not enabled():
        return
    try:
        setup()
        from langfuse import get_client

        get_client().flush()
    except Exception as e:  # noqa: BLE001
        warn(e)
