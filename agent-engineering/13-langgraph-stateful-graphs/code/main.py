from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from typing import Any, Callable, Iterator

State = dict[str, Any]
Update = dict[str, Any]
START = "__start__"
END = "__end__"


def append_reducer(current: list[Any] | None, update: list[Any]) -> list[Any]:
    return (current or []) + update


def replace_reducer(current: Any, update: Any) -> Any:
    return update


@dataclass
class Interrupt(Exception):
    node: str
    question: str


@dataclass
class Command:
    resume: Any


class SqliteCheckpointer:
    def __init__(self) -> None:
        self.db = sqlite3.connect(":memory:")
        self.db.execute(
            "CREATE TABLE checkpoints (thread TEXT, seq INTEGER, node TEXT, next TEXT, state TEXT, PRIMARY KEY (thread, seq))"
        )

    def put(self, thread: str, node: str, next_node: str, state: State) -> int:
        row = self.db.execute("SELECT COALESCE(MAX(seq), 0) FROM checkpoints WHERE thread = ?", (thread,)).fetchone()
        seq = row[0] + 1
        self.db.execute("INSERT INTO checkpoints VALUES (?, ?, ?, ?, ?)", (thread, seq, node, next_node, json.dumps(state)))
        return seq

    def latest(self, thread: str) -> tuple[int, str, str, State] | None:
        row = self.db.execute(
            "SELECT seq, node, next, state FROM checkpoints WHERE thread = ? ORDER BY seq DESC LIMIT 1", (thread,)
        ).fetchone()
        return None if row is None else (row[0], row[1], row[2], json.loads(row[3]))

    def get(self, thread: str, seq: int) -> tuple[int, str, str, State]:
        row = self.db.execute(
            "SELECT seq, node, next, state FROM checkpoints WHERE thread = ? AND seq = ?", (thread, seq)
        ).fetchone()
        return row[0], row[1], row[2], json.loads(row[3])

    def history(self, thread: str) -> list[tuple[int, str, str]]:
        return self.db.execute("SELECT seq, node, next FROM checkpoints WHERE thread = ? ORDER BY seq", (thread,)).fetchall()


@dataclass
class StateGraph:
    reducers: dict[str, Callable[[Any, Any], Any]]
    nodes: dict[str, Callable[[State], Update]] = field(default_factory=dict)
    edges: dict[str, Callable[[State], str]] = field(default_factory=dict)

    def add_node(self, name: str, fn: Callable[[State], Update]) -> None:
        self.nodes[name] = fn

    def add_edge(self, src: str, dst: str) -> None:
        self.edges[src] = lambda state: dst

    def add_conditional_edges(self, src: str, router: Callable[[State], str], mapping: dict[str, str]) -> None:
        self.edges[src] = lambda state: mapping[router(state)]

    def merge(self, state: State, update: Update) -> State:
        merged = dict(state)
        for key, value in update.items():
            reducer = self.reducers.get(key, replace_reducer)
            merged[key] = reducer(merged.get(key), value)
        return merged

    def compile(self, checkpointer: SqliteCheckpointer) -> "CompiledGraph":
        return CompiledGraph(self, checkpointer)


@dataclass
class CompiledGraph:
    graph: StateGraph
    checkpointer: SqliteCheckpointer
    executions: dict[str, int] = field(default_factory=dict)
    max_steps: int = 20

    def stream(self, thread: str, inputs: State | Command | None = None, from_seq: int | None = None) -> Iterator[tuple[str, Update]]:
        if from_seq is not None:
            _, _, node, state = self.checkpointer.get(thread, from_seq)
        else:
            saved = self.checkpointer.latest(thread)
            if saved is None:
                state, node = {}, self.graph.edges[START]({})
            else:
                _, _, node, state = saved
        resume_value = None
        if isinstance(inputs, Command):
            resume_value = inputs.resume
        elif inputs:
            state = self.graph.merge(state, inputs)
        for _ in range(self.max_steps):
            if node == END:
                return
            self.executions[node] = self.executions.get(node, 0) + 1
            if resume_value is not None:
                state = self.graph.merge(state, {"resume": resume_value})
                resume_value = None
            try:
                update = self.graph.nodes[node](state)
            except Interrupt as pause:
                self.checkpointer.put(thread, f"{node}:interrupt", node, state)
                yield "__interrupt__", {"node": pause.node, "question": pause.question}
                return
            state = self.graph.merge(state, update)
            next_node = self.graph.edges[node](state)
            self.checkpointer.put(thread, node, next_node, state)
            yield node, update
            node = next_node
        raise RuntimeError("step budget exceeded")


