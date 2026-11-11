import logging

import pytest


@pytest.fixture(autouse=True)
def no_langfuse_keys(monkeypatch):
    """Keys in the shell must not send a test's calls to Langfuse; a test sets fakes."""
    for name in ("LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY", "LANGFUSE_HOST", "GITHUB_SHA"):
        monkeypatch.delenv(name, raising=False)
    levels = {n: logging.getLogger(n).level for n in ("langfuse", "opentelemetry")}
    yield
    for name, level in levels.items():
        logging.getLogger(name).setLevel(level)
