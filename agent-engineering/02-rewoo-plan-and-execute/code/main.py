from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Callable

REFERENCE = re.compile(r"#E(\d+)")


@dataclass(frozen=True)
class Step:
    step_id: str
    tool: str
    args: dict[str, str]

    def depends_on(self) -> set[str]:
        return {f"E{n}" for n in REFERENCE.findall(" ".join(self.args.values()))}


@dataclass
class Plan:
    steps: list[Step]


def validate_plan(plan: Plan, tools: dict[str, Callable[..., str]]) -> list[str]:
    problems: list[str] = []
    ids = [s.step_id for s in plan.steps]
    if len(ids) != len(set(ids)):
        problems.append("duplicate step ids")
    for step in plan.steps:
        if step.tool not in tools:
            problems.append(f"{step.step_id}: unknown tool {step.tool!r}")
        for ref in step.depends_on() - set(ids):
            problems.append(f"{step.step_id}: reference to missing step {ref}")
        if step.step_id in step.depends_on():
            problems.append(f"{step.step_id}: references itself")
    return problems


def levels(plan: Plan) -> list[list[Step]]:
    done: set[str] = set()
    pending = list(plan.steps)
    layers: list[list[Step]] = []
    while pending:
        ready = [s for s in pending if s.depends_on() <= done]
        if not ready:
            raise ValueError("cycle detected in plan")
        layers.append(ready)
        done |= {s.step_id for s in ready}
        pending = [s for s in pending if s not in ready]
    return layers


def bind(args: dict[str, str], evidence: dict[str, str]) -> dict[str, str]:
    return {k: REFERENCE.sub(lambda m: evidence.get(f"E{m.group(1)}", m.group(0)), v) for k, v in args.items()}


def call_tool(tools: dict[str, Callable[..., str]], step: Step, evidence: dict[str, str]) -> str:
    failed = sorted(d for d in step.depends_on() if evidence.get(d, "").startswith("error:"))
    if failed:
        return f"error: skipped because upstream {failed} failed"
    try:
        return tools[step.tool](**bind(step.args, evidence))
    except Exception as error:
        return f"error: {type(error).__name__}: {error}"


def run_workers(plan: Plan, tools: dict[str, Callable[..., str]]) -> tuple[dict[str, str], list[list[str]]]:
    evidence: dict[str, str] = {}
    schedule: list[list[str]] = []
    with ThreadPoolExecutor(max_workers=4) as pool:
        for layer in levels(plan):
            schedule.append([s.step_id for s in layer])
            outputs = list(pool.map(lambda s: call_tool(tools, s, evidence), layer))
            for step, output in zip(layer, outputs):
                evidence[step.step_id] = output
    return evidence, schedule


FACTS = {
    "capital of france": "Paris",
    "capital of germany": "Berlin",
    "population of paris": "11.2 million (metro)",
    "population of berlin": "3.9 million (city)",
}


def search(query: str) -> str:
    key = query.lower().strip()
    if key not in FACTS:
        raise LookupError(f"no result for {query!r}")
    return FACTS[key]


def round_millions(text: str) -> str:
    match = re.search(r"\d+(\.\d+)?", text)
    if not match:
        raise ValueError(f"no number in {text!r}")
    return f"{round(float(match.group()))} million"


def compare(a: str, b: str) -> str:
    left, right = float(a.split()[0]), float(b.split()[0])
    return f"{'first' if left > right else 'second'} is larger by {abs(left - right):g} million"


SYSTEM_AND_TOOLS = 400
TOOLS: dict[str, Callable[..., str]] = {"search": search, "round_millions": round_millions, "compare": compare}


@dataclass
class Ledger:
    planner: int = 0
    workers: int = 0
    solver: int = 0
    notes: list[str] = field(default_factory=list)

    def model_chars(self) -> int:
        return self.planner + self.solver


def plan_size(plan: Plan) -> int:
    return sum(len(s.tool) + len(str(s.args)) for s in plan.steps)


