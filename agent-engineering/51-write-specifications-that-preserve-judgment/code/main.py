from __future__ import annotations

import json
from dataclasses import dataclass, field, replace

MODES = ("locked", "bounded", "delegated")
PROOF_LAYERS = ["unit", "wire", "journey", "replay", "audit"]
EXAMPLE_KINDS = {"normal", "edge", "failure", "forbidden"}


@dataclass(frozen=True)
class Decision:
    question: str
    mode: str
    consequence: int
    reversible: bool
    rationale: str = ""
    config_key: str = ""


@dataclass(frozen=True)
class Proof:
    claim: str
    claim_layer: str
    evidence: str
    evidence_layer: str


@dataclass(frozen=True)
class Tool:
    name: str
    writes: bool
    production: bool


@dataclass
class Specification:
    outcome: str
    invariants: list[str]
    examples: list[tuple[str, str]]
    non_goals: list[str]
    decisions: list[Decision]
    proof: list[Proof]
    tools: list[Tool] = field(default_factory=list)
    thresholds: dict[str, float] = field(default_factory=dict)


def validate(spec: Specification) -> list[str]:
    issues = []
    for name in ("outcome", "invariants", "examples", "non_goals", "decisions", "proof"):
        if not getattr(spec, name):
            issues.append(f"{name} is empty")
    kinds = {kind for kind, _ in spec.examples}
    for missing in sorted({"failure", "forbidden"} - kinds):
        issues.append(f"no {missing} example: intent at the boundary is unstated")
    for kind in kinds - EXAMPLE_KINDS:
        issues.append(f"unknown example kind {kind!r}")
    for decision in spec.decisions:
        if decision.mode not in MODES:
            issues.append(f"invalid mode {decision.mode!r} for {decision.question!r}")
            continue
        if decision.mode != "delegated" and not decision.rationale:
            issues.append(f"{decision.mode} decision lacks a rationale: {decision.question!r}")
        if (decision.consequence >= 4 or not decision.reversible) and decision.mode != "locked":
            issues.append(f"schema accepts it, product risk does not: {decision.question!r} is {decision.mode} but consequence={decision.consequence}, reversible={decision.reversible}")
        if decision.mode == "bounded" and decision.config_key and decision.config_key not in spec.thresholds:
            issues.append(f"bounded decision points to missing config key {decision.config_key!r}")
    for proof in spec.proof:
        if PROOF_LAYERS.index(proof.evidence_layer) < PROOF_LAYERS.index(proof.claim_layer):
            issues.append(f"proof too weak: {proof.evidence_layer} evidence for the {proof.claim_layer}-level claim ({proof.claim})")
    return issues


def permission_policy(spec: Specification) -> dict[str, str]:
    policy = {}
    for tool in spec.tools:
        policy[tool.name] = "always_ask" if tool.writes and tool.production else "always_allow"
    return policy


def agent_brief(spec: Specification) -> str:
    lines = [f"Outcome: {spec.outcome}", "Never violate:"]
    lines += [f"  - {item}" for item in spec.invariants]
    lines.append("You decide (explain your choice in the PR):")
    lines += [f"  - {d.question}" for d in spec.decisions if d.mode == "delegated"]
    lines.append("You decide within limits:")
    lines += [f"  - {d.question} [{d.rationale}]" for d in spec.decisions if d.mode == "bounded"]
    lines.append("Stop and ask a human:")
    lines += [f"  - {d.question}" for d in spec.decisions if d.mode == "locked"]
    lines.append("Out of scope: " + "; ".join(spec.non_goals))
    lines.append("Done means: " + "; ".join(p.evidence for p in spec.proof))
    return "\n".join(lines)


def example() -> Specification:
    return Specification(
        outcome="On-call engineers see the failing service and a safe next action within two minutes of an alert",
        invariants=["diagnosis is read-only", "every data source queried appears in the audit record", "routing thresholds live in config, never in prompts"],
        examples=[
            ("normal", "alert with deploy id d-913 resolves to checkout, owner team-cart"),
            ("edge", "alert with no deploy id falls back to the service catalog"),
            ("failure", "decision model confidence below threshold shows 'unsure' and the top three candidates"),
            ("forbidden", "suggestion to restart a pod is shown, never executed"),
        ],
        non_goals=["automatic remediation", "changing alert routing", "historical analytics"],
        decisions=[
            Decision("Which read-only source to query first?", "delegated", 1, True),
            Decision("How to structure the suggestion card?", "delegated", 1, True),
            Decision("How many sources may be queried per alert?", "bounded", 2, True, "at most 5 sources or 90 seconds", "max_sources"),
            Decision("When may the service guess be shown without 'unsure'?", "bounded", 3, True, "P(top service) >= auto_show_threshold, picked from the cost matrix", "auto_show_threshold"),
            Decision("May the system write to production?", "locked", 5, False, "production authority stays with the incident commander"),
        ],
        proof=[
            Proof("parser maps alert payloads to service ids", "unit", "unit tests on 40 payload fixtures", "unit"),
            Proof("suggestions are right on real incidents", "replay", "replay of 50 recorded incidents", "replay"),
            Proof("no production writes happen", "audit", "audit log shows zero write calls during the pilot", "audit"),
        ],
        tools=[Tool("logs.search", False, True), Tool("deploys.list", False, True), Tool("k8s.rollout_restart", True, True), Tool("notes.write", True, False)],
        thresholds={"max_sources": 5, "auto_show_threshold": 0.82},
    )


def main() -> None:
    spec = example()
    print("SPEC CHECK:", validate(spec) or "executable")
    print("\nAGENT BRIEF (drop into AGENTS.md or a Skill)\n")
    print(agent_brief(spec))
    print("\nPERMISSION POLICY")
    print(json.dumps(permission_policy(spec), indent=2))
    print("\nTHRESHOLDS (config, not prompt)")
    print(json.dumps(spec.thresholds))
    risky = replace(
        spec,
        decisions=[replace(d, mode="delegated") if "production" in d.question else d for d in spec.decisions],
        proof=spec.proof[:2] + [Proof("no production writes happen", "audit", "unit test mocks the write tool", "unit")],
    )
    print("\nMUTATED SPEC: production write delegated, audit proof replaced by a unit test")
    for issue in validate(risky):
        print(f"  ! {issue}")


if __name__ == "__main__":
    main()
