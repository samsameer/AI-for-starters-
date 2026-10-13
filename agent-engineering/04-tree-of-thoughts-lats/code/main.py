from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from fractions import Fraction
from itertools import combinations

TARGET = Fraction(24)
OPS = ("+", "-", "*", "/")


@dataclass(frozen=True)
class State:
    numbers: tuple[Fraction, ...]
    steps: tuple[str, ...] = ()

    def key(self) -> tuple[Fraction, ...]:
        return tuple(sorted(self.numbers))

    def solved(self) -> bool:
        return len(self.numbers) == 1 and self.numbers[0] == TARGET

    def terminal(self) -> bool:
        return len(self.numbers) == 1


def show(x: Fraction) -> str:
    return str(x.numerator) if x.denominator == 1 else f"({x.numerator}/{x.denominator})"


def apply(a: Fraction, op: str, b: Fraction) -> Fraction | None:
    if op == "+":
        return a + b
    if op == "-":
        return a - b
    if op == "*":
        return a * b
    return a / b if b != 0 else None


@dataclass
class Meter:
    proposals: int = 0
    evaluations: int = 0

    def calls(self) -> int:
        return self.proposals + self.evaluations


def propose(state: State, meter: Meter) -> list[State]:
    meter.proposals += 1
    children: list[State] = []
    seen: set[tuple[Fraction, ...]] = set()
    nums = state.numbers
    for i, j in combinations(range(len(nums)), 2):
        rest = [n for k, n in enumerate(nums) if k not in (i, j)]
        for a, b in ((nums[i], nums[j]), (nums[j], nums[i])):
            for op in OPS:
                value = apply(a, op, b)
                if value is None or value < 0:
                    continue
                child = State(tuple(rest + [value]), state.steps + (f"{show(a)}{op}{show(b)}={show(value)}",))
                if child.key() in seen:
                    continue
                seen.add(child.key())
                children.append(child)
    return children


def reachable(numbers: tuple[Fraction, ...]) -> bool:
    if len(numbers) == 1:
        return numbers[0] == TARGET
    for i, j in combinations(range(len(numbers)), 2):
        rest = [n for k, n in enumerate(numbers) if k not in (i, j)]
        for a, b in ((numbers[i], numbers[j]), (numbers[j], numbers[i])):
            for op in OPS:
                value = apply(a, op, b)
                if value is not None and reachable(tuple(rest + [value])):
                    return True
    return False


def judge(state: State, meter: Meter) -> tuple[str, float]:
    meter.evaluations += 1
    if state.terminal():
        return ("sure", 1.0) if state.solved() else ("impossible", 0.0)
    if len(state.numbers) == 2:
        return ("sure", 1.0) if reachable(state.numbers) else ("impossible", 0.0)
    closest = min(abs(n - TARGET) for n in state.numbers)
    small_pool = sum(1 for n in state.numbers if n <= 12)
    score = 0.3 + 0.4 / (1 + float(closest) / 6) + 0.05 * small_pool
    return "likely", round(min(score, 0.9), 3)


def greedy_chain(start: State) -> tuple[State, Meter]:
    meter = Meter()
    state = start
    while not state.terminal():
        children = propose(state, meter)
        state = max(children, key=lambda c: (judge(c, meter)[1], -len(c.steps)))
    return state, meter


def tot_beam(start: State, beam_width: int) -> tuple[State | None, Meter, list[int]]:
    meter = Meter()
    frontier = [start]
    widths: list[int] = []
    while frontier and not frontier[0].terminal():
        scored: list[tuple[float, State]] = []
        for state in frontier:
            for child in propose(state, meter):
                label, score = judge(child, meter)
                if label == "impossible":
                    continue
                if child.solved():
                    widths.append(len(scored) + 1)
                    return child, meter, widths
                scored.append((score, child))
        scored.sort(key=lambda pair: (-pair[0], pair[1].steps))
        frontier = [s for _, s in scored[:beam_width]]
        widths.append(len(scored))
    return None, meter, widths


