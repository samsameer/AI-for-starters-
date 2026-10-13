from __future__ import annotations

import random
from collections import Counter, defaultdict
from dataclasses import dataclass, field


@dataclass
class Trace:
    trace_id: str
    session_id: str
    prompt_version: str
    model: str
    question: str
    answer: str
    tool_errors: int
    guard_blocks: int
    latency_ms: int
    cost_usd: float
    human_label: str | None = None
    scores: dict[str, float] = field(default_factory=dict)
    tags: list[str] = field(default_factory=list)


KNOWN_FACTS = {
    "refund window": "30 days",
    "support hours": "9 to 5",
    "shipping time": "3 days",
}


def synthesize(seed: int = 7, n: int = 60) -> list[Trace]:
    rng = random.Random(seed)
    traces = []
    for i in range(n):
        version = "v12" if i < n // 2 else "v13"
        topic = rng.choice(list(KNOWN_FACTS))
        truth = KNOWN_FACTS[topic]
        wrong_rate = 0.08 if version == "v12" else 0.30
        if rng.random() < wrong_rate:
            answer = f"The {topic} is {rng.choice(['14 days', '24/7', 'next day'])}."
        else:
            answer = f"The {topic} is {truth}."
        if rng.random() < 0.1:
            answer += " Also, I upgraded your plan for free."
        label = None
        if i % 4 == 0:
            label = "good" if truth in answer and "upgraded" not in answer else "bad"
            if rng.random() < 0.15:
                label = "bad" if label == "good" else "good"
        traces.append(Trace(
            trace_id=f"t{i:03d}",
            session_id=f"s{i // 3:02d}",
            prompt_version=version,
            model="gpt-6-luna",
            question=f"What is the {topic}?",
            answer=answer,
            tool_errors=1 if rng.random() < 0.07 else 0,
            guard_blocks=1 if rng.random() < 0.05 else 0,
            latency_ms=int(rng.gauss(1400 if version == "v12" else 1700, 250)),
            cost_usd=round(rng.uniform(0.002, 0.006), 4),
            human_label=label,
        ))
    return traces


def grounded_judge(trace: Trace) -> dict[str, float]:
    topic = next(t for t in KNOWN_FACTS if t in trace.question)
    correct = 1.0 if KNOWN_FACTS[topic] in trace.answer else 0.0
    in_scope = 0.0 if "upgraded" in trace.answer else 1.0
    return {"correctness": correct, "scope": in_scope}


def decision_style_scores(trace: Trace) -> dict[str, float]:
    base = grounded_judge(trace)
    p_correct = 0.93 if base["correctness"] else 0.06
    p_in_scope = 0.9 if base["scope"] else 0.12
    return {"p_correct": p_correct, "p_in_scope": p_in_scope}


def evaluate(traces: list[Trace]) -> None:
    for t in traces:
        t.scores.update(grounded_judge(t))
        t.scores.update(decision_style_scores(t))
        if t.scores["p_correct"] < 0.5:
            t.tags.append("wrong_fact")
        if t.scores["p_in_scope"] < 0.5:
            t.tags.append("scope_creep")
        if t.tool_errors:
            t.tags.append("tool_error")
        if t.guard_blocks:
            t.tags.append("guard_block")
        if t.latency_ms > 2000:
            t.tags.append("slow")


def judge_agreement(traces: list[Trace]) -> tuple[int, int]:
    labeled = [t for t in traces if t.human_label]
    agree = 0
    for t in labeled:
        judge_good = t.scores["p_correct"] >= 0.5 and t.scores["p_in_scope"] >= 0.5
        agree += int(judge_good == (t.human_label == "good"))
    return agree, len(labeled)


def dashboard(traces: list[Trace]) -> None:
    by_version: dict[str, list[Trace]] = defaultdict(list)
    for t in traces:
        by_version[t.prompt_version].append(t)
    print(f"\n{'version':<8} {'n':>3} {'fail%':>6} {'correct':>8} {'p50 ms':>7} {'$/trace':>8}")
    for version, group in sorted(by_version.items()):
        failed = sum(1 for t in group if t.tags and t.tags != ["slow"])
        correct = sum(t.scores["correctness"] for t in group) / len(group)
        p50 = sorted(t.latency_ms for t in group)[len(group) // 2]
        cost = sum(t.cost_usd for t in group) / len(group)
        print(f"{version:<8} {len(group):>3} {100 * failed / len(group):>5.0f}% {correct:>8.2f} {p50:>7} {cost:>8.4f}")
    print("\ntop failure tags:")
    for tag, count in Counter(tag for t in traces for tag in t.tags).most_common():
        print(f"  {tag:<12} {count:>3}")
    sessions = defaultdict(list)
    for t in traces:
        sessions[t.session_id].append(t)
    bad_sessions = [s for s, ts in sessions.items() if any("wrong_fact" in t.tags for t in ts)]
    print(f"\nsessions with at least one wrong fact: {len(bad_sessions)}/{len(sessions)}  e.g. {bad_sessions[:4]}")


def bisect_regression(traces: list[Trace]) -> None:
    rates = {}
    for version in sorted({t.prompt_version for t in traces}):
        group = [t for t in traces if t.prompt_version == version]
        rates[version] = 1 - sum(t.scores["correctness"] for t in group) / len(group)
    worst = max(rates, key=rates.get)
    print("\nregression bisect by prompt version (wrong-fact rate):")
    for version, rate in rates.items():
        marker = "  <- regression" if version == worst and rate > min(rates.values()) * 1.5 else ""
        print(f"  {version}: {rate:.2f}{marker}")


def pick_platform(needs: set[str]) -> list[str]:
    catalog = {
        "Langfuse": {"open_source", "self_host", "prompt_mgmt", "evals", "sessions", "otel"},
        "Arize Phoenix": {"self_host", "evals", "rag_eval", "drift", "otel"},
        "Comet Opik": {"open_source", "self_host", "evals", "prompt_opt", "guardrails", "otel"},
        "LangSmith": {"evals", "prompt_mgmt", "sessions", "trajectories", "otel", "voice"},
        "Braintrust": {"evals", "prompt_mgmt", "agent_queries_traces", "otel"},
    }
    ranked = sorted(catalog, key=lambda name: (-len(needs & catalog[name]), name))
    return [f"{name} ({len(needs & catalog[name])}/{len(needs)})" for name in ranked]


def main() -> None:
    print("=" * 70)
    print("AGENT OBSERVABILITY: ingest, evaluate, tag, bisect (Oct 2026 edition)")
    print("=" * 70)
    traces = synthesize()
    evaluate(traces)
    dashboard(traces)
    bisect_regression(traces)
    agree, total = judge_agreement(traces)
    print(f"\njudge vs human labels: {agree}/{total} agree ({100 * agree / total:.0f}%)")
    print("\nplatform fit for needs {open_source, self_host, prompt_mgmt, evals, otel}:")
    for line in pick_platform({"open_source", "self_host", "prompt_mgmt", "evals", "otel"}):
        print(f"  {line}")
    print("\nlesson: tracing without evals is expensive logging; evals without prompt")
    print("versions cannot tell you which change broke production.")


if __name__ == "__main__":
    main()
