from __future__ import annotations

import dataclasses
import json
import math
import re
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

RUBRIC: dict[str, tuple[str, list[str]]] = {
    "problem_fit": ("Did the change solve the task as stated, not a nearby task?",
                    ["solves a different problem", "partly solves it", "solves the stated task"]),
    "scope_discipline": ("Were edits confined to the scope contract?",
                         ["forbidden paths edited", "off-scope edits", "inside the contract"]),
    "assumptions": ("Are hidden assumptions written down where a reviewer can see them?",
                    ["contradicted by the diff", "none recorded", "recorded and reviewable"]),
    "verification_quality": ("Does the acceptance evidence prove the goal, not a weaker claim?",
                             ["no trustworthy evidence", "generic checks only", "focused check proves the goal"]),
    "handoff_readiness": ("Can the next session resume cleanly from the recorded state?",
                          ["no next action", "task left open", "closed with a next action"]),
}
FAST_PASS_TOTAL = 8.5
FAST_PASS_MIN_CONFIDENCE = 0.75
REJECT_BELOW_LEVEL = 0.5
REJECT_MIN_CONFIDENCE = 0.8
AUDIT_EVERY_NTH_FAST_PASS = 3
COST_UNITS = {"system_one": 1, "llm": 100}
CALIBRATION_FLOOR = 0.8


@dataclass(frozen=True)
class ReviewerInputs:
    task_id: str
    goal: str
    touched: tuple[str, ...]
    diff_text: str
    assumptions: tuple[str, ...]
    acceptance: tuple[str, ...]
    exits: tuple[int | None, ...]
    gate_passed: bool
    gate_findings: tuple[str, ...]
    active_task: str | None
    next_action: str


@dataclass
class Review:
    task_id: str
    route: str
    verdict: str
    total: float
    cost_units: int
    scores: dict[str, float] = field(default_factory=dict)
    citations: dict[str, str] = field(default_factory=dict)


def keywords(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z]+", text.lower()) if len(w) > 4}


def perceived_levels(inputs: ReviewerInputs) -> dict[str, tuple[float, float]]:
    goal = keywords(inputs.goal)
    seen = keywords(" ".join(inputs.touched) + " " + inputs.diff_text)
    fit = 2 * len(goal & seen) / max(1, len(goal))
    if "scope.forbidden" in inputs.gate_findings:
        scope = 0.0
    elif "scope.off_scope" in inputs.gate_findings:
        scope = 1.0
    else:
        scope = 2.0
    assumptions = (2.0, 3.0) if inputs.assumptions else (1.0, 0.8)
    focused = any("::" in cmd or "tests." in cmd for cmd in inputs.acceptance)
    if not inputs.exits or any(code is None for code in inputs.exits):
        verification = (0.0, 3.0)
    elif focused and inputs.exits[-1] == 0:
        verification = (2.0, 3.0)
    else:
        verification = (1.0, 1.5)
    if inputs.next_action and not inputs.active_task:
        handoff = 2.0
    elif inputs.next_action:
        handoff = 1.0
    else:
        handoff = 0.0
    return {"problem_fit": (fit, 2.5), "scope_discipline": (scope, 3.0), "assumptions": assumptions,
            "verification_quality": verification, "handoff_readiness": (handoff, 3.0)}


class LocalSystemOne:
    model = "local-score-stub (same shape as jev-latest or @cf/cloudflare/clef)"

    def system_one(self, request: dict[str, Any], perceived: dict[str, tuple[float, float]]) -> dict[str, Any]:
        answers: dict[str, Any] = {}
        for qid, question in request["questions"].items():
            level, sharpness = perceived[qid]
            logits = [-sharpness * (i - level) ** 2 for i in range(len(question["criteria"]))]
            peak = max(logits)
            weights = [math.exp(x - peak) for x in logits]
            probs = [round(w / sum(weights), 3) for w in weights]
            answers[qid] = {
                "type": "score",
                "score": round(sum(i * p for i, p in enumerate(probs)), 2),
                "confidence": max(probs),
                "legend": {str(i): text for i, text in enumerate(question["criteria"])},
                "probabilities": {str(i): p for i, p in enumerate(probs)},
            }
        tokens = len(json.dumps(request)) // 4
        return {"model": self.model, "answers": answers, "usage": {"input_tokens": tokens, "output_tokens": 0}}


class StubLlmReviewer:
    def review(self, inputs: ReviewerInputs) -> tuple[dict[str, int], dict[str, str]]:
        perceived = perceived_levels(inputs)
        scores = {dim: int(round(min(2.0, max(0.0, level)))) for dim, (level, _) in perceived.items()}
        citations = {dim: f"outputs/verification/{inputs.task_id}.json" for dim in scores}
        citations["problem_fit"] = f"diff:{','.join(inputs.touched)}"
        citations["handoff_readiness"] = "agent_state.json:next_action"
        if inputs.assumptions and "ascii" in " ".join(inputs.assumptions) and "unicode" in inputs.diff_text:
            scores["assumptions"] = 0
            citations["assumptions"] = "agent_state.json:assumptions contradicts diff"
        return scores, citations


def rubric_verdict(scores: dict[str, float]) -> str:
    total = sum(scores.values())
    if total < 5 or any(round(s) == 0 for s in scores.values()):
        return "hard_fail"
    return "pass" if total >= 7 else "soft_fail"


