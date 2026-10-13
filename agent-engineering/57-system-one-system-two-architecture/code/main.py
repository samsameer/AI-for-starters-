from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Callable

LLM_MS, LLM_USD = 1800, 0.0040
S1_MS, S1_USD = 40, 0.000015


@dataclass
class Ledger:
    ms: float = 0.0
    usd: float = 0.0
    llm_calls: int = 0
    s1_calls: int = 0
    events: list[str] = field(default_factory=list)

    def llm(self, why: str) -> None:
        self.ms += LLM_MS
        self.usd += LLM_USD
        self.llm_calls += 1
        self.events.append(f"LLM  {why}")

    def s1(self, why: str) -> None:
        self.ms += S1_MS
        self.usd += S1_USD
        self.s1_calls += 1
        self.events.append(f"S1   {why}")


def words(x: Any) -> set[str]:
    return set(re.findall(r"[a-z]+", json.dumps(x).lower()))


class SystemOne:
    def __init__(self, ledger: Ledger) -> None:
        self.ledger = ledger

    def ask(self, state: Any, questions: dict[str, dict[str, Any]]) -> dict[str, Any]:
        self.ledger.s1(", ".join(questions))
        w = words(state)
        out: dict[str, Any] = {}
        for qid, q in questions.items():
            if q["type"] == "choice":
                scores = {k: len(w & words(v)) + 0.01 for k, v in q["criteria"].items()}
                total = sum(scores.values())
                probs = {k: s / total for k, s in scores.items()}
                best = max(probs, key=probs.get)
                out[qid] = {"choice": best, "confidence": probs[best], "probabilities": probs}
            elif q["type"] == "noul":
                pos, neg = words(q.get("yes", "")), words(q.get("no", ""))
                a, b = len(w & pos), len(w & neg)
                out[qid] = {"noul": (a + 0.5) / (a + b + 1.0)}
            else:
                hits = len(w & words(q.get("signal", "")))
                n = len(q["criteria"]) - 1
                out[qid] = {"score": float(min(n, hits))}
        return out


class SystemTwo:
    def __init__(self, ledger: Ledger) -> None:
        self.ledger = ledger

    def plan(self, task: str, specialist: str) -> list[tuple[str, dict[str, Any]]]:
        self.ledger.llm(f"plan as {specialist}")
        if specialist == "data":
            return [("sql", {"q": "select region, sum(amount) from orders group by region"}), ("chart", {"kind": "bar"})]
        if specialist == "ops":
            return [("logs", {"service": "checkout"}), ("restart", {"service": "checkout", "env": "prod"})]
        return [("search", {"q": task})]

    def write(self, task: str, observations: list[str]) -> str:
        self.ledger.llm("write answer")
        return f"Answer to '{task}': " + "; ".join(observations)


TOOLS: dict[str, Callable[..., str]] = {
    "sql": lambda q: "north=120 south=80 total revenue",
    "chart": lambda kind: f"{kind} chart rendered",
    "logs": lambda service: f"{service}: 500 errors since 09:00",
    "restart": lambda service, env: f"{service} restarted in {env}",
    "search": lambda q: f"3 docs about {q}",
}

ROUTE = {
    "specialist": {
        "type": "choice",
        "criteria": {
            "data": "revenue sales orders region chart report numbers",
            "ops": "outage errors down checkout failing latency incident",
            "research": "what why explain compare docs policy",
        },
    }
}


def hybrid_agent(task: str, approve: Callable[[str], bool]) -> tuple[str, Ledger]:
    ledger = Ledger()
    s1, s2 = SystemOne(ledger), SystemTwo(ledger)
    route = s1.ask({"task": task}, ROUTE)["specialist"]
    if route["confidence"] < 0.45:
        ledger.events.append("HUMAN low routing confidence")
        return "escalated", ledger
    observations: list[str] = []
    for tool, args in s2.plan(task, route["choice"]):
        guard = s1.ask(
            {"task": task, "call": {"tool": tool, "args": args}},
            {
                "risky": {"type": "noul", "yes": "restart delete drop prod transfer", "no": "select sum chart search logs"},
                "blast": {"type": "score", "criteria": ["none", "one", "system", "many"], "signal": "prod restart delete all"},
            },
        )
        if guard["risky"]["noul"] >= 0.7 or guard["blast"]["score"] >= 2:
            if not approve(f"{tool}({args})"):
                ledger.events.append(f"HOLD {tool} denied by human")
                observations.append(f"{tool} skipped (needs approval)")
                continue
            ledger.events.append(f"HUMAN approved {tool}")
        observations.append(TOOLS[tool](**args))
        done = s1.ask({"task": task, "observations": observations}, {"done": {"type": "noul", "yes": "rendered restarted docs", "no": "errors skipped"}})
        if done["done"]["noul"] >= 0.75:
            ledger.events.append("STOP done-check passed")
            break
    answer = s2.write(task, observations)
    quality = s1.ask({"answer": answer}, {"q": {"type": "score", "criteria": ["bad", "ok", "good", "great"], "signal": "total chart restarted docs revenue"}})
    if quality["q"]["score"] < 1:
        answer = s2.write(task, observations + ["revise for completeness"])
    return answer, ledger


def llm_only_agent(task: str) -> tuple[str, Ledger]:
    ledger = Ledger()
    s2 = SystemTwo(ledger)
    ledger.llm("route via JSON prompt")
    specialist = "data" if "revenue" in task.lower() else "ops" if "checkout" in task.lower() else "research"
    observations: list[str] = []
    for tool, args in s2.plan(task, specialist):
        ledger.llm(f"judge safety of {tool}")
        observations.append(TOOLS[tool](**args))
        ledger.llm("judge done")
    answer = s2.write(task, observations)
    ledger.llm("judge quality")
    return answer, ledger


def main() -> None:
    tasks = [
        "Show revenue by region as a chart",
        "Checkout is failing with errors, fix the outage",
        "Explain our refund policy",
    ]
    rows = []
    for task in tasks:
        a1, l1 = hybrid_agent(task, approve=lambda call: False)
        a2, l2 = llm_only_agent(task)
        print(f"\n=== {task}")
        for e in l1.events:
            print("   ", e)
        print(f"    hybrid  : {a1}")
        print(f"    llm-only: {a2}")
        rows.append((task[:34], l1, l2))
    print(f"\n{'task':<36}{'hybrid ms':>10}{'llm ms':>9}{'hybrid $':>11}{'llm $':>9}")
    for name, l1, l2 in rows:
        print(f"{name:<36}{l1.ms:>10.0f}{l2.ms:>9.0f}{l1.usd:>11.4f}{l2.usd:>9.4f}")


if __name__ == "__main__":
    main()
