from __future__ import annotations

import json
import tempfile
from dataclasses import dataclass, field
from pathlib import Path


SURFACES = ["instructions", "state", "scope", "feedback", "verification", "review", "handoff"]

SYMPTOM_BY_SURFACE = {
    "instructions": "no definition of done, stopped before writing the acceptance test",
    "state": "second session restarted from zero and redid finished steps",
    "scope": "edited files unrelated to the task",
    "feedback": "claimed tests pass without ever running them",
    "verification": "declared success while acceptance actually fails",
    "review": "builder approved its own change",
    "handoff": "next session has no summary of what changed or what is left",
}

PRIMITIVE_BY_SURFACE = {
    "instructions": "policy + function metadata loaded at startup",
    "state": "session persistence (keyed store read every step)",
    "scope": "authorization policy per task (ACL over paths)",
    "feedback": "invocation log written to a durable queue",
    "verification": "deterministic function that fails closed",
    "review": "separate worker with read-only access to builder output",
    "handoff": "durable record emitted by a session-end trigger",
}

ALLOWED_FILES = {"app.py", "test_app.py"}


def render_handler(min_length: int) -> str:
    return "\n".join([
        "def signup(password):",
        f"    if len(password) < {min_length}:",
        "        return 400",
        "    return 201",
        "",
    ])


TEST_FILE = "\n".join([
    "def test_rejects_short_password():",
    "    assert signup('abc1234') == 400",
    "def test_accepts_long_password():",
    "    assert signup('longenough') == 201",
    "",
])


def run_tests(repo: dict[str, str]) -> tuple[int, str]:
    if "test_app.py" not in repo:
        return 5, "no tests collected"
    namespace: dict[str, object] = {}
    exec(repo["app.py"], namespace)
    exec(repo["test_app.py"], namespace)
    failures = []
    for name in sorted(k for k in namespace if k.startswith("test_")):
        try:
            namespace[name]()
        except AssertionError:
            failures.append(name)
    if failures:
        return 1, f"FAILED {failures}"
    return 0, "2 passed"


@dataclass
class RunLog:
    label: str
    surfaces: list[str]
    events: list[str] = field(default_factory=list)
    touched: list[str] = field(default_factory=list)
    declared_success: bool = False
    tests_ran: bool = False
    final_exit: int = -1
    redone_steps: int = 0
    self_approved: bool = False
    handoff_note: str = ""

    def symptoms(self) -> dict[str, str]:
        found: dict[str, str] = {}
        if "test_app.py" not in self.touched:
            found["instructions"] = SYMPTOM_BY_SURFACE["instructions"]
        if self.redone_steps:
            found["state"] = f"{SYMPTOM_BY_SURFACE['state']} ({self.redone_steps} steps)"
        off_scope = sorted(set(self.touched) - ALLOWED_FILES)
        if off_scope:
            found["scope"] = f"{SYMPTOM_BY_SURFACE['scope']}: {off_scope}"
        if self.declared_success and not self.tests_ran:
            found["feedback"] = SYMPTOM_BY_SURFACE["feedback"]
        if self.declared_success and self.final_exit != 0:
            found["verification"] = SYMPTOM_BY_SURFACE["verification"]
        if self.self_approved:
            found["review"] = SYMPTOM_BY_SURFACE["review"]
        if not self.handoff_note:
            found["handoff"] = SYMPTOM_BY_SURFACE["handoff"]
        return found


class StubModel:
    def first_draft_min_length(self) -> int:
        return 7

    def fix_from_feedback(self, output: str) -> int:
        return 8 if "test_rejects_short_password" in output else 7

    def tidy_up_targets(self) -> list[str]:
        return ["README.md", "scripts/release.sh"]


