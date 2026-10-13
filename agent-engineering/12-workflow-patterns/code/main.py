from __future__ import annotations

from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Callable


@dataclass
class ScriptedLLM:
    script: dict[str, str | list[str]]
    cursor: dict[str, int] = field(default_factory=dict)
    calls: list[str] = field(default_factory=list)

    def __call__(self, prompt: str) -> str:
        self.calls.append(prompt)
        value = self.script.get(prompt, f"[unscripted: {prompt}]")
        if isinstance(value, list):
            index = self.cursor.get(prompt, 0)
            self.cursor[prompt] = index + 1
            return value[index % len(value)]
        return value


def prompt_chain(text: str, llm: Callable[[str], str], steps: list[tuple[str, str]],
                 gate: Callable[[str, str], bool]) -> list[tuple[str, str]]:
    trace: list[tuple[str, str]] = []
    current = text
    for label, template in steps:
        current = llm(template.format(text=current))
        trace.append((label, current))
        if not gate(label, current):
            trace.append(("gate", f"stopped after {label}"))
            break
    return trace


def route(text: str, classify: Callable[[str], dict[str, float]],
          handlers: dict[str, Callable[[str], str]], threshold: float) -> tuple[str, float, str]:
    probabilities = classify(text)
    label = max(probabilities, key=probabilities.get)
    confidence = probabilities[label]
    if confidence < threshold or label not in handlers:
        return "human", confidence, "escalated to a human queue"
    return label, confidence, handlers[label](text)


def parallel_sections(sections: list[str], worker: Callable[[str], str]) -> list[str]:
    with ThreadPoolExecutor(max_workers=4) as pool:
        return list(pool.map(worker, sections))


def parallel_vote(prompt: str, llm: Callable[[str], str], voters: int, quorum: float) -> tuple[str, Counter]:
    votes = Counter(llm(prompt) for _ in range(voters))
    winner, count = votes.most_common(1)[0]
    if count / voters < quorum:
        return "no-consensus", votes
    return winner, votes


def orchestrator_workers(task: str, llm: Callable[[str], str],
                         workers: dict[str, Callable[[str], str]]) -> tuple[list[str], list[tuple[str, str]], str]:
    plan = [name.strip() for name in llm(f"plan subtasks: {task}").split(",")]
    results = [(name, workers[name](task)) for name in plan if name in workers]
    summary = llm("synthesize: " + " | ".join(out for _, out in results))
    return plan, results, summary


def evaluator_optimizer(task: str, propose: Callable[[str, str | None], str],
                        evaluate: Callable[[str], tuple[int, str]], max_rounds: int,
                        target: int) -> tuple[str, int, list[tuple[int, str, int, str]]]:
    best, best_score = "", -1
    feedback: str | None = None
    trace: list[tuple[int, str, int, str]] = []
    for round_number in range(1, max_rounds + 1):
        candidate = propose(task, feedback)
        score, critique = evaluate(candidate)
        trace.append((round_number, candidate, score, critique))
        if score > best_score:
            best, best_score = candidate, score
        if score >= target:
            break
        feedback = critique
    return best, best_score, trace


def build_llm() -> ScriptedLLM:
    return ScriptedLLM({
        "outline: agents vs workflows": "1) definitions 2) trade-offs 3) when to switch",
        "draft from outline: 1) definitions 2) trade-offs 3) when to switch": "Workflows fix the path in code; agents choose it at runtime. Start with workflows.",
        "translate to French: Workflows fix the path in code; agents choose it at runtime. Start with workflows.": "Les workflows fixent le chemin; les agents le choisissent.",
        "is the ship safe to sail?": ["yes", "yes", "no", "yes", "yes"],
        "is this migration reversible?": ["yes", "no", "no", "yes", "unsure"],
        "plan subtasks: review PR 42 (python, touches auth)": "python_review, security_review",
        "synthesize: python: 2 nits | security: token logged at INFO": "Block: token logged at INFO. Then fix 2 nits.",
        "propose: one-line definition of ReAct": "ReAct calls tools.",
        "propose: one-line definition of ReAct | fix: mention reasoning and observations": "ReAct interleaves reasoning, tool actions and observations.",
        "propose: one-line definition of ReAct | fix: add the stop condition": "ReAct interleaves reasoning, tool actions and observations until a stop condition.",
    })


