"""Judge what is new in the clients with a small LangGraph graph and write the findings."""

import argparse
import json
import os
import re
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
SCREENS = 2  # each part is screened twice: the model misses a row now and then, not twice
PROMPTS = Path(__file__).resolve().parent.parent / "prompts"
DISAGREED = " A second look disagreed."
GRAVE = ("breaks", "wrong-data")
NOTHING = {"", "nothing", "none", "n/a", "-"}
MARKS = str.maketrans({c: None for c in "`'\"\u2018\u2019\u201c\u201d"})


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


def _plain(text: str) -> str:
    text = text.translate(MARKS).replace("\u2014", "-").replace("\u2013", "-").lower()
    return " ".join(text.split())


def quoted(quote: str, text: str) -> bool:
    """True when the quote is in the text: every bit of it between "..." marks, ignoring case,
    spacing, quote marks and backticks. A change whose quote is not there is not trusted."""
    bits = [_plain(b).strip(" .") for b in re.split(r"\.\.\.|\u2026", quote)]
    bits = [b for b in bits if b]
    plain = _plain(text)
    return bool(bits) and all(b in plain for b in bits)


def _full(state: State, cost: int = 1) -> bool:
    return state["calls"] + cost > state["max_calls"]


class _Failed(Exception):
    pass


def _call(piece_id: str, fn, *args):
    try:
        with watch_trace.piece(piece_id):
            return fn(*args)
    except Exception as e:  # noqa: BLE001 - a failed call skips its piece, the run goes on
        print(f"model call failed for {piece_id}: {type(e).__name__}", file=sys.stderr)
        raise _Failed from None


def _stops(node, late, cost=1):
    def run(state: State) -> dict:
        if _full(state, cost) or late():
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


def _join(to_assess: list[dict], change: dict) -> list[dict]:
    """One change a row and piece: a row touched again (in a later part) joins the first."""
    for n, old in enumerate(to_assess):
        if old["row"] == change["row"]:
            both = {k: f"{old.get(k, '')}\n{change.get(k, '')}".strip()
                    for k in ("changed", "quote")}
            return [*to_assess[:n], {**old, **both}, *to_assess[n + 1:]]
    return [*to_assess, change]


def build_graph(model: Model, late=lambda: False):
    def settle(state: State, update: dict, cost: int = 1) -> dict:
        new = {**state, **update, "calls": state["calls"] + cost}
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
        changes, seen = [], set()
        for _ in range(SCREENS):
            changes += _call(piece["id"], model.screen, part, inp["list"], titles)
        for change in changes:
            label = change.get("row", "none")
            if not quoted(change.get("quote", ""), part["text"]):
                continue
            # The screens are joined: a row once, a gap once for each sentence it rests on.
            same = (label, _plain(change["quote"]) if label == "gap" else "")
            if same in seen:
                continue
            seen.add(same)
            if label == "gap":
                current.append(_finding(inp, piece, "", None, effect="gap",
                                        systems="not checked", **{
                                            k: change.get(k, "") for k in
                                            ("title", "changed", "user_gets", "why")},
                                        sure=change.get("sure", False)))
            elif (piece["client"], label) in rows:
                to_assess = _join(to_assess, {**change, "row": label})
        if state["part"] + 1 < len(parts):  # more of this piece to read before the next step
            return {"current": current, "to_assess": to_assess, "part": state["part"] + 1,
                    "calls": state["calls"] + SCREENS}
        return settle(state, {"current": current, "to_assess": to_assess, "to_refute": [],
                              "part": 0}, SCREENS)

    def assess(state: State) -> dict:
        inp = state["inp"]
        piece = inp["pieces"][state["i"]]
        change, *rest = state["to_assess"]
        row = _rows(inp["list"])[(piece["client"], change["row"])]
        got = _call(piece["id"], model.assess, change, row, _files(row, inp))
        effect, sure = got.get("effect", ""), got.get("sure", False)
        if effect in GRAVE and got.get("shown_wrong", "").strip(" .").lower() in NOTHING:
            effect, sure = "minor", False  # a break or wrong data names what Kitden gets wrong
        f = _finding(inp, piece, change["row"], row, changed=change.get("changed", ""),
                     effect=effect, sure=sure,
                     **{k: got.get(k, "") for k in ("title", "user_gets", "systems", "why")})
        update = {"to_assess": rest}
        if f["effect"] == "none":  # the code shows Kitden is not touched: no finding
            pass
        elif f["effect"] in GRAVE and f["sure"]:
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
    graph.add_node("screen", _stops(screen, late, SCREENS))
    graph.add_node("assess", _stops(assess, late))
    graph.add_node("refute", _stops(refute, late))
    graph.add_conditional_edges(START, after)
    for node in ("screen", "assess", "refute"):
        graph.add_conditional_edges(node, after)
    return graph.compile()