class ReviewerAgent:
    def __init__(self) -> None:
        self.first_pass = LocalSystemOne()
        self.llm = StubLlmReviewer()
        self.fast_passes = 0

    def request(self, inputs: ReviewerInputs) -> dict[str, Any]:
        questions = {dim: {"type": "score", "instructions": q, "criteria": levels} for dim, (q, levels) in RUBRIC.items()}
        state = {"goal": inputs.goal, "touched": list(inputs.touched), "diff": inputs.diff_text,
                 "assumptions": list(inputs.assumptions), "acceptance": list(inputs.acceptance),
                 "gate_findings": list(inputs.gate_findings), "next_action": inputs.next_action}
        return {"model": "jev-latest", "state": state, "questions": questions}

    def review(self, inputs: ReviewerInputs) -> Review:
        if not inputs.gate_passed:
            return Review(inputs.task_id, "refused: verification gate is not green", "not_reviewed", 0.0, 0)
        response = self.first_pass.system_one(self.request(inputs), perceived_levels(inputs))
        answers = response["answers"]
        scores = {dim: a["score"] for dim, a in answers.items()}
        total = round(sum(scores.values()), 2)
        weakest = min(a["confidence"] for a in answers.values())
        cost = COST_UNITS["system_one"]
        rejects = [d for d, a in answers.items()
                   if a["score"] < REJECT_BELOW_LEVEL and a["confidence"] >= REJECT_MIN_CONFIDENCE]
        if rejects:
            return Review(inputs.task_id, f"system_one_reject({','.join(rejects)})", "hard_fail", total, cost, scores)
        if total >= FAST_PASS_TOTAL and weakest >= FAST_PASS_MIN_CONFIDENCE:
            self.fast_passes += 1
            if self.fast_passes % AUDIT_EVERY_NTH_FAST_PASS:
                return Review(inputs.task_id, "system_one_fast_pass", "pass", total, cost, scores)
            route = "audit_sample -> llm"
        else:
            route = f"escalate -> llm (weakest confidence {weakest})"
        llm_scores, citations = self.llm.review(inputs)
        return Review(inputs.task_id, route, rubric_verdict(llm_scores), float(sum(llm_scores.values())),
                      cost + COST_UNITS["llm"], dict(llm_scores), citations)


def case(task_id: str, touched: list[str], diff: str, *, assumptions: tuple[str, ...] = (),
         acceptance: tuple[str, ...] = ("python3 -m unittest tests.test_signup",), exits: tuple = (0,),
         gate_passed: bool = True, findings: tuple[str, ...] = (), active: str | None = None,
         next_action: str = "pick next task from board") -> ReviewerInputs:
    goal = "add password validation to signup handler"
    return ReviewerInputs(task_id, goal, tuple(touched), diff, assumptions, acceptance, exits,
                          gate_passed, findings, active, next_action)


def calibration_set() -> list[tuple[ReviewerInputs, str]]:
    good = ["app/signup.py", "tests/test_signup.py"]
    diff = "validation rejects short password in signup handler"
    return [
        (case("T-101", good, diff, assumptions=("email and password only",)), "pass"),
        (case("T-102", ["docs/api.md"], "document endpoint", findings=("scope.off_scope",),
              active="T-102", next_action=""), "hard_fail"),
        (case("T-103", good, diff, assumptions=("min length 8",), findings=("scope.forbidden",)), "hard_fail"),
        (case("T-104", good, diff, acceptance=("pytest",)), "soft_fail"),
        (case("T-105", good, diff, assumptions=("ascii passwords only",)), "pass"),
        (case("T-106", good, diff, assumptions=("min length 8",), exits=(1, None)), "hard_fail"),
        (case("T-107", good, diff + " normalizes unicode", assumptions=("ascii passwords only",)), "hard_fail"),
        (case("T-108", good + ["README.md"], diff, assumptions=("min length 8",),
              findings=("scope.off_scope",), active="T-108"), "pass"),
        (case("T-109", good, diff, gate_passed=False), "not_reviewed"),
    ]


def main() -> None:
    reviewer = ReviewerAgent()
    labelled = calibration_set()
    agree, cost = 0, 0
    print(f"first pass: {reviewer.first_pass.model}\n")
    print(f"{'task':6} {'expected':12} {'verdict':12} {'total':>5} {'cost':>4}  route")
    with tempfile.TemporaryDirectory() as tmp:
        out_dir = Path(tmp) / "outputs" / "review"
        out_dir.mkdir(parents=True)
        for inputs, expected in labelled:
            result = reviewer.review(inputs)
            agree += result.verdict == expected
            cost += result.cost_units
            (out_dir / f"{result.task_id}.json").write_text(json.dumps(asdict(result), indent=2))
            print(f"{result.task_id:6} {expected:12} {result.verdict:12} {result.total:5} {result.cost_units:4}  {result.route}")
        written = sorted(p.name for p in out_dir.iterdir())
    llm_only = sum(COST_UNITS["llm"] for inputs, _ in labelled if inputs.gate_passed)
    rate = agree / len(labelled)
    print(f"\nagreement with labelled verdicts: {agree}/{len(labelled)} ({rate:.0%}); "
          f"ship rubric: {'yes' if rate >= CALIBRATION_FLOOR else 'no, revise anchors first'}")
    print(f"cost units: cascade={cost} vs llm-only={llm_only} ({1 - cost / llm_only:.0%} saved)")
    print(f"reports written: {written}")
    try:
        setattr(labelled[0][0], "touched", ("app/signup.py", "patched_by_reviewer.py"))
    except dataclasses.FrozenInstanceError:
        print("reviewer write attempt on builder artifacts: rejected (inputs are frozen)")
    question = reviewer.request(labelled[0][0])["questions"]["verification_quality"]
    print("\nscore question sent to the System One first pass:\n" + json.dumps(question, indent=2))


if __name__ == "__main__":
    main()
