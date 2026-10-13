from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Callable

State = frozenset[str]


@dataclass(frozen=True)
class Operator:
    name: str
    pre: tuple[str, ...]
    add: tuple[str, ...]
    remove: tuple[str, ...] = ()

    def applicable(self, state: State) -> bool:
        return all(fact in state for fact in self.pre)

    def apply(self, state: State) -> State:
        return frozenset((set(state) - set(self.remove)) | set(self.add))


@dataclass(frozen=True)
class Method:
    name: str
    task: str
    pre: tuple[str, ...]
    subtasks: tuple[str, ...]


@dataclass
class ScriptedLLM:
    proposals: dict[str, list[tuple[str, ...]]]
    calls: list[str] = field(default_factory=list)

    def decompose(self, task: str, state: State) -> list[tuple[str, ...]]:
        self.calls.append(task)
        return self.proposals.get(task, [])


@dataclass
class HTNPlanner:
    operators: dict[str, Operator]
    methods: dict[str, list[Method]]
    llm: ScriptedLLM
    learned: dict[str, tuple[str, ...]] = field(default_factory=dict)
    rejected: list[tuple[str, tuple[str, ...], str]] = field(default_factory=list)
    max_depth: int = 12

    def known(self, task: str) -> bool:
        return task in self.operators or task in self.methods or task in self.learned

    def plan(self, tasks: list[str], state: State, depth: int = 0) -> tuple[list[str], State] | None:
        if not tasks:
            return [], state
        if depth > self.max_depth:
            return None
        head, rest = tasks[0], tasks[1:]
        if head in self.operators:
            op = self.operators[head]
            if not op.applicable(state):
                return None
            tail = self.plan(rest, op.apply(state), depth + 1)
            return None if tail is None else ([head] + tail[0], tail[1])
        for method in self.methods.get(head, []):
            if all(fact in state for fact in method.pre):
                result = self.plan(list(method.subtasks) + rest, state, depth + 1)
                if result is not None:
                    return result
        if head in self.learned:
            result = self.plan(list(self.learned[head]) + rest, state, depth + 1)
            if result is not None:
                return result
        for proposal in self.llm.decompose(head, state):
            unknown = [t for t in proposal if not self.known(t)]
            if unknown:
                self.rejected.append((head, proposal, f"unknown tasks {unknown}"))
                continue
            result = self.plan(list(proposal) + rest, state, depth + 1)
            if result is None:
                self.rejected.append((head, proposal, "preconditions unsatisfiable"))
                continue
            self.learned[head] = proposal
            return result
        return None


def build_planner() -> HTNPlanner:
    operators = {
        "open_branch": Operator("open_branch", ("repo_cloned",), ("branch_open",)),
        "write_migration": Operator("write_migration", ("branch_open",), ("migration_written",)),
        "write_code": Operator("write_code", ("branch_open",), ("code_written",)),
        "run_tests": Operator("run_tests", ("code_written",), ("tests_green",)),
        "dry_run_migration": Operator("dry_run_migration", ("migration_written",), ("migration_safe",)),
        "request_approval": Operator("request_approval", ("tests_green",), ("approved",)),
        "open_pr": Operator("open_pr", ("tests_green", "approved"), ("pr_open",)),
        "hotfix_merge": Operator("hotfix_merge", ("incident_declared", "tests_green"), ("pr_open",)),
    }
    methods = {
        "ship_change": [
            Method("hotfix_path", "ship_change", ("incident_declared",), ("open_branch", "write_code", "run_tests", "hotfix_merge")),
            Method("normal_path", "ship_change", (), ("open_branch", "write_code", "run_tests", "request_approval", "open_pr")),
        ],
    }
    llm = ScriptedLLM({
        "ship_with_migration": [
            ("open_branch", "write_code", "deploy_to_prod"),
            ("open_branch", "write_code", "run_tests", "open_pr"),
            ("open_branch", "write_migration", "dry_run_migration", "write_code", "run_tests", "request_approval", "open_pr"),
        ],
    })
    return HTNPlanner(operators, methods, llm)


def htn_demo() -> None:
    print("demo 1: ChatHTN-style planner (symbolic first, LLM fallback, validated)")
    planner = build_planner()
    base = frozenset({"repo_cloned"})
    cases = [
        ("A normal day", "ship_change", base),
        ("B incident", "ship_change", base | {"incident_declared"}),
        ("C no method", "ship_with_migration", base),
        ("D cached", "ship_with_migration", base),
    ]
    for label, task, state in cases:
        calls_before = len(planner.llm.calls)
        result = planner.plan([task], state)
        steps = result[0] if result else None
        print(f"  case {label}: {task}")
        print(f"    plan: {steps}")
        print(f"    new LLM calls: {len(planner.llm.calls) - calls_before}")
    print("  rejected LLM proposals (soundness kept by the symbolic layer):")
    for task, proposal, reason in planner.rejected:
        print(f"    {task}: {list(proposal)} -> {reason}")


Program = tuple[int, int, int]


def evaluator(program: Program) -> int:
    a, b, c = program
    error = 0
    for x in range(-6, 7):
        target = 2 * x * x - 3 * x + 5
        error += abs(target - (a * x * x + b * x + c))
    return error


def mutate(program: Program, rng: random.Random) -> Program:
    genes = list(program)
    index = rng.randrange(3)
    genes[index] += rng.choice((-3, -2, -1, 1, 2, 3))
    return (genes[0], genes[1], genes[2])


def crossover(left: Program, right: Program, rng: random.Random) -> Program:
    return tuple(rng.choice(pair) for pair in zip(left, right))


def evolve(fitness: Callable[[Program], int], generations: int = 40, seed: int = 7) -> list[tuple[int, Program, int]]:
    rng = random.Random(seed)
    population = [(rng.randint(-9, 9), rng.randint(-9, 9), rng.randint(-9, 9)) for _ in range(8)]
    history: list[tuple[int, Program, int]] = []
    for generation in range(generations + 1):
        population.sort(key=fitness)
        best = population[0]
        history.append((generation, best, fitness(best)))
        if fitness(best) == 0:
            break
        elite = population[:4]
        children = [mutate(rng.choice(elite), rng) for _ in range(8)]
        children += [crossover(rng.choice(elite), rng.choice(elite), rng) for _ in range(4)]
        population = sorted(set(elite + children), key=fitness)[:8]
    return history


def evolution_demo() -> None:
    print("\ndemo 2: AlphaEvolve-style search (mutate, evaluate deterministically, keep the best)")
    print("  target program: 2x^2 - 3x + 5, fitness = total abs error on x in [-6, 6]")
    history = evolve(evaluator)
    for generation, best, score in history:
        if generation % 5 == 0 or score == 0:
            print(f"  gen {generation:02d}  best a,b,c={best}  error={score}")
    final = history[-1]
    print(f"  converged={final[2] == 0} after {final[0]} generations")


def main() -> None:
    htn_demo()
    evolution_demo()
    print("\nHTN: the LLM proposes, the schema disposes. Evolution: no checkable evaluator, no progress.")


if __name__ == "__main__":
    main()