def _seconds(name: str, default: int) -> int:
    return int(os.environ.get(name) or default)


def judge(inp: dict, model: Model, max_calls: int = MAX_MODEL_CALLS,
          deadline: float | None = None, clock=time.monotonic) -> dict:
    # WATCH_DEADLINE_SECONDS gives a slow setting (a high effort) more time than the default.
    if deadline is None:
        deadline = _seconds("WATCH_DEADLINE_SECONDS", DEADLINE_SECONDS)
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
    rows = [i for i, (client, _) in row_ids(list_text).items() if client == piece["client"]]
    data = {"piece": {k: piece[k] for k in ("client", "kind", "version", "url", "text")},
            "rows_to_check": rows, "known_titles": known_titles}
    return [{"role": "system", "content": _prompt("screen") + short_list(list_text)},
            {"role": "user", "content": json.dumps(data, indent=1)}]


def _messages(name: str, data: dict) -> list[dict]:
    return [{"role": "system", "content": _prompt(name)},
            {"role": "user", "content": json.dumps(data, indent=1)}]


# The fields come in the order the model should think: the quote before the verdict.
class RowCheck(BaseModel):
    row: str
    quote: str
    touched: bool
    title: str
    changed: str


class Gap(BaseModel):
    quote: str
    title: str
    changed: str
    user_gets: str
    why: str
    sure: bool


class Screened(BaseModel):
    rows: list[RowCheck]
    gaps: list[Gap]


class Assessed(BaseModel):
    kitden_reads: str
    client_now: str
    shown_wrong: str
    effect: Literal["breaks", "wrong-data", "minor", "none"]
    sure: bool
    user_gets: str
    systems: str
    why: str
    title: str


class Refuted(BaseModel):
    reason: str
    holds: bool


def named(screened: Screened, client: str, list_text: str) -> list[dict]:
    """The model checks the rows by their short ids; the graph wants a change for each touched
    row, under the row's label, and one for each gap. An id that is not a row of the piece's
    client is dropped."""
    ids = row_ids(list_text)
    out = []
    for check in screened.rows:
        row_client, label = ids.get(check.row.strip(), ("", ""))
        if check.touched and row_client == client:
            out.append({"row": label, "quote": check.quote, "title": check.title,
                        "changed": check.changed, "user_gets": "", "why": "", "sure": False})
    return out + [{"row": "gap", **gap.model_dump()} for gap in screened.gaps]


class OpenAIModel:
    def __init__(self, name: str):
        from langchain_openai import ChatOpenAI

        # WATCH_EFFORT is how hard the model thinks (low, medium, high, xhigh, max); unset or
        # empty leaves the model's own default. The name in the traces carries it.
        effort = os.environ.get("WATCH_EFFORT") or None
        self.name = f"{name} {effort}" if effort else name
        # A long piece takes the model a minute or two, so one call may wait three;
        # WATCH_CALL_SECONDS gives a slow setting more.
        self.llm = ChatOpenAI(model=name, reasoning_effort=effort, max_retries=1,
                              timeout=_seconds("WATCH_CALL_SECONDS", 180))

    def _ask(self, step: str, schema: type[BaseModel], messages: list[dict]) -> BaseModel:
        config = watch_trace.config(step, self.name)
        return self.llm.with_structured_output(schema, strict=True).invoke(messages, config)

    def screen(self, piece, list_text, known_titles):
        out = self._ask("screen", Screened, screen_messages(piece, list_text, known_titles))
        return named(out, piece["client"], list_text)

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
