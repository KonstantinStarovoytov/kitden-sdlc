"""The judge's model on Claude, through Anthropic's own SDK.

Claude caches only what a request marks. Each call puts its long, unchanging start first and
marks it: the prompt and the list for `screen`; the Kitden files for `assess` and `refute`,
which repeat while the rows of one file are judged. What changes (the piece, the change, the
finding) comes after the mark. Thinking stays on, as these models require; WATCH_EFFORT sets
how much they think and is always sent, since Sonnet 5.5 and Opus 5.5 differ in their default.
A refusal or a cut answer fails the call, so the piece is not judged by a model it did not
name.
"""

import json
import os
from dataclasses import asdict

import watch_trace
from watch_judge import Assessed, Refuted, Screened, _prompt, _seconds, named, screen_messages

MAX_TOKENS = 16000
# Dollars for a million tokens, checked 2026-11-12: input, cache write (5 minutes), cache read,
# output.
PRICES = {
    "claude-sonnet-5-5": (2.0, 2.5, 0.10, 10.0),
    "claude-opus-5-5": (4.0, 5.0, 0.20, 20.0),
}


def _cached(text: str) -> dict:
    return {"type": "text", "text": text, "cache_control": {"type": "ephemeral"}}


class ClaudeModel:
    def __init__(self, name: str):
        import anthropic

        self.model = name
        self.effort = os.environ.get("WATCH_EFFORT") or "medium"
        self.name = f"{name} {self.effort}"
        self.client = anthropic.Anthropic(max_retries=2,
                                          timeout=_seconds("WATCH_CALL_SECONDS", 180))
        self.tokens = {"input": 0, "cache_write": 0, "cache_read": 0, "output": 0}

    def _ask(self, step: str, schema, system: list[dict], user: list[dict]):
        messages = [{"role": "user", "content": user}]
        with watch_trace.generation(step, self.name, [*system, *user]) as record:
            response = self.client.messages.parse(
                model=self.model, max_tokens=MAX_TOKENS, system=system, messages=messages,
                output_format=schema, output_config={"effort": self.effort})
            if response.stop_reason != "end_turn" or response.parsed_output is None:
                raise RuntimeError(f"stopped: {response.stop_reason}")
            got = self._count(response.usage)
            record(output=response.parsed_output.model_dump(), usage_details=got,
                   cost_details={"total": self._cost(got)})
        return response.parsed_output

    def _count(self, usage) -> dict[str, int]:
        got = {"input": usage.input_tokens or 0,
               "cache_write": usage.cache_creation_input_tokens or 0,
               "cache_read": usage.cache_read_input_tokens or 0,
               "output": usage.output_tokens or 0}
        for key, value in got.items():
            self.tokens[key] += value
        return got

    def _cost(self, got: dict[str, int]) -> float:
        prices = PRICES.get(self.model, (0, 0, 0, 0))
        return sum(n * p for n, p in zip(got.values(), prices, strict=True)) / 1_000_000

    def summary(self) -> str:
        t = self.tokens
        return (f"{self.name}: {t['input']} input, {t['cache_write']} cache write, "
                f"{t['cache_read']} cache read, {t['output']} output tokens, "
                f"about ${self._cost(t):.2f}")

    def screen(self, piece, list_text, known_titles):
        start, rest = screen_messages(piece, list_text, known_titles)
        out = self._ask("screen", Screened, [_cached(start["content"])],
                        [{"type": "text", "text": rest["content"]}])
        return named(out, piece["client"], list_text)

    def _judge(self, step: str, schema, files: dict, data: dict):
        return self._ask(step, schema, [{"type": "text", "text": _prompt(step)}],
                         [_cached(json.dumps({"files": files}, indent=1)),
                          {"type": "text", "text": json.dumps(data, indent=1)}])

    def assess(self, change, row, files):
        data = {"change": change, "row": asdict(row)}
        return self._judge("assess", Assessed, files, data).model_dump()

    def refute(self, finding, row, files):
        data = {"finding": finding, "row": asdict(row)}
        return not self._judge("refute", Refuted, files, data).holds
