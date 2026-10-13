from __future__ import annotations

import random
from collections import Counter
from dataclasses import dataclass

OPTIONS = ("A", "B", "C", "D")
CORRECT = "A"
MISCONCEPTION = "B"
TOKENS_PER_ANSWER = 220
TOKENS_PER_PEER_READ = 180
TRAP_RATE = 0.3


@dataclass(frozen=True)
class Debater:
    name: str
    family: str
    skill: float
    shares_misconception: float
    stubbornness: float


def draw_traps(families: set[str], rng: random.Random) -> dict[str, bool]:
    return {family: rng.random() < TRAP_RATE for family in sorted(families)}


def initial_answer(d: Debater, trapped: bool, rng: random.Random) -> str:
    skill = d.skill * 0.3 if trapped else min(0.95, d.skill + 0.15)
    misconception = 0.9 if trapped else d.shares_misconception
    if rng.random() < skill:
        return CORRECT
    if rng.random() < misconception:
        return MISCONCEPTION
    return rng.choice(OPTIONS[2:])


def topology(kind: str, n: int) -> dict[int, list[int]]:
    if kind == "full":
        return {i: [j for j in range(n) if j != i] for i in range(n)}
    if kind == "ring":
        return {i: [(i - 1) % n, (i + 1) % n] for i in range(n)}
    if kind == "star":
        return {i: ([j for j in range(1, n)] if i == 0 else [0]) for i in range(n)}
    if kind == "none":
        return {i: [] for i in range(n)}
    raise ValueError(kind)


def update(d: Debater, own: str, seen: list[str], rng: random.Random) -> str:
    if not seen or rng.random() < d.stubbornness:
        return own
    if CORRECT in seen and own != CORRECT and rng.random() < 0.45:
        return CORRECT
    pool = Counter(seen + [own])
    top, votes = pool.most_common(1)[0]
    if top != own and votes > pool[own] and rng.random() < 0.5:
        return top
    return own


def debate(team: list[Debater], kind: str, rounds: int, rng: random.Random) -> tuple[str, int, int]:
    graph = topology(kind, len(team))
    traps = draw_traps({d.family for d in team}, rng)
    answers = [initial_answer(d, traps[d.family], rng) for d in team]
    tokens = TOKENS_PER_ANSWER * len(team)
    used_rounds = 0
    for _ in range(rounds if kind != "none" else 0):
        if len(set(answers)) == 1:
            break
        used_rounds += 1
        answers = [update(d, answers[i], [answers[j] for j in graph[i]], rng) for i, d in enumerate(team)]
        tokens += sum(TOKENS_PER_ANSWER + TOKENS_PER_PEER_READ * len(graph[i]) for i in range(len(team)))
    final = Counter(answers).most_common(1)[0][0]
    return final, tokens, used_rounds


def self_consistency(d: Debater, samples: int, rng: random.Random) -> tuple[str, int]:
    trapped = draw_traps({d.family}, rng)[d.family]
    votes = Counter(initial_answer(d, trapped, rng) for _ in range(samples))
    return votes.most_common(1)[0][0], samples * TOKENS_PER_ANSWER


def evaluate(label: str, runner, questions: int, seed: int) -> tuple[str, float, float, float]:
    rng = random.Random(seed)
    correct = 0
    tokens = 0
    rounds = 0
    for _ in range(questions):
        answer, cost, used = runner(rng)
        correct += answer == CORRECT
        tokens += cost
        rounds += used
    return label, correct / questions, tokens / questions, rounds / questions


def main() -> None:
    print("=" * 76)
    print("MULTI-AGENT DEBATE: topology, cost, and correlated errors")
    print("=" * 76)

    diverse = [
        Debater("model-x", "x", 0.62, 0.3, 0.25),
        Debater("model-y", "y", 0.55, 0.2, 0.25),
        Debater("model-z", "z", 0.58, 0.1, 0.25),
        Debater("model-x-alt-prompt", "x", 0.60, 0.3, 0.25),
        Debater("model-w", "w", 0.50, 0.2, 0.25),
    ]
    clones = [Debater(f"clone-{i}", "x", 0.58, 0.3, 0.25) for i in range(5)]
    best = max(diverse, key=lambda d: d.skill)
    questions = 2000
    rounds = 3

    rows = [
        evaluate("single agent (best)", lambda r: (*self_consistency(best, 1, r), 0), questions, 1),
        evaluate("self-consistency k=15", lambda r: (*self_consistency(best, 15, r), 0), questions, 2),
        evaluate("self-consistency k=48", lambda r: (*self_consistency(best, 48, r), 0), questions, 8),
        evaluate("independent vote, 5 diverse", lambda r: debate(diverse, "none", rounds, r), questions, 3),
        evaluate("debate full mesh, 5 diverse", lambda r: debate(diverse, "full", rounds, r), questions, 4),
        evaluate("debate ring, 5 diverse", lambda r: debate(diverse, "ring", rounds, r), questions, 5),
        evaluate("debate star, 5 diverse", lambda r: debate(diverse, "star", rounds, r), questions, 6),
        evaluate("debate full mesh, 5 clones", lambda r: debate(clones, "full", rounds, r), questions, 7),
    ]

    print(f"\n{'protocol':<30} {'accuracy':>9} {'tokens/q':>9} {'rounds':>7}")
    for label, acc, tokens, used in rows:
        print(f"{label:<30} {acc:>9.3f} {tokens:>9.0f} {used:>7.2f}")

    full = next(r for r in rows if r[0].startswith("debate full mesh, 5 diverse"))
    ring = next(r for r in rows if r[0].startswith("debate ring"))
    sc = next(r for r in rows if r[0].startswith("self-consistency k=48"))
    clones_row = rows[-1]
    print("\nreadout:")
    print(f"  ring vs full mesh: {ring[1] - full[1]:+.3f} accuracy at {100 * ring[2] / full[2]:.0f}% of the tokens")
    print(f"  full-mesh debate vs same-budget self-consistency: {full[1] - sc[1]:+.3f} accuracy at {full[2] / sc[2]:.2f}x the tokens")
    print(f"  clones vs diverse team: {clones_row[1] - full[1]:+.3f} accuracy (shared misconception)")
    print("  always compare debate against a same-budget voting baseline before shipping it")


if __name__ == "__main__":
    main()
