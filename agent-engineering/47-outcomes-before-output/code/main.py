from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field

SOLUTION_TERMS = [
    "assistant",
    "chatbot",
    "copilot",
    "agent",
    "dashboard",
    "summary",
    "vector database",
    "rag",
    "fine-tune",
    "llm",
    "gpt",
    "gemini",
    "clef",
    "jev",
    "decision model",
    "mcp server",
    "langgraph",
]

MEASURABLE = re.compile(r"\d|within|under|at most|at least|before|without")


@dataclass(frozen=True)
class Constraint:
    text: str
    reason: str = ""


@dataclass(frozen=True)
class Decision:
    question: str
    answers: tuple[str, ...]
    reversible: bool


@dataclass
class OutcomeFrame:
    user: str
    situation: str
    current_behavior: str
    desired_outcome: str
    constraints: list[Constraint]
    non_goals: list[str]
    proposed_output: str = ""
    decisions: list[Decision] = field(default_factory=list)


def leaked_terms(text: str, proposed_output: str) -> list[str]:
    lowered = text.lower()
    found = [term for term in SOLUTION_TERMS if re.search(rf"\b{re.escape(term)}\b", lowered)]
    if proposed_output and proposed_output.lower() in lowered:
        found.append(proposed_output.lower())
    return sorted(set(found))


def validate(frame: OutcomeFrame) -> list[str]:
    issues: list[str] = []
    for name in ("user", "situation", "current_behavior", "desired_outcome"):
        if not getattr(frame, name).strip():
            issues.append(f"{name} is empty")
    if not frame.constraints:
        issues.append("constraints are empty")
    if not frame.non_goals:
        issues.append("non-goals are empty")
    leaks = leaked_terms(frame.desired_outcome, frame.proposed_output)
    if leaks:
        issues.append(f"desired outcome names a solution: {leaks}")
    if frame.desired_outcome and not MEASURABLE.search(frame.desired_outcome.lower()):
        issues.append("desired outcome has no observable bound (time, count, or condition)")
    for constraint in frame.constraints:
        if leaked_terms(constraint.text, "") and not constraint.reason:
            issues.append(f"constraint names technology without a reason: {constraint.text!r}")
    return issues


def classify(decision: Decision) -> str:
    if not decision.reversible:
        return "human (irreversible or authority-bearing)"
    if decision.answers and decision.answers != ("open",):
        return "System One candidate (bounded answers)"
    return "System Two (open-ended generation)"


def assess(frame: OutcomeFrame) -> dict:
    issues = validate(frame)
    return {
        "status": "ready-to-discover" if not issues else "needs-framing",
        "issues": issues,
        "decision_inventory": [{"question": item.question, "owner": classify(item)} for item in frame.decisions],
        "next_question": f"What observation would show the {frame.user} reached the outcome, and what would disprove it?",
    }


def good_frame() -> OutcomeFrame:
    return OutcomeFrame(
        user="on-call engineer",
        situation="a production alert fires during an incident",
        current_behavior="opens three dashboards and asks in chat before finding the affected service",
        desired_outcome="identifies the failing service and a safe next action within two minutes",
        constraints=[
            Constraint("diagnosis stays read-only"),
            Constraint("existing audit events remain authoritative"),
            Constraint("runs inside the existing MCP server fleet", "security already reviewed it; no new network egress allowed"),
        ],
        non_goals=["automatic remediation", "a new alert-routing system", "replacing the incident commander"],
        proposed_output="incident assistant",
        decisions=[
            Decision("Which service is failing?", ("checkout", "payments", "search", "other"), True),
            Decision("Is this alert a duplicate of an open incident?", ("yes", "no"), True),
            Decision("What should the incident summary say?", ("open",), True),
            Decision("Roll back the last deploy?", ("yes", "no"), False),
        ],
    )


def leaky_frame() -> OutcomeFrame:
    frame = good_frame()
    frame.desired_outcome = "engineers use the Clef-powered incident assistant for every alert"
    frame.constraints = [Constraint("must use LangGraph")]
    return frame


def vague_frame() -> OutcomeFrame:
    return OutcomeFrame(
        user="support team",
        situation="",
        current_behavior="answers tickets by hand",
        desired_outcome="support feels better",
        constraints=[],
        non_goals=[],
    )


def main() -> None:
    for label, frame in (("GOOD", good_frame()), ("LEAKY", leaky_frame()), ("VAGUE", vague_frame())):
        result = assess(frame)
        print(f"== {label}: {result['status']}")
        print(f"   outcome: {frame.desired_outcome}")
        for issue in result["issues"]:
            print(f"   ! {issue}")
        for row in result["decision_inventory"]:
            print(f"   decision: {row['question']:<48} -> {row['owner']}")
        print(f"   next: {result['next_question']}")
    print("\nOUTCOME FRAME (keep this file)")
    kept = asdict(good_frame())
    kept["constraints"] = [item["text"] for item in kept["constraints"]]
    kept.pop("decisions")
    print(json.dumps(kept, indent=2))


if __name__ == "__main__":
    main()
