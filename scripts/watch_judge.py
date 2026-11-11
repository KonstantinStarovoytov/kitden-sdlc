"""Judge what is new in the clients with a small LangGraph graph and write the findings."""

import argparse
import json
import os
import sys
import time
from dataclasses import asdict
from pathlib import Path
from typing import Literal, Protocol, TypedDict

from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel

import watch_trace
from watch_list import Row, parse_list, row_ids, row_labels, short_list

MAX_MODEL_CALLS = 60
DEADLINE_SECONDS = 600
FAILS_IN_A_ROW = 3
FILE_CHARS = 40000
PART_CHARS = 4000  # a long piece is screened in parts: the model misses less in a short text
PROMPTS = Path(__file__).resolve().parent.parent / "prompts"
DISAGREED = " A second look disagreed."


class Model(Protocol):
    def screen(self, piece: dict, list_text: str, known_titles: list[str]) -> list[dict]: ...
    def assess(self, change: dict, row: Row, files: dict[str, str]) -> dict: ...
    def refute(self, finding: dict, row: Row, files: dict[str, str]) -> bool: ...


class State(TypedDict):
    inp: dict
    max_calls: int
    i: int
    part: int
    calls: int
    stop: bool
    streak: int
    to_assess: list[dict]
    to_refute: list[dict]
    current: list[dict]
    judged: list[str]
    failed: list[str]
    findings: list[dict]


def _rows(list_text: str) -> dict[tuple[str, str], Row]:
    labels = row_labels(list_text)
    return {(row.client, labels[(row.client, row.what)]): row for row in parse_list(list_text)}


def _files(row: Row, inp: dict) -> dict[str, str]:
    return {f: inp["files"][f]["text"][:FILE_CHARS] for f in row.files if f in inp["files"]}


def _finding(inp: dict, piece: dict, label: str, row: Row | None, **kw) -> dict:
    return {"piece": piece["id"], "client": piece["client"], "version": piece["version"],
            "url": piece["url"], "row": label,
            "files": [f for f in row.files if f in inp["files"]] if row else [],
            **{k: str(kw[k]) for k in ("title", "changed", "effect", "user_gets", "systems",
                                       "why")},
            "sure": bool(kw["sure"])}


def _parts(text: str) -> list[str]:
    """The text cut at line ends into parts of about PART_CHARS."""
    parts, now = [], ""
    for line in text.splitlines(keepends=True):
        if now and len(now) + len(line) > PART_CHARS:
            parts.append(now)
            now = ""
        now += line
    return [*parts, now] if now or not parts else parts


def _full(state: State) -> bool:
    return state["calls"] + 1 > state["max_calls"]


class _Failed(Exception):
    pass


def _call(piece_id: str, fn, *args):
    try:
        with watch_trace.piece(piece_id):
            return fn(*args)
    except Exception as e:  # noqa: BLE001 - a failed call skips its piece, the run goes on
        print(f"model call failed for {piece_id}: {type(e).__name__}", file=sys.stderr)
        raise _Failed from None


def _stops(node, late):
    def run(state: State) -> dict:
        if _full(state) or late():
            return {"stop": True}
        try:
            return node(state)
        except _Failed:
            streak = state["streak"] + 1
            return {"calls": state["calls"] + 1, "i": state["i"] + 1, "streak": streak,
                    "stop": streak >= FAILS_IN_A_ROW, "current": [], "to_assess": [],
                    "to_refute": [], "part": 0,
                    "failed": [*state["failed"], state["inp"]["pieces"][state["i"]]["id"]]}
    return run


def build_graph(model: Model, late=lambda: False):
    def settle(state: State, update: dict) -> dict:
        new = {**state, **update, "calls": state["calls"] + 1}
        if not new["to_assess"] and not new["to_refute"]:
            new["judged"] = [*new["judged"], new["inp"]["pieces"][new["i"]]["id"]]
            new["findings"] = [*new["findings"], *new["current"]]
            new["current"], new["i"], new["streak"] = [], new["i"] + 1, 0
        return new

    def screen(state: State) -> dict:
        inp = state["inp"]
        piece, rows = inp["pieces"][state["i"]], _rows(inp["list"])
        parts = _parts(piece["text"])
        part = {**piece, "text": parts[state["part"]]}
        current, to_assess = [*state["current"]], [*state["to_assess"]]
        titles = inp["known_titles"] + [f["title"] for f in state["findings"] + current]
        for change in _call(piece["id"], model.screen, part, inp["list"], titles):
            label = change.get("row", "none")
            if label == "gap":
                current.append(_finding(inp, piece, "", None, effect="gap",
                                        systems="not checked", **{
                                            k: change.get(k, "") for k in
                                            ("title", "changed", "user_gets", "why")},
                                        sure=change.get("sure", False)))
            elif (piece["client"], label) in rows:
                to_assess.append({**change, "row": label})
        if state["part"] + 1 < len(parts):  # more of this piece to read before the next step
            return {"current": current, "to_assess": to_assess, "part": state["part"] + 1,
                    "calls": state["calls"] + 1}
        return settle(state, {"current": current, "to_assess": to_assess, "to_refute": [],
                              "part": 0})

    def assess(state: State) -> dict:
        inp = state["inp"]
        piece = inp["pieces"][state["i"]]
        change, *rest = state["to_assess"]
        row = _rows(inp["list"])[(piece["client"], change["row"])]
        got = _call(piece["id"], model.assess, change, row, _files(row, inp))
        f = _finding(inp, piece, change["row"], row, changed=change.get("changed", ""), **{
            k: got.get(k, "") for k in ("title", "effect", "user_gets", "systems", "why")},
            sure=got.get("sure", False))
        update = {"to_assess": rest}
        if f["effect"] == "none":  # the code shows Kitden is not touched: no finding
            pass
        elif f["effect"] in ("breaks", "wrong-data") and f["sure"]:
            update["to_refute"] = [*state["to_refute"], f]
        else:
            update["current"] = [*state["current"], f]
        return settle(state, update)

    def refute(state: State) -> dict:
        inp = state["inp"]
        f, *rest = state["to_refute"]
        row = _rows(inp["list"])[(f["client"], f["row"])]
        if _call(f["piece"], model.refute, f, row, _files(row, inp)):
            f = {**f, "sure": False, "why": f["why"] + DISAGREED}
        return settle(state, {"to_refute": rest, "current": [*state["current"], f]})

    def after(state: State) -> str:
        if state["stop"] or state["i"] >= len(state["inp"]["pieces"]):
            return END
        if state["part"]:
            return "screen"
        if state["to_assess"]:
            return "assess"
        if state["to_refute"]:
            return "refute"
        return "screen"

    graph = StateGraph(State)
    graph.add_node("screen", _stops(screen, late))
    graph.add_node("assess", _stops(assess, late))
    graph.add_node("refute", _stops(refute, late))
    graph.add_conditional_edges(START, after)
    for node in ("screen", "assess", "refute"):
        graph.add_conditional_edges(node, after)
    return graph.compile()


