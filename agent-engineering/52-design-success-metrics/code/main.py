from __future__ import annotations

import json
import random
import statistics
from dataclasses import asdict, dataclass

KINDS = ("outcome", "guardrail", "counter")
DIRECTIONS = ("at_most", "at_least")
REQUIRED_FIELDS = ("name", "kind", "direction", "window", "source", "population")

PRICE_PER_MILLION_INPUT = 0.038
TOKENS_PER_DECISION = 900
COST_WRONG_AUTO = 40.0
COST_HUMAN_REVIEW = 3.0
SECONDS_AUTO = 25.0
SECONDS_HUMAN = 150.0


@dataclass(frozen=True)
class MetricSpec:
    name: str
    kind: str
    direction: str
    threshold: float | None
    window: str
    source: str
    population: str


@dataclass(frozen=True)
class Decision:
    alert_id: int
    probability: float
    correct: bool


def validate_plan(plan: list[MetricSpec]) -> list[str]:
    issues = []
    for metric in plan:
        for name in REQUIRED_FIELDS:
            if not str(getattr(metric, name)).strip():
                issues.append(f"{metric.name or '?'}: missing {name}")
        if metric.kind not in KINDS:
            issues.append(f"{metric.name}: unknown kind {metric.kind!r}")
        if metric.direction not in DIRECTIONS:
            issues.append(f"{metric.name}: unknown direction {metric.direction!r}")
        if metric.threshold is None:
            issues.append(f"{metric.name}: no threshold, so it cannot drive a decision")
    kinds = {metric.kind for metric in plan}
    if "outcome" not in kinds:
        issues.append("plan has no outcome metric")
    if "guardrail" not in kinds:
        issues.append("plan has no guardrail metric: a fast but unsafe result would pass")
    if "counter" not in kinds:
        issues.append("plan has no counter-metric: cost shifted to another role stays invisible")
    return issues


def replay_log(overconfidence: float, size: int = 400, seed: int = 52) -> list[Decision]:
    rng = random.Random(seed)
    log = []
    for alert_id in range(size):
        probability = round(min(0.995, max(0.34, rng.betavariate(25.0, 1.0))), 3)
        true_accuracy = probability ** overconfidence
        log.append(Decision(alert_id, probability, rng.random() < true_accuracy))
    return log


def expected_calibration_error(log: list[Decision], bins: int = 10) -> float:
    total = 0.0
    for index in range(bins):
        low, high = index / bins, (index + 1) / bins
        members = [item for item in log if low <= item.probability < high or (index == bins - 1 and item.probability == 1.0)]
        if not members:
            continue
        confidence = statistics.fmean(item.probability for item in members)
        accuracy = statistics.fmean(1.0 if item.correct else 0.0 for item in members)
        total += len(members) / len(log) * abs(confidence - accuracy)
    return round(total, 4)


def brier_score(log: list[Decision]) -> float:
    return round(statistics.fmean((item.probability - (1.0 if item.correct else 0.0)) ** 2 for item in log), 4)


def model_cost_per_decision() -> float:
    return TOKENS_PER_DECISION * PRICE_PER_MILLION_INPUT / 1_000_000


def operate(log: list[Decision], threshold: float) -> dict:
    automated = [item for item in log if item.probability >= threshold]
    abstained = len(log) - len(automated)
    wrong_auto = sum(not item.correct for item in automated)
    business_cost = wrong_auto * COST_WRONG_AUTO + abstained * COST_HUMAN_REVIEW
    seconds = [SECONDS_AUTO if item.correct else SECONDS_HUMAN for item in automated] + [SECONDS_HUMAN] * abstained
    return {
        "threshold": threshold,
        "abstain_rate": round(abstained / len(log), 3),
        "auto_precision": round((len(automated) - wrong_auto) / len(automated), 3) if automated else None,
        "wrong_auto_actions": wrong_auto,
        "cost_per_decision": round(business_cost / len(log) + model_cost_per_decision(), 4),
        "median_identification_seconds": statistics.median(seconds),
        "reviews_per_shift": round(abstained / len(log) * 60, 1),
    }


def pick_threshold(log: list[Decision]) -> tuple[float, list[dict]]:
    sweep = [operate(log, round(0.50 + step * 0.01, 2)) for step in range(50)]
    best = min(sweep, key=lambda row: (row["cost_per_decision"], -row["threshold"]))
    return best["threshold"], sweep


