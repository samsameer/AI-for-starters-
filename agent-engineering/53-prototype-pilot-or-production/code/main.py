from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field

CONTROLS = {
    "prototype": ["isolated sandbox", "synthetic or redacted data only", "no credentials to production", "written learning question", "delete-by date"],
    "pilot": ["named audience", "human owner", "bounded duration", "bounded authority", "audit log", "rollback switch", "outcome and guardrail thresholds", "expand/revise/stop criteria"],
    "production": ["SLO", "on-call rotation", "security and privacy review", "cost and capacity budget", "rollback and recovery", "continuous monitoring", "retirement path"],
}


@dataclass(frozen=True)
class StageContext:
    name: str
    unknown: str
    needs_real_users: bool
    needs_real_data: bool
    consequence: int
    operations_ready: bool
    owner: str = ""


@dataclass(frozen=True)
class DeployedSystem:
    name: str
    declared_stage: str
    has_real_users: bool
    reads_production_data: bool
    can_write: bool
    owner: str
    controls: tuple[str, ...]


@dataclass(frozen=True)
class GateCriteria:
    min_labeled: int
    min_auto_precision: float
    max_calibration_error: float
    max_abstain_rate: float
    max_cost_per_decision: float
    max_guardrail_breaches: int = 0


@dataclass(frozen=True)
class RolloutStage:
    name: str
    traffic_share: float
    authority: str
    gate: GateCriteria


@dataclass
class Observation:
    labeled: int
    auto_precision: float
    calibration_error: float
    abstain_rate: float
    cost_per_decision: float
    guardrail_breaches: int
    notes: list[str] = field(default_factory=list)


def choose_stage(context: StageContext) -> dict:
    if not (context.needs_real_users or context.needs_real_data):
        stage = "prototype"
    elif context.consequence >= 3 or not context.operations_ready:
        stage = "pilot"
    else:
        stage = "production"
    warnings = []
    if stage != "prototype" and not context.owner:
        warnings.append("no human owner: real users or data without ownership is stage drift waiting to happen")
    return {"project": context.name, "unknown": context.unknown, "stage": stage, "required_controls": CONTROLS[stage], "warnings": warnings}


def detect_drift(system: DeployedSystem) -> list[str]:
    findings = []
    if system.declared_stage == "prototype":
        if system.has_real_users:
            findings.append("prototype has real users")
        if system.reads_production_data:
            findings.append("prototype reads production data")
        if system.can_write:
            findings.append("prototype holds write authority")
    missing = [control for control in CONTROLS[system.declared_stage] if control not in system.controls]
    if system.declared_stage != "prototype" and missing:
        findings.append(f"{system.declared_stage} is missing controls: {missing}")
    if (system.has_real_users or system.can_write) and not system.owner:
        findings.append("no accountable owner")
    return findings


def evaluate_gate(stage: RolloutStage, observed: Observation) -> tuple[str, list[str]]:
    gate = stage.gate
    if observed.guardrail_breaches > gate.max_guardrail_breaches:
        return "rollback", [f"guardrail breaches {observed.guardrail_breaches} > {gate.max_guardrail_breaches}"]
    misses = []
    if observed.labeled < gate.min_labeled:
        misses.append(f"labeled {observed.labeled} < {gate.min_labeled}")
    if observed.auto_precision < gate.min_auto_precision:
        misses.append(f"auto precision {observed.auto_precision} < {gate.min_auto_precision}")
    if observed.calibration_error > gate.max_calibration_error:
        misses.append(f"calibration error {observed.calibration_error} > {gate.max_calibration_error}")
    if observed.abstain_rate > gate.max_abstain_rate:
        misses.append(f"abstain rate {observed.abstain_rate} > {gate.max_abstain_rate}")
    if observed.cost_per_decision > gate.max_cost_per_decision:
        misses.append(f"cost/decision {observed.cost_per_decision} > {gate.max_cost_per_decision}")
    if observed.auto_precision < gate.min_auto_precision - 0.05:
        return "rollback", misses
    return ("promote", []) if not misses else ("hold", misses)


