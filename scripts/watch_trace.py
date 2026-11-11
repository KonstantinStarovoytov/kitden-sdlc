"""Send the judge's model calls to Langfuse, only when LANGFUSE_PUBLIC_KEY and
LANGFUSE_SECRET_KEY are set (LANGFUSE_HOST gives the region). Without them nothing is
imported. A Langfuse error prints one line with its type and the run goes on."""

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
        from langfuse.langchain import CallbackHandler

        return CallbackHandler()
    except Exception as e:  # noqa: BLE001 - Langfuse must never stop the judge
        warn(e)
        return None


def config(step: str, model: str) -> dict | None:
    """The LangChain config of one model call: Langfuse's handler and the call's tags."""
    if not enabled() or (handler := _handler()) is None:
        return None
    piece_id = _piece.get()
    tags = [t for t in (step, piece_id, model, commit()) if t]
    metadata = {"langfuse_tags": tags, "step": step, "piece": piece_id, "model": model,
                "commit": commit()}
    if piece_id:
        metadata["langfuse_session_id"] = piece_id
    return {"callbacks": [handler], "run_name": step, "metadata": metadata}


def flush() -> None:
    if not enabled():
        return
    try:
        from langfuse import get_client

        get_client().flush()
    except Exception as e:  # noqa: BLE001
        warn(e)