def judge(inp: dict, model: Model, max_calls: int = MAX_MODEL_CALLS,
          deadline: float = DEADLINE_SECONDS, clock=time.monotonic) -> dict:
    end_at = clock() + deadline
    start = {"inp": inp, "max_calls": max_calls, "i": 0, "part": 0, "calls": 0, "stop": False,
             "streak": 0, "to_assess": [], "to_refute": [], "current": [], "judged": [],
             "failed": [], "findings": []}
    graph = build_graph(model, lambda: clock() > end_at)
    end = graph.invoke(start, config={"recursion_limit": max_calls + 10})
    return {"judged": end["judged"], "findings": end["findings"], "failed": end["failed"]}


def _prompt(name: str) -> str:
    return (PROMPTS / f"watch-{name}.md").read_text(encoding="utf-8")


def screen_messages(piece: dict, list_text: str, known_titles: list[str]) -> list[dict]:
    data = {"piece": {k: piece[k] for k in ("client", "kind", "version", "url", "text")},
            "known_titles": known_titles}
    return [{"role": "system", "content": _prompt("screen") + short_list(list_text)},
            {"role": "user", "content": json.dumps(data, indent=1)}]


def _messages(name: str, data: dict) -> list[dict]:
    return [{"role": "system", "content": _prompt(name)},
            {"role": "user", "content": json.dumps(data, indent=1)}]


class Change(BaseModel):
    row: str
    title: str
    changed: str
    user_gets: str
    sure: bool
    why: str


class Screened(BaseModel):
    changes: list[Change]


class Assessed(BaseModel):
    effect: Literal["breaks", "wrong-data", "minor", "none"]
    sure: bool
    user_gets: str
    systems: str
    why: str
    title: str


class Refuted(BaseModel):
    reason: str
    holds: bool


def named(changes: list[Change], client: str, list_text: str) -> list[dict]:
    """The model names a row by its short id; the graph wants the row's label. An id that is
    not a row of the piece's client makes the change `none`."""
    ids = row_ids(list_text)
    out = []
    for change in changes:
        got = change.model_dump()
        if got["row"] != "gap":
            row_client, label = ids.get(got["row"].strip(), ("", "none"))
            got["row"] = label if row_client == client else "none"
        out.append(got)
    return out


class OpenAIModel:
    def __init__(self, name: str):
        from langchain_openai import ChatOpenAI

        # WATCH_EFFORT is how hard the model thinks (low, medium, high, xhigh, max); unset or
        # empty leaves the model's own default. The name in the traces carries it.
        effort = os.environ.get("WATCH_EFFORT") or None
        self.name = f"{name} {effort}" if effort else name
        # A long piece takes the model a minute or two, so one call may wait three.
        self.llm = ChatOpenAI(model=name, reasoning_effort=effort, max_retries=1, timeout=180)

    def _ask(self, step: str, schema: type[BaseModel], messages: list[dict]) -> BaseModel:
        config = watch_trace.config(step, self.name)
        return self.llm.with_structured_output(schema, strict=True).invoke(messages, config)

    def screen(self, piece, list_text, known_titles):
        out = self._ask("screen", Screened, screen_messages(piece, list_text, known_titles))
        return named(out.changes, piece["client"], list_text)

    def assess(self, change, row, files):
        data = {"change": change, "row": asdict(row), "files": files}
        return self._ask("assess", Assessed, _messages("assess", data)).model_dump()

    def refute(self, finding, row, files):
        data = {"finding": finding, "row": asdict(row), "files": files}
        return not self._ask("refute", Refuted, _messages("refute", data)).holds


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    inp = json.loads(Path(a.input).read_text(encoding="utf-8"))
    name = os.environ.get("WATCH_MODEL")
    if not name:
        print("WATCH_MODEL is not set", file=sys.stderr)
        raise SystemExit(1)
    max_calls = int(os.environ.get("MAX_MODEL_CALLS") or MAX_MODEL_CALLS)
    try:
        out = judge(inp, OpenAIModel(name), max_calls)
    finally:
        watch_trace.flush()
    Path(a.out).write_text(json.dumps(out, indent=1), encoding="utf-8")
    if inp["pieces"] and not out["judged"]:
        print(f"No piece was judged ({len(out['failed'])} failed); post saves the tries.",
              file=sys.stderr)


if __name__ == "__main__":
    main()
