from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date, timedelta

TODAY = date(2026, 10, 13)
HOLDOUT_SHARE = 0.3
MIN_EVAL_ROWS = 4
MIN_TRAIN_ROWS = 6
SEVERITY_FAST_TRACK = 5
FAST_TRACK_PRIORITY = 100

ROUTES = [
    ("runtime", ("timeout", "retry storm", "rate limit", "unavailable")),
    ("policy", ("unsafe", "authority", "permission", "wrote to", "destructive")),
    ("context", ("stale", "missing context", "duplicate work", "outdated")),
    ("evaluation", ("false positive", "regression", "wrong result", "misrouted")),
]

VERIFY = {
    "decision_dataset": "row lands in the eval holdout or training pool; threshold re-picked on the new eval",
    "evaluation": "new eval case fails on the old build and passes on the fix",
    "context": "replay shows the fresh fact retrieved for the same input",
    "policy": "replayed action is blocked by the permission layer",
    "runtime": "fault-injection run stays inside the timeout and retry budget",
    "backlog": "shaped item with outcome, owner and decision date",
}

ARTIFACT = {
    "decision_dataset": "datasets/decisions/*.jsonl",
    "evaluation": "evals/cases/",
    "context": "retrieval sources and AGENTS.md",
    "policy": "permission policy",
    "runtime": "runtime config: timeouts, retries, circuit breakers",
    "backlog": "product backlog",
}


@dataclass(frozen=True)
class DecisionCorrection:
    state: str
    question: str
    labels: tuple[str, ...]
    model_choice: str
    model_probability: float
    human_choice: str


@dataclass(frozen=True)
class Signal:
    source: str
    text: str
    severity: int
    frequency: int
    owner: str
    correction: DecisionCorrection | None = None


def route(signal: Signal) -> str:
    if signal.correction is not None:
        return "decision_dataset"
    lowered = signal.text.lower()
    for layer, words in ROUTES:
        if any(word in lowered for word in words):
            return layer
    return "backlog"


def fingerprint(text: str) -> str:
    return hashlib.sha256(text.lower().strip().encode()).hexdigest()[:10]


def split_for(row_key: str) -> str:
    bucket = int(hashlib.sha256(row_key.encode()).hexdigest(), 16) % 100
    return "eval_holdout" if bucket < HOLDOUT_SHARE * 100 else "train_pool"


def to_rows(correction: DecisionCorrection) -> dict:
    key = fingerprint(correction.state + "|" + correction.question)
    split = split_for(key)
    eval_row = {
        "id": key,
        "state": correction.state,
        "question": {"type": "choice", "instructions": correction.question, "criteria": {label: None for label in correction.labels}},
        "expected": correction.human_choice,
    }
    rl_row = {
        "id": key,
        "state": correction.state,
        "question": correction.question,
        "rewards": {label: (1.0 if label == correction.human_choice else -1.0 if label == correction.model_choice else 0.0) for label in correction.labels},
        "model_was_confident": correction.model_probability >= 0.8,
    }
    return {"split": split, "eval_row": eval_row, "rl_row": rl_row}


def ratchet(signals: list[Signal]) -> dict:
    actions: dict[str, dict] = {}
    holdout, train_pool = [], []
    for signal in signals:
        layer = route(signal)
        if signal.correction is not None:
            rows = to_rows(signal.correction)
            target = holdout if rows["split"] == "eval_holdout" else train_pool
            if all(existing["id"] != rows["eval_row"]["id"] for existing in holdout + train_pool):
                target.append(rows["eval_row"] if rows["split"] == "eval_holdout" else rows["rl_row"])
            key = fingerprint(layer + signal.correction.question)
        else:
            key = fingerprint(layer + signal.text)
        if key in actions:
            actions[key]["frequency"] += signal.frequency
            actions[key]["severity"] = max(actions[key]["severity"], signal.severity)
            continue
        actions[key] = {
            "layer": layer,
            "signal": signal.text,
            "source": signal.source,
            "owner": signal.owner,
            "artifact": ARTIFACT[layer],
            "verify": VERIFY[layer],
            "severity": signal.severity,
            "frequency": signal.frequency,
        }
    ordered = []
    for action in actions.values():
        action["priority"] = action["severity"] * action["frequency"]
        if action["severity"] >= SEVERITY_FAST_TRACK:
            action["priority"] = max(action["priority"], FAST_TRACK_PRIORITY)
        action["review_on"] = (TODAY + timedelta(days=30 if action["severity"] >= 4 else 90)).isoformat()
        action["retire_when"] = "no recurrence across two review windows and a lower-layer control exists"
        ordered.append(action)
    ordered.sort(key=lambda item: (-item["priority"], item["layer"]))
    return {"actions": ordered, "eval_holdout": holdout, "train_pool": train_pool}


