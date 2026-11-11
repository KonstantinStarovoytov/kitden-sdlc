"""Judge what is new in the clients with a small LangGraph graph and write the findings."""

import argparse
import json
import os
from dataclasses import asdict
from pathlib import Path
from typing import Literal, Protocol, TypedDict

from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel

from watch_list import Row, _table_rows, parse_list

MAX_MODEL_CALLS = 60
FILE_CHARS = 40000
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
    calls: int
    stop: bool
    to_assess: list[dict]
    to_refute: list[dict]
    current: list[dict]
    judged: list[str]
    findings: list[dict]


def _rows(list_text: str) -> dict[tuple[str, str], Row]:
    return {(client, cells[0]): row
            for (client, cells), row in zip(_table_rows(list_text), parse_list(list_text),
                                            strict=True)}


def _files(row: Row, inp: dict) -> dict[str, str]:
    return {f: inp["files"][f]["text"][:FILE_CHARS] for f in row.files if f in inp["files"]}


def _finding(inp: dict, piece: dict, label: str, row: Row | None, **kw) -> dict:
    return {"piece": piece["id"], "client": piece["client"], "version": piece["version"],
            "url": piece["url"], "row": label,
            "files": [f for f in row.files if f in inp["files"]] if row else [],
            **{k: str(kw[k]) for k in ("title", "changed", "effect", "user_gets", "systems",
                                       "why")},
            "sure": bool(kw["sure"])}


def _full(state: State) -> bool:
    return state["calls"] + 1 > state["max_calls"]


def build_graph(model: Model):
    def settle(state: State, update: dict) -> dict:
        new = {**state, **update, "calls": state["calls"] + 1}
        if not new["to_assess"] and not new["to_refute"]:
            new["judged"] = [*new["judged"], new["inp"]["pieces"][new["i"]]["id"]]
            new["findings"] = [*new["findings"], *new["current"]]
            new["current"], new["i"] = [], new["i"] + 1
        return new

    def screen(state: State) -> dict:
        if _full(state):
            return {"stop": True}
        inp = state["inp"]
        piece, rows = inp["pieces"][state["i"]], _rows(inp["list"])
        current, to_assess = [], []
        for change in model.screen(piece, inp["list"], inp["known_titles"]):
            label = change.get("row", "none")
            if label == "gap":
                current.append(_finding(inp, piece, "", None, effect="gap",
                                        systems="not checked", **{
                                            k: change.get(k, "") for k in
                                            ("title", "changed", "user_gets", "why")},
                                        sure=change.get("sure", False)))
            elif (piece["client"], label) in rows:
                to_assess.append({**change, "row": label})
        return settle(state, {"current": current, "to_assess": to_assess, "to_refute": []})

    def assess(state: State) -> dict:
        if _full(state):
            return {"stop": True}
        inp = state["inp"]
        piece = inp["pieces"][state["i"]]
        change, *rest = state["to_assess"]
        row = _rows(inp["list"])[(piece["client"], change["row"])]
        got = model.assess(change, row, _files(row, inp))
        f = _finding(inp, piece, change["row"], row, changed=change.get("changed", ""), **{
            k: got.get(k, "") for k in ("title", "effect", "user_gets", "systems", "why")},
            sure=got.get("sure", False))
        update = {"to_assess": rest}
        if f["effect"] in ("breaks", "wrong-data") and f["sure"]:
            update["to_refute"] = [*state["to_refute"], f]
        else:
            update["current"] = [*state["current"], f]
        return settle(state, update)

    def refute(state: State) -> dict:
        if _full(state):
            return {"stop": True}
        inp = state["inp"]
        f, *rest = state["to_refute"]
        row = _rows(inp["list"])[(f["client"], f["row"])]
        if model.refute(f, row, _files(row, inp)):
            f = {**f, "sure": False, "why": f["why"] + DISAGREED}
        return settle(state, {"to_refute": rest, "current": [*state["current"], f]})

    def after(state: State) -> str:
        if state["stop"] or state["i"] >= len(state["inp"]["pieces"]):
            return END
        if state["to_assess"]:
            return "assess"
        if state["to_refute"]:
            return "refute"
        return "screen"

    graph = StateGraph(State)
    graph.add_node("screen", screen)
    graph.add_node("assess", assess)
    graph.add_node("refute", refute)
    graph.add_conditional_edges(START, after)
    for node in ("screen", "assess", "refute"):
        graph.add_conditional_edges(node, after)
    return graph.compile()


def judge(inp: dict, model: Model, max_calls: int = MAX_MODEL_CALLS) -> dict:
    start = {"inp": inp, "max_calls": max_calls, "i": 0, "calls": 0, "stop": False,
             "to_assess": [], "to_refute": [], "current": [], "judged": [], "findings": []}
    end = build_graph(model).invoke(start, config={"recursion_limit": max_calls + 10})
    return {"judged": end["judged"], "findings": end["findings"]}


def _prompt(name: str) -> str:
    return (PROMPTS / f"watch-{name}.md").read_text(encoding="utf-8")


def screen_messages(piece: dict, list_text: str, known_titles: list[str]) -> list[dict]:
    data = {"piece": {k: piece[k] for k in ("client", "version", "url", "text")},
            "known_titles": known_titles}
    return [{"role": "system", "content": _prompt("screen") + list_text},
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
    effect: Literal["breaks", "wrong-data", "minor"]
    sure: bool
    user_gets: str
    systems: str
    why: str
    title: str


class Refuted(BaseModel):
    reason: str
    holds: bool


class OpenAIModel:
    def __init__(self, name: str):
        from langchain_openai import ChatOpenAI

        self.llm = ChatOpenAI(model=name)

    def _ask(self, schema: type[BaseModel], messages: list[dict]) -> BaseModel:
        return self.llm.with_structured_output(schema, strict=True).invoke(messages)

    def screen(self, piece, list_text, known_titles):
        out = self._ask(Screened, screen_messages(piece, list_text, known_titles))
        return [c.model_dump() for c in out.changes]

    def assess(self, change, row, files):
        data = {"change": change, "row": asdict(row), "files": files}
        return self._ask(Assessed, _messages("assess", data)).model_dump()

    def refute(self, finding, row, files):
        data = {"finding": finding, "row": asdict(row), "files": files}
        return not self._ask(Refuted, _messages("refute", data)).holds


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    inp = json.loads(Path(a.input).read_text(encoding="utf-8"))
    model = OpenAIModel(os.environ["WATCH_MODEL"])
    out = judge(inp, model, int(os.environ.get("MAX_MODEL_CALLS", MAX_MODEL_CALLS)))
    Path(a.out).write_text(json.dumps(out, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
