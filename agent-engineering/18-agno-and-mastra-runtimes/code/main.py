from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Iterator


class SessionDb:
    def __init__(self) -> None:
        self.conn = sqlite3.connect(":memory:", check_same_thread=False)
        self.conn.execute("CREATE TABLE runs (session_id TEXT, turn INTEGER, role TEXT, content TEXT)")

    def history(self, session_id: str) -> list[tuple[str, str]]:
        rows = self.conn.execute("SELECT role, content FROM runs WHERE session_id = ? ORDER BY turn", (session_id,))
        return list(rows)

    def append(self, session_id: str, role: str, content: str) -> None:
        turn = len(self.history(session_id))
        self.conn.execute("INSERT INTO runs VALUES (?, ?, ?, ?)", (session_id, turn, role, content))


def lookup_order(order_id: str) -> str:
    return {"A1": "shipped", "B2": "delayed"}.get(order_id, "unknown")


@dataclass
class PyAgent:
    model: str
    instructions: str
    tools: tuple[Callable[..., str], ...]
    db: SessionDb

    def run_stream(self, message: str, session_id: str) -> Iterator[str]:
        past = self.db.history(session_id)
        self.db.append(session_id, "user", message)
        order_id = next((w for w in message.split() if w[:1].isupper() and w[1:].isdigit()), None)
        if order_id is None:
            remembered = [c for r, c in past if r == "assistant" and "order" in c]
            answer = f"Earlier you asked about: {remembered[-1]}" if remembered else "Which order?"
        else:
            yield f"tool_call lookup_order({order_id})"
            answer = f"order {order_id} is {self.tools[0](order_id)}"
        for word in answer.split():
            yield f"delta {word}"
        self.db.append(session_id, "assistant", answer)
        yield f"completed history_len={len(self.db.history(session_id))}"


def stateless_endpoint(db: SessionDb, worker: str) -> Callable[[dict[str, str]], list[str]]:
    def handle(request: dict[str, str]) -> list[str]:
        agent = PyAgent("openai:gpt-6-luna", "Answer order questions.", (lookup_order,), db)
        return [f"[{worker}] {event}" for event in agent.run_stream(request["message"], request["session_id"])]
    return handle


def check_schema(schema: dict[str, type], data: dict[str, Any], where: str) -> None:
    for key, expected in schema.items():
        if not isinstance(data.get(key), expected):
            raise TypeError(f"{where}: field {key!r} must be {expected.__name__}, got {data.get(key)!r}")


@dataclass
class Step:
    step_id: str
    input_schema: dict[str, type]
    output_schema: dict[str, type]
    execute: Callable[[dict[str, Any], dict[str, Any]], dict[str, Any] | None]


@dataclass
class Workflow:
    workflow_id: str
    plan: list[Any] = field(default_factory=list)
    snapshots: dict[str, dict[str, Any]] = field(default_factory=dict)

    def then(self, step: Step) -> "Workflow":
        self.plan.append(step)
        return self

    def branch(self, routes: list[tuple[Callable[[dict[str, Any]], bool], Step]]) -> "Workflow":
        self.plan.append(routes)
        return self

    def start(self, run_id: str, data: dict[str, Any], resume: dict[str, Any] | None = None, at: int = 0) -> dict[str, Any]:
        for index in range(at, len(self.plan)):
            item = self.plan[index]
            step = item if isinstance(item, Step) else next(s for cond, s in item if cond(data))
            check_schema(step.input_schema, data, f"{step.step_id}.input")
            output = step.execute(data, resume or {})
            resume = None
            if output is None:
                self.snapshots[run_id] = {"at": index, "data": data, "step": step.step_id}
                return {"status": "suspended", "step": step.step_id}
            check_schema(step.output_schema, output, f"{step.step_id}.output")
            print(f"    step {step.step_id:<14} -> {json.dumps(output)}")
            data = output
        return {"status": "success", "result": data}

    def resume(self, run_id: str, resume_data: dict[str, Any]) -> dict[str, Any]:
        saved = self.snapshots.pop(run_id)
        return self.start(run_id, saved["data"], resume_data, saved["at"])


def route_model(spec: str, healthy: set[str], fallbacks: list[str]) -> str:
    for candidate in [spec] + fallbacks:
        provider = candidate.split("/", 1)[0]
        if provider in healthy:
            return candidate
    raise RuntimeError("no healthy provider")


classify = Step("classify", {"text": str}, {"text": str, "amount": int},
                lambda d, r: {"text": d["text"], "amount": int("".join(c for c in d["text"] if c.isdigit()) or 0)})
auto_refund = Step("auto_approve", {"amount": int}, {"amount": int, "approved": bool},
                   lambda d, r: {"amount": d["amount"], "approved": True})
approval = Step("human_approval", {"amount": int}, {"amount": int, "approved": bool},
                lambda d, r: None if "approved" not in r else {"amount": d["amount"], "approved": r["approved"]})
settle = Step("settle", {"approved": bool}, {"status": str},
              lambda d, r: {"status": f"refund ${d['amount']} {'paid' if d['approved'] else 'declined'}"})
broken = Step("broken_settle", {"approved": bool}, {"status": str}, lambda d, r: {"status": 42})


def main() -> None:
    print("1. Python runtime shape: a fresh agent per request, history in a database")
    db = SessionDb()
    worker_a, worker_b = stateless_endpoint(db, "worker-a"), stateless_endpoint(db, "worker-b")
    for line in worker_a({"session_id": "s1", "message": "Where is order B2 ?"}):
        print(f"    {line}")
    for line in worker_b({"session_id": "s1", "message": "and what did I ask before?"}):
        print(f"    {line}")

    started = time.perf_counter()
    agents = [PyAgent("openai:gpt-6-luna", "x", (lookup_order,), db) for _ in range(10_000)]
    per_agent_ms = (time.perf_counter() - started) * 1000 / len(agents)
    print(f"    10k agent objects built; per-agent cost under 1 ms: {per_agent_ms < 1.0} (a model call is ~100s of ms)")

    print("\n2. TypeScript runtime shape: typed steps, branch, suspend and resume")
    refunds = Workflow("refunds").then(classify).branch([
        (lambda d: d["amount"] <= 50, auto_refund),
        (lambda d: d["amount"] > 50, approval),
    ]).then(settle)
    print(f"    small: {refunds.start('r1', {'text': 'refund 30 dollars'})}")
    paused = refunds.start("r2", {"text": "refund 400 dollars"})
    print(f"    large: {paused}  snapshot={refunds.snapshots['r2']}")
    print(f"    resumed: {refunds.resume('r2', {'approved': True})}")

    print("\n3. schema validation catches a bad step output at the boundary")
    strict = Workflow("strict").then(classify).then(Step("force", {"amount": int}, {"amount": int, "approved": bool}, lambda d, r: {"amount": d["amount"], "approved": True})).then(broken)
    try:
        strict.start("r3", {"text": "refund 10"})
    except TypeError as error:
        print(f"    rejected: {error}")

    print("\n4. model router: provider/model strings with fallbacks")
    print(f"    all healthy    -> {route_model('openai/gpt-6.1-sol', {'openai', 'google'}, ['google/gemini-3.8-flash'])}")
    print(f"    openai is down -> {route_model('openai/gpt-6.1-sol', {'google'}, ['google/gemini-3.8-flash'])}")
    print("\nsame job, two shapes: per-request Python agents with a session DB, or typed TS-style workflows.")


if __name__ == "__main__":
    main()
