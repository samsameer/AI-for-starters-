from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable

SOURCE_OF_TRUTH = {
    "revenue_q2": 35,
    "revenue_q3": 42,
    "top_region": "EMEA",
    "customers": 1200,
}
MAX_BULLETS = 3
MAX_CHARS = 60


@dataclass(frozen=True)
class Issue:
    tag: str
    detail: str
    grounded: bool


@dataclass
class Critique:
    issues: list[Issue]
    source: str

    def passed(self) -> bool:
        return not self.issues


@dataclass
class Round:
    number: int
    draft: list[str]
    critique: Critique


@dataclass
class RunResult:
    label: str
    rounds: list[Round] = field(default_factory=list)
    stop_reason: str = ""


def growth_percent() -> int:
    q2, q3 = SOURCE_OF_TRUTH["revenue_q2"], SOURCE_OF_TRUTH["revenue_q3"]
    return round((q3 - q2) * 100 / q2)


def generate_first_draft() -> list[str]:
    return [
        "Q3 revenue reached $42M, an outstanding quarter for every team",
        "Revenue grew 17% quarter over quarter",
        "APAC was the top region by bookings",
        "Customer count passed 1,200",
    ]


FIXES: dict[str, Callable[[list[str]], list[str]]] = {
    "too_long": lambda d: [b if len(b) <= MAX_CHARS else b.split(",")[0] for b in d],
    "too_many": lambda d: d[:MAX_BULLETS] if len(d) > MAX_BULLETS else d,
    "wrong_growth": lambda d: [re.sub(r"grew \d+%", f"grew {growth_percent()}%", b) for b in d],
    "wrong_region": lambda d: [b.replace("APAC", SOURCE_OF_TRUTH["top_region"]) for b in d],
}
FIX_ORDER = ["too_long", "wrong_growth", "wrong_region", "too_many"]


def refine(known_tags: set[str]) -> list[str]:
    draft = generate_first_draft()
    for tag in FIX_ORDER:
        if tag in known_tags:
            draft = FIXES[tag](draft)
    return draft


def format_tool(draft: list[str]) -> list[Issue]:
    issues: list[Issue] = []
    for bullet in draft:
        if len(bullet) > MAX_CHARS:
            issues.append(Issue("too_long", f"{len(bullet)} chars: {bullet[:28]}...", True))
    if len(draft) > MAX_BULLETS:
        issues.append(Issue("too_many", f"{len(draft)} bullets, limit {MAX_BULLETS}", True))
    return issues


def calculator_tool(draft: list[str]) -> list[Issue]:
    issues: list[Issue] = []
    for bullet in draft:
        match = re.search(r"grew (\d+)%", bullet)
        if match and int(match.group(1)) != growth_percent():
            issues.append(Issue("wrong_growth", f"claimed {match.group(1)}%, computed {growth_percent()}% from 35 -> 42", True))
    return issues


def lookup_tool(draft: list[str]) -> list[Issue]:
    issues: list[Issue] = []
    regions = ("APAC", "EMEA", "AMER", "LATAM")
    for bullet in draft:
        for region in regions:
            if region in bullet and "top region" in bullet and region != SOURCE_OF_TRUTH["top_region"]:
                issues.append(Issue("wrong_region", f"claimed {region}, record says {SOURCE_OF_TRUTH['top_region']}", True))
    return issues


def self_critic(draft: list[str]) -> Critique:
    issues: list[Issue] = []
    for bullet in draft:
        if len(bullet) > MAX_CHARS + 2:
            issues.append(Issue("too_long", "this bullet feels long", False))
    if len(draft) > MAX_BULLETS:
        issues.append(Issue("too_many", "there seem to be extra bullets", False))
    return Critique(issues, "self-critique (same model, no tools)")


def critic_with_tools(draft: list[str]) -> Critique:
    for name, tool in (("format linter", format_tool), ("calculator", calculator_tool), ("record lookup", lookup_tool)):
        issues = tool(draft)
        if issues:
            return Critique(issues, f"CRITIC via {name}")
    return Critique([], "CRITIC (all tools passed)")


def ground_truth_errors(draft: list[str]) -> list[str]:
    return [i.tag for i in format_tool(draft) + calculator_tool(draft) + lookup_tool(draft)]


def run_loop(label: str, critic: Callable[[list[str]], Critique], keep_history: bool, max_rounds: int) -> RunResult:
    result = RunResult(label)
    known: set[str] = set()
    draft = generate_first_draft()
    seen_drafts: list[list[str]] = []
    for number in range(1, max_rounds + 1):
        critique = critic(draft)
        result.rounds.append(Round(number, draft, critique))
        if critique.passed():
            result.stop_reason = "critic passed"
            return result
        if draft in seen_drafts:
            result.stop_reason = "oscillation detected (draft repeated)"
            return result
        seen_drafts.append(draft)
        new_tags = {issue.tag for issue in critique.issues}
        known = known | new_tags if keep_history else new_tags
        draft = refine(known)
    result.stop_reason = f"hit max_rounds={max_rounds}"
    return result


def print_run(result: RunResult) -> None:
    print(f"\n{result.label}")
    print("-" * 76)
    for r in result.rounds:
        verdict = "pass" if r.critique.passed() else ", ".join(i.tag for i in r.critique.issues)
        print(f"  round {r.number}: {len(r.draft)} bullets, {r.critique.source}: {verdict}")
        for issue in r.critique.issues:
            kind = "tool" if issue.grounded else "opinion"
            print(f"           [{kind}] {issue.detail}")
    final = result.rounds[-1].draft
    print(f"  stop: {result.stop_reason}")
    print("  shipped:")
    for bullet in final:
        print(f"    - {bullet}")
    errors = ground_truth_errors(final)
    print(f"  ground-truth audit: {'clean' if not errors else 'SHIPPED ERRORS ' + str(errors)}")


def main() -> None:
    print("=" * 76)
    print("LESSON 05 - Self-Refine vs CRITIC: three bullets, <= 60 chars, all facts true")
    print("=" * 76)
    print(f"source of truth: {SOURCE_OF_TRUTH}")
    runs = [
        run_loop("SELF-REFINE (self-critique, history kept)", self_critic, True, 4),
        run_loop("CRITIC (tool-grounded critique, history kept)", critic_with_tools, True, 5),
        run_loop("CRITIC WITHOUT HISTORY (refiner sees only the last critique)", critic_with_tools, False, 6),
    ]
    for result in runs:
        print_run(result)
    print("\nSUMMARY")
    print(f"  {'run':<62} {'rounds':>6} {'errors':>6}")
    for result in runs:
        print(f"  {result.label:<62} {len(result.rounds):>6} {len(ground_truth_errors(result.rounds[-1].draft)):>6}")
    print("\ntakeaways:")
    print("  - self-critique fixes style and rubber-stamps plausible numbers")
    print("  - tool-grounded critique catches the wrong growth rate and the wrong region")
    print("  - dropping refine history makes the loop undo earlier fixes and oscillate")


if __name__ == "__main__":
    main()