def rewoo(question: str, plan: Plan, solve: Callable[[dict[str, str]], str]) -> tuple[str, Ledger, list[list[str]]]:
    problems = validate_plan(plan, TOOLS)
    if problems:
        raise ValueError("; ".join(problems))
    ledger = Ledger(planner=SYSTEM_AND_TOOLS + len(question) + plan_size(plan))
    evidence, schedule = run_workers(plan, TOOLS)
    ledger.workers = sum(len(str(s.args)) + len(evidence[s.step_id]) for s in plan.steps)
    answer = solve(evidence)
    ledger.solver = SYSTEM_AND_TOOLS + len(question) + plan_size(plan) + sum(len(v) for v in evidence.values()) + len(answer)
    return answer, ledger, schedule


def react_cost(question: str, trajectory: list[tuple[str, dict[str, str]]]) -> int:
    system_and_tools = SYSTEM_AND_TOOLS
    history = 0
    total = 0
    for name, args in trajectory:
        total += system_and_tools + len(question) + history
        observation = TOOLS[name](**args)
        history += len(name) + len(str(args)) + len(observation) + 60
    return total + system_and_tools + len(question) + history


def plan_and_execute(question: str, plan: Plan, replan: Callable[[Plan, dict[str, str]], Plan]) -> tuple[dict[str, str], int]:
    rounds = 0
    while True:
        rounds += 1
        evidence, _ = run_workers(plan, TOOLS)
        failed = [k for k, v in evidence.items() if v.startswith("error:")]
        if not failed or rounds >= 3:
            return evidence, rounds
        plan = replan(plan, evidence)


def main() -> None:
    print("=" * 72)
    print("LESSON 02 - ReWOO and Plan-and-Execute")
    print("=" * 72)
    question = "Which capital is bigger, France's or Germany's, in rounded millions?"
    plan = Plan([
        Step("E1", "search", {"query": "capital of France"}),
        Step("E2", "search", {"query": "capital of Germany"}),
        Step("E3", "search", {"query": "population of #E1"}),
        Step("E4", "search", {"query": "population of #E2"}),
        Step("E5", "round_millions", {"text": "#E3"}),
        Step("E6", "round_millions", {"text": "#E4"}),
        Step("E7", "compare", {"a": "#E5", "b": "#E6"}),
    ])
    answer, ledger, schedule = rewoo(
        question, plan,
        lambda ev: f"{ev['E1']} ({ev['E5']}) vs {ev['E2']} ({ev['E6']}): {ev['E7']}.",
    )
    print("\nPLAN (one planner call, no observations seen)")
    for step in plan.steps:
        print(f"  {step.step_id}: {step.tool}({step.args})")
    print("\nEXECUTION LAYERS (steps in a layer run in parallel)")
    for depth, layer in enumerate(schedule, 1):
        print(f"  layer {depth}: {layer}")
    print(f"\nANSWER: {answer}")

    trajectory = [
        ("search", {"query": "capital of France"}), ("search", {"query": "capital of Germany"}),
        ("search", {"query": "population of Paris"}), ("search", {"query": "population of Berlin"}),
        ("round_millions", {"text": "11.2 million"}), ("round_millions", {"text": "3.9 million"}),
        ("compare", {"a": "11 million", "b": "4 million"}),
    ]
    react = react_cost(question, trajectory)
    print("\nPROMPT-SIZE INTUITION (characters sent to the model, toy accounting)")
    print(f"  ReAct, 8 model calls re-reading history : {react}")
    print(f"  ReWOO, 2 model calls (planner + solver) : {ledger.model_chars()}")
    print(f"  ratio                                   : {react / ledger.model_chars():.1f}x")

    print("\nVALIDATION catches bad plans before any tool runs")
    bad = Plan([Step("E1", "serch", {"query": "x"}), Step("E2", "search", {"query": "#E9"})])
    for problem in validate_plan(bad, TOOLS):
        print(f"  rejected: {problem}")

    print("\nPLAN-AND-EXECUTE: a replanner fixes a failed node")
    fragile = Plan([Step("E1", "search", {"query": "capital of Frnace"}), Step("E2", "search", {"query": "population of #E1"})])

    def replan(old: Plan, evidence: dict[str, str]) -> Plan:
        print(f"  replanner saw: {evidence}")
        return Plan([Step("E1", "search", {"query": "capital of France"}), old.steps[1]])

    evidence, rounds = plan_and_execute("population of France's capital", fragile, replan)
    print(f"  after {rounds} rounds: {evidence}")


if __name__ == "__main__":
    main()
