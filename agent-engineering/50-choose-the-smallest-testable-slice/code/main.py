from __future__ import annotations

import json
from dataclasses import dataclass


@dataclass(frozen=True)
class Slice:
    name: str
    outcome_value: int
    uncertainty_reduced: int
    effort_days: int
    consequence: int
    reversible: bool
    proves: tuple[str, ...]
    real_data: bool
    covers_exception: bool
    repeatable_measurement: bool
    builds_platform: bool
    stop_rule: str


def score(item: Slice) -> float:
    if item.effort_days < 1:
        raise ValueError("effort must be at least one day")
    risk_penalty = item.consequence * (0.5 if item.reversible else 2.0)
    return round((item.outcome_value + item.uncertainty_reduced) / (item.effort_days + risk_penalty), 3)


def false_minimums(item: Slice) -> list[str]:
    found = []
    if not item.real_data:
        found.append("UI-only minimum: no real data, so feasibility stays unknown")
    if not item.covers_exception:
        found.append("happy-path minimum: skips the exception that carries the risk")
    if not item.repeatable_measurement:
        found.append("demo minimum: persuasive, but nothing is measured repeatably")
    if item.builds_platform:
        found.append("platform minimum: builds shared machinery before one workflow earns it")
    return found


def gate(item: Slice, required: set[str]) -> list[str]:
    reasons = []
    missing = required - set(item.proves)
    if missing:
        reasons.append(f"does not prove {sorted(missing)}")
    if not item.stop_rule.strip():
        reasons.append("no stop rule, so every result means keep building")
    if item.consequence >= 4 and not item.reversible:
        reasons.append("irreversible high-consequence slice before evidence exists")
    return reasons


def decide(items: list[Slice], required: set[str]) -> dict:
    rows = []
    for item in items:
        rejected = gate(item, required)
        rows.append(
            {
                "name": item.name,
                "score": score(item),
                "eligible": not rejected,
                "rejected_because": rejected,
                "false_minimum_warnings": false_minimums(item),
            }
        )
    eligible = [row for row in rows if row["eligible"]]
    if not eligible:
        raise ValueError("no slice proves the required assumptions; redesign the candidates")
    chosen_name = max(eligible, key=lambda row: (row["score"], row["name"]))["name"]
    chosen = next(item for item in items if item.name == chosen_name)
    return {"required_proof": sorted(required), "selected": chosen_name, "stop_rule": chosen.stop_rule, "candidates": rows}


def example() -> list[Slice]:
    return [
        Slice("dashboard mockup", 2, 2, 1, 1, True, ("operator-trust",), False, False, False, False, "drop if 3 of 5 engineers ignore it"),
        Slice(
            "shadow-mode decision model on live alerts",
            2,
            4,
            2,
            1,
            True,
            ("service-identification", "calibration"),
            True,
            True,
            True,
            False,
            "stop if precision at P>=0.8 is below 0.9 after 300 alerts",
        ),
        Slice(
            "read-only replay plus shadow log, engineers review suggestions",
            4,
            5,
            4,
            1,
            True,
            ("service-identification", "calibration", "operator-trust"),
            True,
            True,
            True,
            False,
            "stop if fewer than 6 of 10 engineers act on correct suggestions within 2 minutes",
        ),
        Slice(
            "production auto-remediation",
            5,
            4,
            15,
            5,
            False,
            ("service-identification", "calibration", "operator-trust"),
            True,
            True,
            True,
            True,
            "roll back if an incident worsens",
        ),
        Slice("shared agent platform with tool registry", 1, 1, 30, 2, True, (), False, False, False, True, ""),
    ]


def main() -> None:
    required = {"service-identification", "calibration", "operator-trust"}
    result = decide(example(), required)
    print(f"REQUIRED PROOF: {result['required_proof']}\n")
    for row in result["candidates"]:
        marker = "ELIGIBLE" if row["eligible"] else "rejected"
        print(f"  {marker:<8} score={row['score']:<6} {row['name']}")
        for reason in row["rejected_because"]:
            print(f"           gate: {reason}")
        for warning in row["false_minimum_warnings"]:
            print(f"           warn: {warning}")
    print(f"\nSELECTED: {result['selected']}")
    print(f"STOP RULE: {result['stop_rule']}")
    print("\nTwo candidates outscore the winner and still lose: the proof gate outranks the arithmetic.\n")
    print(json.dumps({"selected": result["selected"], "required_proof": result["required_proof"]}, indent=2))


if __name__ == "__main__":
    main()