def check(metric: MetricSpec, observed: dict) -> str:
    value = observed.get(metric.name)
    if value is None or metric.threshold is None:
        return "missing"
    if metric.direction == "at_most":
        return "pass" if value <= metric.threshold else "fail"
    return "pass" if value >= metric.threshold else "fail"


def decide(plan: list[MetricSpec], observed: dict) -> tuple[str, list[tuple[str, str, object]]]:
    rows = [(metric.name, check(metric, observed), observed.get(metric.name)) for metric in plan]
    verdicts = {metric.name: status for metric, (_, status, _) in zip(plan, rows)}
    guardrail_failed = any(verdicts[metric.name] == "fail" for metric in plan if metric.kind == "guardrail")
    if guardrail_failed:
        return "fail: a guardrail broke, stop regardless of the outcome metrics", rows
    if "missing" in verdicts.values():
        return "ambiguous: a metric has no value, collect it before deciding", rows
    if all(status == "pass" for status in verdicts.values()):
        return "pass: expand to the next stage", rows
    return "ambiguous: outcome or counter-metric missed, revise and re-run on a larger replay", rows


def measurement_plan() -> list[MetricSpec]:
    window = "400 replayed alerts, last 90 days"
    population = "on-call engineers in the pilot rotation"
    return [
        MetricSpec("median_identification_seconds", "outcome", "at_most", 120, window, "replay event log", population),
        MetricSpec("auto_precision", "guardrail", "at_least", 0.97, window, "labeled replay set", population),
        MetricSpec("expected_calibration_error", "guardrail", "at_most", 0.05, window, "decision log with probabilities", population),
        MetricSpec("production_writes", "guardrail", "at_most", 0, window, "audit log", population),
        MetricSpec("abstain_rate", "counter", "at_most", 0.30, window, "decision log", population),
        MetricSpec("cost_per_decision", "counter", "at_most", 2.00, window, "cost matrix x decision log", population),
    ]


def main() -> None:
    plan = measurement_plan()
    print("PLAN CHECK:", validate_plan(plan) or "valid (decided before any result exists)")
    without_guardrails = [metric for metric in plan if metric.kind != "guardrail"]
    print("PLAN WITHOUT GUARDRAILS:", validate_plan(without_guardrails))

    candidates = {"candidate A (calibrated)": 1.0, "candidate B (overconfident)": 4.0}
    reports = {}
    for label, overconfidence in candidates.items():
        log = replay_log(overconfidence)
        chosen, sweep = pick_threshold(log)
        print(f"\n== {label}: {len(log)} replayed decisions")
        print(f"  expected calibration error = {expected_calibration_error(log)}")
        print(f"  brier score                = {brier_score(log)}")
        print(f"  model cost per decision    = ${model_cost_per_decision():.6f}")
        print(f"  cost-matrix sweep (wrong auto ${COST_WRONG_AUTO:.0f}, human review ${COST_HUMAN_REVIEW:.0f})")
        print("    thr   abstain  precision  wrong  $/decision")
        for row in sweep[::10] + [operate(log, chosen)]:
            marker = "  <- min expected cost" if row["threshold"] == chosen else ""
            print(f"    {row['threshold']:.2f}  {row['abstain_rate']:<7}  {row['auto_precision']!s:<9}  {row['wrong_auto_actions']:<5}  {row['cost_per_decision']:<10}{marker}")
        observed = operate(log, chosen)
        observed["expected_calibration_error"] = expected_calibration_error(log)
        observed["production_writes"] = 0
        verdict, rows = decide(plan, observed)
        print(f"  decision rule at threshold {chosen}:")
        for name, status, value in rows:
            print(f"    {status:<7} {name:<32} observed={value}")
        print(f"  => {verdict}")
        reports[label] = {"threshold": chosen, "observed": observed, "verdict": verdict}

    observed_missing = dict(reports["candidate A (calibrated)"]["observed"])
    observed_missing.pop("expected_calibration_error")
    print(f"\nIF CALIBRATION WAS NOT LOGGED FOR A => {decide(plan, observed_missing)[0]}")

    print("\nMEASUREMENT REPORT (candidate A)")
    print(json.dumps({"plan_fields": list(asdict(plan[0])), **reports["candidate A (calibrated)"]}, indent=2))


if __name__ == "__main__":
    main()