def fine_tune_gate(holdout: list[dict], train_pool: list[dict]) -> str:
    holdout_ids = {row["id"] for row in holdout}
    leaked = [row["id"] for row in train_pool if row["id"] in holdout_ids]
    if leaked:
        return f"blocked: {len(leaked)} training rows leak into the eval holdout"
    if len(holdout) < MIN_EVAL_ROWS:
        return f"wait: eval holdout has {len(holdout)} rows, need {MIN_EVAL_ROWS} before any fine-tune can be judged"
    if len(train_pool) < MIN_TRAIN_ROWS:
        return f"wait: training pool has {len(train_pool)} rows, need {MIN_TRAIN_ROWS}; re-pick thresholds instead"
    return "ready: submit the training pool, then accept the tuned model only if it beats the base on the holdout"


def example_signals() -> list[Signal]:
    labels = ("billing", "technical", "account", "other")
    question = "Which team should handle this ticket?"
    tickets = [
        ("Card charged twice after plan upgrade", "technical", 0.71, "billing"),
        ("SSO login loops back to the sign-in page", "account", 0.64, "technical"),
        ("Invoice PDF shows the old company address", "technical", 0.58, "billing"),
        ("Cannot add a teammate, seat limit message", "billing", 0.83, "account"),
        ("Webhook retries hit our endpoint 40 times", "other", 0.52, "technical"),
        ("Refund not visible on the statement", "technical", 0.77, "billing"),
        ("2FA codes arrive after they expire", "other", 0.49, "technical"),
        ("Export to CSV drops unicode names", "billing", 0.55, "technical"),
        ("Need to transfer workspace ownership", "technical", 0.68, "account"),
        ("Tax ID missing on receipts", "account", 0.61, "billing"),
        ("API returns 500 on bulk import", "billing", 0.66, "technical"),
        ("Card charged twice after plan upgrade", "technical", 0.71, "billing"),
    ]
    signals = [
        Signal("support override", f"misrouted ticket: {text}", 2, 1, "support-ops", DecisionCorrection(text, question, labels, model, prob, human))
        for text, model, prob, human in tickets
    ]
    signals += [
        Signal("incident", "Agent wrote to the billing DB during diagnosis without authority", 5, 1, "platform-security"),
        Signal("eval", "Regression: refund-policy answers cite the 2025 policy", 3, 4, "support-ai"),
        Signal("trace", "Tool timeout on CRM lookup causes a retry storm", 4, 6, "platform"),
        Signal("user", "Agents answer with stale plan prices", 3, 5, "support-ai"),
        Signal("user", "Customers ask for refunds in Spanish", 2, 3, "product"),
    ]
    return signals


def decision_brief(result: dict) -> dict:
    corrections = sum(1 for action in result["actions"] if action["layer"] == "decision_dataset")
    return {
        "decision_needed": "keep the router on auto above threshold, or move billing tickets back to assist mode?",
        "evidence": f"{len(result['eval_holdout']) + len(result['train_pool'])} unique human overrides, {corrections} grouped action",
        "options": ["keep auto, re-pick threshold on the grown holdout", "assist mode for billing only", "stop auto-routing"],
        "recommendation": "assist mode for billing only until the holdout reaches 200 rows",
        "decision_owner": "support-ops lead",
        "decide_by": (TODAY + timedelta(days=7)).isoformat(),
    }


def main() -> None:
    result = ratchet(example_signals())
    print("RATCHET ACTIONS (priority = severity x frequency; severity 5 is fast-tracked)")
    for action in result["actions"]:
        print(f"  p={action['priority']:<3} {action['layer']:<17} owner={action['owner']:<18} {action['signal'][:62]}")
        print(f"        change: {action['artifact']} | verify: {action['verify']}")
    print(f"\nLABELED DATA FROM CORRECTIONS: holdout={len(result['eval_holdout'])} train_pool={len(result['train_pool'])} (duplicate overrides collapsed)")
    if result["eval_holdout"]:
        print("  eval row: " + json.dumps(result["eval_holdout"][0])[:150] + "...")
    if result["train_pool"]:
        print("  rl row:   " + json.dumps(result["train_pool"][0]))
    print(f"\nFINE-TUNE GATE: {fine_tune_gate(result['eval_holdout'], result['train_pool'])}")
    print("\nDECISION BRIEF")
    print(json.dumps(decision_brief(result), indent=2))


if __name__ == "__main__":
    main()
