from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, replace

CLASSES = {"value", "usability", "feasibility", "viability", "safety"}
UNFALSIFIABLE = ("useful", "better", "intuitive", "users like", "works well", "valuable")


@dataclass(frozen=True)
class Experiment:
    method: str
    sample: str
    metric: str
    threshold: str
    on_pass: str
    on_fail: str
    on_ambiguous: str
    cost_days: float


@dataclass(frozen=True)
class Assumption:
    category: str
    statement: str
    impact: int
    uncertainty: int
    irreversibility: int
    experiment: Experiment
    evidence: str = ""


def risk_score(item: Assumption) -> int:
    for value in (item.impact, item.uncertainty, item.irreversibility):
        if value not in range(1, 6):
            raise ValueError("risk dimensions must be integers from 1 to 5")
    return item.impact * item.uncertainty + item.irreversibility


def lint(item: Assumption) -> list[str]:
    issues = []
    if item.category not in CLASSES:
        issues.append(f"unknown class {item.category!r}")
    lowered = item.statement.lower()
    if any(word in lowered for word in UNFALSIFIABLE) and not re.search(r"\d", lowered):
        issues.append("statement is not falsifiable: add a population, a number, and an observable")
    experiment = item.experiment
    for name in ("sample", "metric", "threshold", "on_pass", "on_fail", "on_ambiguous"):
        if not getattr(experiment, name).strip():
            issues.append(f"experiment lacks {name}")
    if experiment.on_pass == experiment.on_fail:
        issues.append("pass and fail lead to the same decision, so this is a ritual, not an experiment")
    return issues


def rank(items: list[Assumption]) -> list[dict]:
    ranked = sorted(items, key=lambda item: (-risk_score(item), item.statement))
    return [
        {
            "risk": risk_score(item),
            "class": item.category,
            "status": "tested" if item.evidence else "open",
            "statement": item.statement,
            "lint": lint(item),
        }
        for item in ranked
    ]


def next_experiment(items: list[Assumption]) -> Assumption | None:
    open_items = [item for item in items if not item.evidence and not lint(item)]
    return max(open_items, key=lambda item: (risk_score(item), -item.experiment.cost_days), default=None)


def example() -> list[Assumption]:
    return [
        Assumption(
            "feasibility",
            "On 200 replayed alerts, a decision model names the failing service with P>=0.8 on at least 70% of them and is right on at least 97% of those",
            5,
            5,
            1,
            Experiment("offline replay with Clef-flash choice question", "200 recorded alerts, last 90 days", "coverage at P>=0.8 and precision in that band", "coverage>=0.70 and precision>=0.97", "build shadow-mode slice", "drop auto-identification; keep a search UI", "label 200 more alerts and re-run", 2),
        ),
        Assumption(
            "usability",
            "8 of 10 on-call engineers act on a read-only suggestion within 2 minutes without opening dashboards",
            4,
            4,
            1,
            Experiment("moderated replay sessions", "10 engineers, both senior and junior", "time to correct action", "8 of 10 under 120 s", "proceed to pilot", "redesign the suggestion format", "run 10 more sessions", 5),
        ),
        Assumption(
            "value",
            "Faster diagnosis is useful",
            4,
            2,
            1,
            Experiment("interviews", "", "", "", "build", "build", "build", 1),
            "4 of 5 incident commanders confirmed in interviews",
        ),
        Assumption(
            "safety",
            "Automatic rollback on a P>=0.95 verdict causes zero customer-visible regressions over 50 incidents",
            5,
            4,
            5,
            Experiment("do not automate yet; measure human approval rate of suggested rollbacks", "50 pilot incidents", "suggested rollbacks rejected by the commander", "rejections<=2", "propose auto-rollback for one service", "keep the human approval step", "extend the pilot", 30),
        ),
        Assumption(
            "viability",
            "Platform team can own the decision eval set at 2 hours per week",
            3,
            3,
            2,
            Experiment("time tracking for 4 weeks", "platform team", "hours per week on labeling", "<=2", "assign ownership", "fund a rotating labeler", "track 4 more weeks", 20),
        ),
    ]


def main() -> None:
    items = example()
    print("ASSUMPTION MAP (risk = impact * uncertainty + irreversibility)")
    for row in rank(items):
        flag = "  LINT: " + "; ".join(row["lint"]) if row["lint"] else ""
        print(f"  {row['risk']:>2}  {row['class']:<11} {row['status']:<6} {row['statement'][:88]}{flag}")
    chosen = next_experiment(items)
    print(f"\nNEXT EXPERIMENT -> {chosen.statement[:70]}...")
    print(json.dumps(asdict(chosen.experiment), indent=2))
    print("\nAFTER THE REPLAY PASSES")
    updated = [replace(item, evidence="coverage 0.74, precision 0.98 on 200 alerts") if item is chosen else item for item in items]
    follow_up = next_experiment(updated)
    print(f"  next experiment becomes: {follow_up.category} -> {follow_up.statement[:80]}")
    print("  note: the safety assumption ranks highest but its experiment deliberately keeps a human in the loop")


if __name__ == "__main__":
    main()