def rollout_plan() -> list[RolloutStage]:
    return [
        RolloutStage("shadow", 1.00, "log only; humans act as today", GateCriteria(300, 0.95, 0.06, 0.40, 2.50)),
        RolloutStage("assist", 0.10, "show suggestion; human confirms", GateCriteria(500, 0.96, 0.05, 0.35, 2.20)),
        RolloutStage("auto-low-risk", 0.25, "auto-route above threshold; read-only", GateCriteria(1000, 0.97, 0.05, 0.30, 2.00)),
        RolloutStage("auto-all", 1.00, "auto-route above threshold; abstain to human", GateCriteria(2000, 0.97, 0.04, 0.25, 1.80)),
    ]


def run_rollout(plan: list[RolloutStage], observations: list[Observation]) -> list[dict]:
    history = []
    index = 0
    for observed in observations:
        stage = plan[index]
        verdict, reasons = evaluate_gate(stage, observed)
        history.append({"stage": stage.name, "traffic": stage.traffic_share, "authority": stage.authority, "verdict": verdict, "reasons": reasons, "notes": observed.notes})
        if verdict == "promote":
            index += 1
            if index == len(plan):
                break
        elif verdict == "rollback":
            index = max(0, index - 1)
    return history


def example_contexts() -> list[StageContext]:
    return [
        StageContext("alert service picker", "can a decision model name the service from alert text at all?", False, False, 1, False),
        StageContext("alert service picker", "do engineers act on suggestions during real incidents?", True, True, 3, False, "sre-lead"),
        StageContext("ticket tagger", "does auto-tagging hold up at full volume?", True, True, 2, True, "support-ops"),
        StageContext("refund approver", "will customers accept automatic refunds?", True, True, 5, True),
    ]


def example_observations() -> list[Observation]:
    return [
        Observation(320, 0.962, 0.031, 0.18, 1.42, 0, ["two weeks of shadow logs"]),
        Observation(540, 0.958, 0.044, 0.22, 1.51, 0, ["precision dipped on a new service name"]),
        Observation(610, 0.971, 0.036, 0.20, 1.33, 0, ["added 70 corrected labels; re-picked threshold"]),
        Observation(1150, 0.912, 0.071, 0.17, 2.90, 1, ["upstream alert format changed; one wrong page sent"]),
        Observation(720, 0.974, 0.030, 0.19, 1.30, 0, ["parser fixed; drift alarm added"]),
        Observation(1240, 0.976, 0.029, 0.21, 1.21, 0, ["stable for three weeks"]),
        Observation(2300, 0.978, 0.027, 0.18, 1.15, 0, ["full traffic, on-call owns it"]),
    ]


def main() -> None:
    print("STAGE CHOICE")
    for context in example_contexts():
        result = choose_stage(context)
        print(f"  {result['stage']:<10} {context.name:<22} unknown: {context.unknown}")
        for warning in result["warnings"]:
            print(f"             ! {warning}")

    print("\nSTAGE DRIFT CHECK")
    systems = [
        DeployedSystem("triage-demo", "prototype", True, True, False, "", ("isolated sandbox",)),
        DeployedSystem("service-picker-pilot", "pilot", True, True, False, "sre-lead", tuple(CONTROLS["pilot"])),
    ]
    for system in systems:
        print(f"  {system.name:<22} {detect_drift(system) or 'stage matches reality'}")

    print("\nSTAGED ROLLOUT WITH DECISION-MODEL GATES")
    for row in run_rollout(rollout_plan(), example_observations()):
        print(f"  {row['stage']:<14} traffic={row['traffic']:<4} -> {row['verdict']:<8} {'; '.join(row['reasons']) or 'all gates met'}")
        print(f"  {'':<14} note: {row['notes'][0]}")

    print("\nPILOT GATE (keep with the stage decision)")
    print(json.dumps(asdict(rollout_plan()[1]), indent=2))


if __name__ == "__main__":
    main()