def run_session(model: StubModel, surfaces: set[str], label: str) -> RunLog:
    log = RunLog(label=label, surfaces=sorted(surfaces))
    repo = {"app.py": "def signup(password):\n    return 201\n", "README.md": "demo", "scripts/release.sh": "deploy"}
    plan = ["read handler", "write validation", "write test", "run tests"]

    repo["app.py"] = render_handler(model.first_draft_min_length())
    log.touched.append("app.py")
    log.events.append("wrote validation in app.py")

    if "instructions" in surfaces:
        repo["test_app.py"] = TEST_FILE
        log.touched.append("test_app.py")
        log.events.append("definition of done needs a test: wrote test_app.py")

    for target in model.tidy_up_targets():
        if "scope" in surfaces:
            log.events.append(f"scope contract blocked write to {target}")
        else:
            repo[target] = repo[target] + " (tidied)"
            log.touched.append(target)
            log.events.append(f"tidied {target} while nearby")

    if "feedback" in surfaces:
        code, output = run_tests(repo)
        log.tests_ran = True
        log.events.append(f"ran tests: exit={code} {output}")
        if code != 0:
            repo["app.py"] = render_handler(model.fix_from_feedback(output))
            code, output = run_tests(repo)
            log.events.append(f"fixed from feedback, re-ran: exit={code} {output}")
    else:
        log.events.append("assumed tests pass")

    log.final_exit, final_output = run_tests(repo)
    if "verification" in surfaces and log.final_exit != 0:
        log.events.append(f"verification gate refused: {final_output}")
        log.declared_success = False
    else:
        log.declared_success = True
        log.events.append("declared: done")

    if "review" in surfaces:
        log.events.append("reviewer role checked diff against scope and acceptance")
    else:
        log.self_approved = True

    if "handoff" in surfaces:
        log.handoff_note = f"changed {sorted(set(log.touched))}; tests exit {log.final_exit}; next: open PR"
        log.events.append("wrote handoff note")

    if "state" not in surfaces:
        log.redone_steps = len(plan) - 1
    return log


def outcome(run: RunLog) -> str:
    if run.declared_success and run.final_exit == 0:
        return "shipped"
    if run.declared_success:
        return "FALSE DONE"
    return "blocked by gate"


def print_side_by_side(left: RunLog, right: RunLog) -> None:
    width = 58
    print(f"{left.label:<{width}} | {right.label}")
    print("-" * width + "-+-" + "-" * width)
    for index in range(max(len(left.events), len(right.events))):
        a = left.events[index] if index < len(left.events) else ""
        b = right.events[index] if index < len(right.events) else ""
        print(f"{a[:width]:<{width}} | {b[:width]}")


def main() -> None:
    model = StubModel()
    prompt_only = run_session(model, set(), "PROMPT ONLY")
    workbench = run_session(model, set(SURFACES), "WORKBENCH (7 surfaces)")

    print("same model, same task: add /signup password validation plus a passing test\n")
    print_side_by_side(prompt_only, workbench)

    report = {
        "label": prompt_only.label,
        "declared_success": prompt_only.declared_success,
        "actual_test_exit": prompt_only.final_exit,
        "missed_surfaces": [
            {"surface": s, "symptom": text, "primitive": PRIMITIVE_BY_SURFACE[s]}
            for s, text in prompt_only.symptoms().items()
        ],
    }
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "failure_modes.json"
        out.write_text(json.dumps(report, indent=2) + "\n")
        print(f"\nfailure_modes.json ({len(report['missed_surfaces'])} missed surfaces)")
        print(out.read_text())

    verdict = "SHIP" if not workbench.symptoms() and workbench.final_exit == 0 else "HOLD"
    print(f"prompt-only outcome: {outcome(prompt_only)}")
    print(f"workbench verdict: {verdict} (tests exit {workbench.final_exit}, symptoms {len(workbench.symptoms())})")

    print("\nleave-one-out ablation: remove a single surface from the full workbench")
    for surface in SURFACES:
        run = run_session(model, set(SURFACES) - {surface}, f"without {surface}")
        new = sorted(run.symptoms())
        print(f"  without {surface:<13} tests_exit={run.final_exit}  outcome={outcome(run):<16} symptoms={new}")


if __name__ == "__main__":
    main()
