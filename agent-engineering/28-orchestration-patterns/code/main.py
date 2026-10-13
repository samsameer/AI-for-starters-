from __future__ import annotations

import json
import math
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Callable


ROUTES = {
    "refund": "refund money charged twice invoice payment",
    "bug": "crash error bug fails broken exception",
    "sales": "pricing quote volume plan seats discount",
}


def words(text: str) -> set[str]:
    return set(re.findall(r"[a-z]+", text.lower()))


def softmax(logits: dict[str, float]) -> dict[str, float]:
    top = max(logits.values())
    exp = {k: math.exp(v - top) for k, v in logits.items()}
    total = sum(exp.values())
    return {k: round(v / total, 3) for k, v in exp.items()}


def system_one_choice(state: str, labels: dict[str, str]) -> dict[str, object]:
    seen = words(state)
    logits = {label: 2.0 * len(seen & words(desc)) for label, desc in labels.items()}
    probs = softmax(logits)
    best = max(probs, key=probs.get)
    return {"choice": best, "confidence": probs[best], "probabilities": probs}


@dataclass
class Meter:
    llm_calls: int = 0
    decision_calls: int = 0
    hops: int = 0
    trace: list[str] = field(default_factory=list)

    def cost_units(self) -> float:
        return round(self.llm_calls * 1.0 + self.decision_calls * 0.05, 2)


def specialist(label: str, task: str, meter: Meter) -> str:
    meter.llm_calls += 1
    return {"refund": "refund issued", "bug": "bug filed", "sales": "quote sent", "human": "queued for a person"}[label] + f" ({task[:28]})"


def llm_route(task: str, meter: Meter) -> str:
    meter.llm_calls += 1
    return system_one_choice(task, ROUTES)["choice"]


def supervisor_llm(tasks: list[str]) -> Meter:
    meter = Meter()
    for task in tasks:
        label = llm_route(task, meter)
        meter.trace.append(f"supervisor(llm) -> {label}: {specialist(label, task, meter)}")
    return meter


def supervisor_system_one(tasks: list[str], threshold: float = 0.6) -> Meter:
    meter = Meter()
    for task in tasks:
        meter.decision_calls += 1
        verdict = system_one_choice(task, ROUTES)
        label = verdict["choice"] if verdict["confidence"] >= threshold else "human"
        meter.trace.append(f"supervisor(system-one p={verdict['confidence']}) -> {label}: {specialist(label, task, meter)}")
    return meter


PEER_GUESS = {"sales": "refund", "refund": "sales", "bug": "sales"}


def swarm(tasks: list[str], max_hops: int = 3, threshold: float = 0.6) -> Meter:
    meter = Meter()
    for task in tasks:
        current = "sales"
        visited = [current]
        while True:
            meter.llm_calls += 1
            verdict = system_one_choice(task, ROUTES)
            wanted = verdict["choice"] if verdict["confidence"] >= threshold else PEER_GUESS[current]
            if wanted == current:
                meter.trace.append(f"swarm[{current}] handles: {specialist(current, task, meter)}")
                break
            if wanted in visited or len(visited) > max_hops:
                meter.trace.append(f"swarm bounce detected {visited + [wanted]} -> human: {specialist('human', task, meter)}")
                break
            meter.hops += 1
            meter.trace.append(f"swarm[{current}] hands off -> {wanted}")
            visited.append(wanted)
            current = wanted
    return meter


def hierarchical(tasks: list[str]) -> Meter:
    meter = Meter()
    for task in tasks:
        label = llm_route(task, meter)
        division = "commercial" if label == "sales" else "customer_ops"
        meter.llm_calls += 1
        meter.hops += 2
        meter.trace.append(f"top -> {division} -> {label}: {specialist(label, task, meter)}")
    return meter


def debate(tasks: list[str], debaters: int = 3) -> Meter:
    meter = Meter()
    for task in tasks:
        votes = [llm_route(task, meter) for _ in range(debaters)]
        meter.llm_calls += 1
        winner = Counter(votes).most_common(1)[0][0]
        meter.trace.append(f"debate votes={votes} -> {winner}: {specialist(winner, task, meter)}")
    return meter


@dataclass(frozen=True)
class AgentCard:
    name: str
    url: str
    skills: tuple[str, ...]
    signed: bool


def a2a_send(card: AgentCard, task: str, task_id: str) -> dict[str, object]:
    if not card.signed:
        return {"id": task_id, "status": "rejected", "reason": "unsigned agent card"}
    request = {
        "jsonrpc": "2.0",
        "id": task_id,
        "method": "send-message",
        "params": {"message": {"role": "user", "parts": [{"kind": "text", "text": task}]}},
    }
    body = json.dumps(request)
    return {"id": task_id, "status": "completed", "agent": card.name, "bytes": len(body), "content_type": "application/a2a+json"}


def main() -> None:
    tasks = [
        "I was charged twice, please refund invoice 4711",
        "the CLI crashes with an exception on ctrl-c",
        "do you offer volume pricing for 200 seats",
        "hello, can someone call me back?",
    ]
    patterns: list[tuple[str, Callable[[list[str]], Meter]]] = [
        ("supervisor (LLM router)", supervisor_llm),
        ("supervisor (System One router)", supervisor_system_one),
        ("swarm (hop-limited)", swarm),
        ("hierarchical", hierarchical),
        ("debate", debate),
    ]
    summary = []
    for name, run in patterns:
        meter = run(tasks)
        print(f"\n--- {name} ---")
        for line in meter.trace:
            print(f"  {line}")
        summary.append((name, meter))

    print("\npattern                          llm  decide  hops  cost_units")
    for name, meter in summary:
        print(f"  {name:31} {meter.llm_calls:>3}  {meter.decision_calls:>6}  {meter.hops:>4}  {meter.cost_units():>10}")

    print("\nA2A v1.0-shaped call to a remote agent owned by another team:")
    partner = AgentCard("billing-partner", "https://partner.example/a2a", ("refunds",), signed=True)
    rogue = AgentCard("free-refunds", "https://unknown.example/a2a", ("refunds",), signed=False)
    for card in (partner, rogue):
        print(f"  {json.dumps(a2a_send(card, tasks[0], 'task-001'))}")


if __name__ == "__main__":
    main()
