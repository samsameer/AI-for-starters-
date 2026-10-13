from __future__ import annotations

import json
from dataclasses import dataclass

EVIDENCE_STRENGTH = {"direct": 1.0, "artifact": 0.8, "reported": 0.5, "inference": 0.25}


@dataclass(frozen=True)
class Evidence:
    kind: str
    source: str
    observation: str


@dataclass(frozen=True)
class Step:
    variant: str
    order: int
    actor: str
    trigger: str
    action: str
    evidence: tuple[Evidence, ...]
    friction: str = ""
    hidden_state: str = ""
    authority: str = ""
    answers: tuple[str, ...] = ()
    branch_from: int = 0


def audit(steps: list[Step]) -> dict:
    issues: list[str] = []
    by_variant: dict[str, list[Step]] = {}
    for step in steps:
        by_variant.setdefault(step.variant, []).append(step)
    for variant, items in by_variant.items():
        main_path = [item.order for item in items if not item.branch_from]
        if sorted(main_path) != list(range(1, len(main_path) + 1)):
            issues.append(f"variant {variant!r}: main path order must be contiguous from 1")
        for item in items:
            if item.branch_from and item.branch_from not in main_path:
                issues.append(f"variant {variant!r}: exception step {item.order} branches from a missing step")
    for step in steps:
        if not step.evidence:
            issues.append(f"{step.variant}/{step.order} has no evidence")
        for item in step.evidence:
            if item.kind not in EVIDENCE_STRENGTH:
                issues.append(f"{step.variant}/{step.order} has unknown evidence kind {item.kind!r}")
    all_evidence = [item for step in steps for item in step.evidence if item.kind in EVIDENCE_STRENGTH]
    direct_like = sum(item.kind in ("direct", "artifact") for item in all_evidence)
    weak_steps = [
        f"{step.variant}/{step.order} {step.action}"
        for step in steps
        if step.evidence and max(EVIDENCE_STRENGTH.get(item.kind, 0) for item in step.evidence) < 0.8
    ]
    return {
        "status": "grounded" if not issues and not weak_steps else "needs-evidence",
        "issues": issues,
        "direct_or_artifact_ratio": round(direct_like / len(all_evidence), 2) if all_evidence else 0.0,
        "weakly_evidenced_steps": weak_steps,
        "friction": [f"{step.variant}/{step.order}: {step.friction}" for step in steps if step.friction],
        "hidden_state": [f"{step.variant}/{step.order}: {step.hidden_state}" for step in steps if step.hidden_state],
        "authority_boundaries": [f"{step.variant}/{step.order}: {step.authority}" for step in steps if step.authority],
        "exceptions": [f"{step.variant}/{step.order} branches from step {step.branch_from}: {step.action}" for step in steps if step.branch_from],
    }


def decision_points(steps: list[Step]) -> list[dict]:
    points = []
    for step in steps:
        if not step.answers:
            continue
        if step.authority:
            owner = "human: authority boundary"
        elif len(step.answers) <= 64 and "open" not in step.answers:
            owner = "System One candidate (choice)" if len(step.answers) > 2 else "System One candidate (noul)"
        else:
            owner = "System Two"
        points.append({"step": f"{step.variant}/{step.order}", "decision": step.action, "answers": list(step.answers), "owner": owner})
    return points


def divergence(steps: list[Step], left: str, right: str) -> list[str]:
    left_actions = [step.action for step in steps if step.variant == left and not step.branch_from]
    right_actions = [step.action for step in steps if step.variant == right and not step.branch_from]
    notes = []
    for index in range(max(len(left_actions), len(right_actions))):
        a = left_actions[index] if index < len(left_actions) else "(none)"
        b = right_actions[index] if index < len(right_actions) else "(none)"
        if a != b:
            notes.append(f"step {index + 1}: {left} '{a}' vs {right} '{b}'")
    return notes


def example() -> list[Step]:
    trace = Evidence("direct", "OTel trace of incident 184 (invoke_agent and execute_tool spans)", "three dashboard queries in 4 min")
    recording = Evidence("direct", "screen recording 01", "alert payload lacks service owner")
    runbook = Evidence("artifact", "runbook v7", "production writes require commander approval")
    interview = Evidence("reported", "interview with senior on-call", "checks deploy log first")
    guess = Evidence("inference", "team retro", "juniors probably escalate earlier")
    return [
        Step("senior", 1, "on-call engineer", "alert fires", "opens the alert", (recording,), "owner lookup by hand", answers=()),
        Step("senior", 2, "on-call engineer", "alert open", "checks the last deploy", (interview,), hidden_state="which deploys are risky lives in memory"),
        Step("senior", 3, "on-call engineer", "deploy checked", "picks the failing service", (trace,), "context switching across three tools", answers=("checkout", "payments", "search", "other")),
        Step("senior", 4, "incident commander", "service named", "approves mitigation", (runbook,), authority="only the commander may approve production writes", answers=("approve", "reject")),
        Step("senior", 5, "on-call engineer", "deploy record missing", "asks in team chat who shipped last", (interview,), "waits for a reply", "deploy ownership lives in chat", branch_from=2),
        Step("junior", 1, "on-call engineer", "alert fires", "opens the alert", (recording,)),
        Step("junior", 2, "on-call engineer", "alert open", "escalates to a senior", (guess,), "handoff delay", answers=("escalate", "handle")),
        Step("junior", 3, "on-call engineer", "senior joins", "picks the failing service", (trace,), answers=("checkout", "payments", "search", "other")),
    ]


def main() -> None:
    steps = example()
    report = audit(steps)
    print(f"STATUS {report['status']}  direct_or_artifact_ratio={report['direct_or_artifact_ratio']}")
    for key in ("issues", "weakly_evidenced_steps", "friction", "hidden_state", "authority_boundaries", "exceptions"):
        print(f"\n{key.upper()}")
        for line in report[key] or ["(none)"]:
            print(f"  - {line}")
    print("\nVARIANTS (kept separate, not averaged)")
    for line in divergence(steps, "senior", "junior"):
        print(f"  - {line}")
    print("\nDECISION POINTS FOUND IN THE WORKFLOW")
    for point in decision_points(steps):
        print(f"  - {point['step']:<9} {point['decision']:<26} {point['owner']}")
    print("\nEVIDENCE FILE (excerpt)")
    print(json.dumps({"direct_or_artifact_ratio": report["direct_or_artifact_ratio"], "weak": report["weakly_evidenced_steps"]}, indent=2))


if __name__ == "__main__":
    main()