def toy_classifier(text: str) -> dict[str, float]:
    lowered = text.lower()
    scores = {"refund": 0.1, "bug": 0.1, "sales": 0.1}
    for label, cues in {"refund": ("refund", "money back", "charged"), "bug": ("crash", "error", "500"), "sales": ("pricing", "quote", "seats")}.items():
        scores[label] += sum(0.4 for cue in cues if cue in lowered)
    total = sum(scores.values())
    return {label: round(value / total, 3) for label, value in scores.items()}


def rubric(candidate: str) -> tuple[int, str]:
    lowered = candidate.lower()
    if "reasoning" not in lowered or "observation" not in lowered:
        return 1, "mention reasoning and observations"
    if "stop" not in lowered:
        return 2, "add the stop condition"
    return 3, "ok"


def main() -> None:
    llm = build_llm()
    cost: dict[str, int] = {}

    def measure(name: str, start: int) -> None:
        cost[name] = len(llm.calls) - start

    print("1. prompt chaining with a programmatic gate")
    start = len(llm.calls)
    steps = [("outline", "outline: {text}"), ("draft", "draft from outline: {text}"), ("translate", "translate to French: {text}")]
    for label, output in prompt_chain("agents vs workflows", llm, steps, lambda label, out: len(out) < 200):
        print(f"  [{label}] {output}")
    measure("chain", start)

    print("\n2. routing with a confidence threshold and an abstain path")
    handlers = {"refund": lambda t: "refund ticket opened", "bug": lambda t: "bug filed", "sales": lambda t: "quote sent"}
    for text in ("I was charged twice, money back please", "API returns 500 error and crashes", "hello, quick question"):
        label, confidence, outcome = route(text, toy_classifier, handlers, threshold=0.5)
        print(f"  {text[:38]:<38} -> {label:<6} p={confidence:.2f} {outcome}")
    cost["route"] = 0

    print("\n3a. parallelization by sectioning")
    sections = ["intro", "pricing", "security", "faq"]
    for section, review in zip(sections, parallel_sections(sections, lambda s: f"{s}: ok ({len(s)} chars)")):
        print(f"  {review}")
    print("3b. parallelization by voting with a quorum")
    start = len(llm.calls)
    for question in ("is the ship safe to sail?", "is this migration reversible?"):
        winner, votes = parallel_vote(question, llm, voters=5, quorum=0.6)
        print(f"  {question:<32} -> {winner:<13} votes={dict(votes)}")
    measure("vote", start)

    print("\n4. orchestrator-workers (plan decided at runtime, bounded)")
    start = len(llm.calls)
    workers = {
        "python_review": lambda t: "python: 2 nits",
        "security_review": lambda t: "security: token logged at INFO",
        "style_review": lambda t: "style: fine",
    }
    plan, results, summary = orchestrator_workers("review PR 42 (python, touches auth)", llm, workers)
    print(f"  plan: {plan}")
    for name, out in results:
        print(f"  [{name}] {out}")
    print(f"  synthesis: {summary}")
    measure("orchestrator", start)

    print("\n5. evaluator-optimizer (keep best-so-far, bounded rounds)")
    start = len(llm.calls)

    def propose(task: str, feedback: str | None) -> str:
        prompt = f"propose: {task}" + (f" | fix: {feedback}" if feedback else "")
        return llm(prompt)

    best, score, trace = evaluator_optimizer("one-line definition of ReAct", propose, rubric, max_rounds=4, target=3)
    for round_number, candidate, round_score, critique in trace:
        print(f"  round {round_number} score={round_score} {candidate}  [{critique}]")
    print(f"  final (score {score}): {best}")
    measure("evaluator", start)

    print(f"\nLLM calls per pattern: {cost}  total={len(llm.calls)}")
    print("each pattern is a few lines of code. add a framework only when it pays for itself.")


if __name__ == "__main__":
    main()