FLAKY = {"remaining_failures": 1}


def classify(state: State) -> Update:
    text = state["ticket"].lower()
    route = "refund" if "refund" in text or "charged" in text else "bug" if "crash" in text else "sales"
    return {"route": route, "log": [f"classified as {route}"]}


def draft_refund(state: State) -> Update:
    return {"draft": "Refund of $40 approved for duplicate charge.", "log": ["drafted refund"]}


def draft_bug(state: State) -> Update:
    if FLAKY["remaining_failures"] > 0:
        FLAKY["remaining_failures"] -= 1
        raise ConnectionError("issue tracker timed out")
    return {"draft": "Bug BUG-118 filed with stack trace.", "log": ["drafted bug"]}


def draft_sales(state: State) -> Update:
    return {"draft": "Quote for 50 seats sent.", "log": ["drafted quote"]}


def human_review(state: State) -> Update:
    if "resume" not in state:
        raise Interrupt("human_review", f"approve? {state['draft']}")
    decision = state["resume"]
    return {"approved": decision == "approve", "log": [f"human said {decision}"]}


def send(state: State) -> Update:
    outcome = "sent" if state.get("approved") else "discarded"
    return {"output": f"{outcome}: {state['draft']}", "log": [outcome]}


def build() -> StateGraph:
    graph = StateGraph(reducers={"log": append_reducer})
    for name, fn in [("classify", classify), ("refund", draft_refund), ("bug", draft_bug), ("sales", draft_sales), ("human_review", human_review), ("send", send)]:
        graph.add_node(name, fn)
    graph.add_edge(START, "classify")
    graph.add_conditional_edges("classify", lambda s: s["route"], {"refund": "refund", "bug": "bug", "sales": "sales"})
    for branch in ("refund", "bug", "sales"):
        graph.add_edge(branch, "human_review")
    graph.add_edge("human_review", "send")
    graph.add_edge("send", END)
    return graph


def run_and_print(app: CompiledGraph, thread: str, inputs: State | Command | None, from_seq: int | None = None) -> None:
    try:
        for node, update in app.stream(thread, inputs, from_seq):
            print(f"  stream {node:<14} {json.dumps(update)}")
    except ConnectionError as error:
        print(f"  crash: {error} (state up to the last node is checkpointed)")


def main() -> None:
    checkpointer = SqliteCheckpointer()
    app = build().compile(checkpointer)

    print("1. refund ticket runs until the human interrupt")
    run_and_print(app, "t-refund", {"ticket": "I was charged twice, please refund"})

    print("\n2. resume the same thread with Command(resume='approve')")
    run_and_print(app, "t-refund", Command(resume="approve"))
    print(f"  final output: {checkpointer.latest('t-refund')[3]['output']}")

    print("\n3. bug ticket crashes mid-graph, then resumes from the checkpoint")
    run_and_print(app, "t-bug", {"ticket": "CLI crash on ctrl-c"})
    run_and_print(app, "t-bug", None)
    run_and_print(app, "t-bug", Command(resume="approve"))
    print(f"  node executions so far: {app.executions}")

    print("\n4. checkpoint history for t-refund")
    for seq, node, next_node in checkpointer.history("t-refund"):
        print(f"  seq={seq} node={node:<24} next={next_node}")

    print("\n5. time travel: fork t-refund from the interrupt checkpoint and reject instead")
    interrupt_seq = next(seq for seq, node, _ in checkpointer.history("t-refund") if node.endswith(":interrupt"))
    run_and_print(app, "t-refund", Command(resume="reject"), from_seq=interrupt_seq)
    print(f"  forked output: {checkpointer.latest('t-refund')[3]['output']}")
    print(f"  full log: {checkpointer.latest('t-refund')[3]['log']}")

    print("\nstate is checkpointed after every node: crash, pause and fork all resume exactly.")


if __name__ == "__main__":
    main()