@dataclass
class Node:
    state: State
    parent: "Node | None" = None
    children: list["Node"] = field(default_factory=list)
    visits: int = 0
    total: float = 0.0
    expanded: bool = False

    def q(self) -> float:
        return self.total / self.visits if self.visits else 0.0


def uct(child: Node, parent_visits: int, c: float) -> float:
    if child.visits == 0:
        return math.inf
    return child.q() + c * math.sqrt(math.log(parent_visits) / child.visits)


def lats(start: State, iterations: int, c: float, seed: int) -> tuple[State | None, Meter, int, list[str], int]:
    rng = random.Random(seed)
    meter = Meter()
    root = Node(start)
    reflections: set[tuple[Fraction, ...]] = set()
    notes: list[str] = []
    for iteration in range(1, iterations + 1):
        node = root
        while node.expanded and node.children:
            node = max(node.children, key=lambda ch: uct(ch, node.visits + 1, c))
        if not node.state.terminal() and not node.expanded:
            for child_state in propose(node.state, meter):
                if child_state.key() in reflections:
                    continue
                node.children.append(Node(child_state, node))
            node.expanded = True
            if node.children:
                node = rng.choice(node.children)
        label, reward = judge(node.state, meter)
        if node.state.solved():
            return node.state, meter, iteration, notes, len(reflections)
        if label == "impossible" and node.state.key() not in reflections:
            reflections.add(node.state.key())
            if len(notes) < 3:
                notes.append(f"dead end {[show(n) for n in node.state.numbers]} after {' ; '.join(node.state.steps)}")
        cursor: Node | None = node
        while cursor is not None:
            cursor.visits += 1
            cursor.total += reward
            cursor = cursor.parent
    return None, meter, iterations, notes, len(reflections)


def exhaustive_size(start: State) -> int:
    count = 0
    stack = [start]
    scratch = Meter()
    while stack:
        state = stack.pop()
        count += 1
        if not state.terminal():
            stack.extend(propose(state, scratch))
    return count


def report(name: str, result: State | None, meter: Meter, extra: str = "") -> None:
    verdict = "SOLVED" if result is not None and result.solved() else "failed"
    trail = " ; ".join(result.steps) if result is not None else "-"
    print(f"  {name:<22} {verdict:<7} calls={meter.calls():>4}  {trail}")
    if extra:
        print(f"  {'':<22} {extra}")


def main() -> None:
    print("=" * 76)
    print("LESSON 04 - Tree of Thoughts and LATS on the Game of 24")
    print("=" * 76)
    puzzles = [(4, 6, 4, 1), (1, 5, 5, 5), (3, 3, 8, 8)]
    for puzzle in puzzles:
        start = State(tuple(Fraction(n) for n in puzzle))
        print(f"\npuzzle {list(puzzle)}  full tree size: {exhaustive_size(start)} nodes")
        chain, chain_meter = greedy_chain(start)
        report("chain (no backtrack)", chain, chain_meter)
        for width in (1, 5):
            found, meter, widths = tot_beam(start, width)
            report(f"ToT beam width={width}", found, meter, f"candidates kept per level: {widths}")
        found, meter, used, notes, stored = lats(start, iterations=400, c=1.0, seed=11)
        report("LATS / MCTS", found, meter, f"iterations used: {used}, dead ends remembered: {stored}")
        for note in notes[:2]:
            print(f"  {'':<22} reflection: {note}")
    print("\nEXPLORATION KNOB (LATS on [3, 3, 8, 8], same seed)")
    start = State(tuple(Fraction(n) for n in (3, 3, 8, 8)))
    for c in (0.1, 1.0, 3.0):
        found, meter, used, _, _ = lats(start, iterations=400, c=c, seed=11)
        status = "SOLVED" if found else "failed"
        print(f"  c={c:<4} {status:<7} iterations={used:>3} calls={meter.calls():>4}")
    print("\ntakeaways:")
    print("  - a single chain commits early and cannot recover from a bad first step")
    print("  - search buys correctness with many more model calls; budget it explicitly")
    print("  - the value function decides everything: a 'sure/impossible' check prunes whole subtrees")


if __name__ == "__main__":
    main()
