from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path

HANDOFF_FIELDS = ("summary", "changed_files", "commands_run", "failed_attempts", "open_risks", "next_action", "verdict_pointer")

SIGNUP_V0 = "\n".join([
    "USERS: dict[str, str] = {}",
    "",
    "",
    "def signup(email: str, password: str) -> dict:",
    "    USERS[email] = password",
    "    return {'status': 200, 'email': email}",
    "",
])

SIGNUP_PROMPT_ONLY = SIGNUP_V0.replace(
    "    USERS[email] = password",
    "    if len(password) < 8:\n        return {'status': 400, 'error': 'too short'}\n    USERS[email] = password",
)

SIGNUP_WORKBENCH_TYPO = SIGNUP_V0.replace(
    "    USERS[email] = password",
    "    if len(password) < 8:\n"
    "        return {'status': 442, 'error': {'type': 'validation_error', 'field': 'password'}}\n"
    "    USERS[email] = password",
)

SIGNUP_WORKBENCH = SIGNUP_WORKBENCH_TYPO.replace("442", "422")

TEST_V0 = "\n".join([
    "import unittest",
    "from app.signup import signup",
    "",
    "",
    "class SignupTest(unittest.TestCase):",
    "    def test_happy_path(self):",
    "        self.assertEqual(signup('a@b.co', 'longenough')['status'], 200)",
    "",
])

TEST_WORKBENCH = TEST_V0 + "\n".join([
    "",
    "    def test_short_password_is_rejected_with_envelope(self):",
    "        out = signup('a@b.co', 'short')",
    "        self.assertEqual(out['status'], 422)",
    "        self.assertEqual(out['error']['type'], 'validation_error')",
    "",
])

HIDDEN_ACCEPTANCE = "; ".join([
    "from app.signup import signup",
    "bad = signup('x@y.co', 'short')",
    "assert bad['status'] == 422, bad",
    "assert bad['error']['type'] == 'validation_error', bad",
    "assert signup('x@y.co', 'longenough')['status'] == 200",
])

SAMPLE_APP = {
    "app/__init__.py": "",
    "app/signup.py": SIGNUP_V0,
    "tests/__init__.py": "",
    "tests/test_signup.py": TEST_V0,
    "README.md": "Sample app\n\nRun: python3 -m unitest\n",
    "scripts/release.sh": "echo releasing 1.0.0\n",
}

TASKS = {
    "validate-signup": {
        "goal": "reject passwords shorter than 8 chars with 422 and a typed error envelope",
        "allowed": {"app/signup.py", "tests/test_signup.py"},
        "acceptance": "python3 -m unittest tests.test_signup",
        "hidden_check": HIDDEN_ACCEPTANCE,
    },
    "fix-readme-typo": {
        "goal": "fix the unittest typo in README",
        "allowed": {"README.md"},
        "acceptance": "grep -q 'unittest' README.md",
        "hidden_check": "assert 'unittest' in open('README.md').read() and 'unitest' not in open('README.md').read()",
    },
}


@dataclass
class RunRecord:
    pipeline: str
    task: str
    steps: list[str] = field(default_factory=list)
    feedback: list[dict] = field(default_factory=list)
    claimed_done: bool = False
    handoff: dict = field(default_factory=dict)


@dataclass
class Outcome:
    pipeline: str
    task: str
    tests_actually_run: bool
    acceptance_met: bool
    files_outside_scope: list[str]
    handoff_fields: int
    reviewer_total: int
    honest_claim: bool
    agent_steps: int


def python_env() -> dict:
    return {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}


def run(cmd: list[str], cwd: Path) -> int:
    return subprocess.run(cmd, cwd=cwd, env=python_env(), capture_output=True, timeout=30).returncode


def lay_out(root: Path) -> None:
    for rel, body in SAMPLE_APP.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(body)


def fingerprint(root: Path) -> dict[str, str]:
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.rglob("*")) if p.is_file() and "__pycache__" not in p.parts}


def write(root: Path, record: RunRecord, rel: str, body: str) -> None:
    (root / rel).write_text(body)
    record.steps.append(f"edit {rel}")


def feedback_run(root: Path, record: RunRecord, command: str) -> int:
    argv = [sys.executable, *command.split()[1:]] if command.startswith("python3") else ["sh", "-c", command]
    code = run(argv, root)
    record.feedback.append({"command": command, "exit_code": code})
    record.steps.append(f"run {command} -> {code}")
    return code


def prompt_only(root: Path, task: str) -> RunRecord:
    record = RunRecord("prompt-only", task, steps=["read README.md"])
    if task == "validate-signup":
        record.steps.append("read app/signup.py")
        write(root, record, "app/signup.py", SIGNUP_PROMPT_ONLY)
        write(root, record, "README.md", SAMPLE_APP["README.md"] + "\nPasswords must be 8+ chars.\n")
        write(root, record, "scripts/release.sh", "echo releasing 1.0.1\n")
    else:
        write(root, record, "README.md", SAMPLE_APP["README.md"].replace("unitest", "unittest"))
    record.claimed_done = True
    record.steps.append("claim: done, tests pass")
    return record


def workbench(root: Path, task: str) -> RunRecord:
    spec = TASKS[task]
    record = RunRecord("workbench", task, steps=["init: tree clean, state loaded", f"scope: {sorted(spec['allowed'])}"])
    if task == "validate-signup":
        write(root, record, "tests/test_signup.py", TEST_WORKBENCH)
        write(root, record, "app/signup.py", SIGNUP_WORKBENCH_TYPO)
        if feedback_run(root, record, spec["acceptance"]) != 0:
            write(root, record, "app/signup.py", SIGNUP_WORKBENCH)
            feedback_run(root, record, spec["acceptance"])
    else:
        write(root, record, "README.md", SAMPLE_APP["README.md"].replace("unitest", "unittest"))
        feedback_run(root, record, spec["acceptance"])
    passed = bool(record.feedback) and record.feedback[-1]["exit_code"] == 0
    record.steps += ["gate: verify", "review: rubric", "handoff: generate"]
    record.claimed_done = passed
    record.handoff = {
        "summary": f"{task}: gate passed={passed}",
        "changed_files": sorted(spec["allowed"]),
        "commands_run": sorted({r["command"] for r in record.feedback}),
        "failed_attempts": [f"{r['command']} -> {r['exit_code']}" for r in record.feedback if r["exit_code"]],
        "open_risks": [{"severity": "warn", "detail": "no rate limit on signup yet"}] if task == "validate-signup" else [],
        "next_action": "open PR and request review",
        "verdict_pointer": f"outputs/verification/{task}.json",
    }
    return record


def measure(record: RunRecord, root: Path, before: dict[str, str]) -> Outcome:
    spec = TASKS[record.task]
    after = fingerprint(root)
    changed = sorted(p for p in set(before) | set(after) if before.get(p) != after.get(p))
    outside = [p for p in changed if p not in spec["allowed"]]
    ran = any(r["command"] == spec["acceptance"] and r["exit_code"] is not None for r in record.feedback)
    met = run([sys.executable, "-c", spec["hidden_check"]], root) == 0
    fields = sum(1 for f in HANDOFF_FIELDS if f in record.handoff)
    review = (2 if met else 0) + (2 if not outside else 0 if any(p.startswith("scripts/") for p in outside) else 1)
    review += (2 if ran and met else 0) + (2 if record.handoff.get("next_action") else 0) + (2 if record.handoff.get("open_risks") is not None else 1)
    return Outcome(record.pipeline, record.task, ran, met, outside, fields, review,
                   record.claimed_done == met, len(record.steps))


def compare(task: str) -> list[Outcome]:
    outcomes = []
    for pipeline in (prompt_only, workbench):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            lay_out(root)
            before = fingerprint(root)
            record = pipeline(root, task)
            outcomes.append(measure(record, root, before))
            if pipeline is workbench:
                print(f"  workbench trace ({task}): " + " | ".join(record.steps))
    return outcomes


def wins(po: Outcome, wb: Outcome) -> int:
    return sum([wb.tests_actually_run > po.tests_actually_run, wb.acceptance_met > po.acceptance_met,
                len(wb.files_outside_scope) < len(po.files_outside_scope), wb.handoff_fields > po.handoff_fields,
                wb.reviewer_total > po.reviewer_total])


def report(results: dict[str, list[Outcome]]) -> str:
    lines = ["# Before / after: same repo, same tasks, two pipelines", ""]
    for task, (po, wb) in results.items():
        lines += [f"## {task}", "", "| Outcome | Prompt-only | Workbench |", "|---|---|---|"]
        for name in ("tests_actually_run", "acceptance_met", "files_outside_scope", "handoff_fields",
                     "reviewer_total", "honest_claim", "agent_steps"):
            a, b = getattr(po, name), getattr(wb, name)
            lines.append(f"| {name} | {len(a) if isinstance(a, list) else a} | {len(b) if isinstance(b, list) else b} |")
        lines += ["", f"Workbench wins {wins(po, wb)}/5 core outcomes; step overhead {wb.agent_steps - po.agent_steps:+d}.", ""]
    return "\n".join(lines)


def main() -> None:
    results = {task: compare(task) for task in TASKS}
    body = report(results)
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp)
        (out / "before-after-report.md").write_text(body)
        (out / "comparison.json").write_text(json.dumps({t: [asdict(o) for o in os_] for t, os_ in results.items()}, indent=2))
        print(f"\nwrote {sorted(p.name for p in out.iterdir())}\n")
    print(body)
    po, _ = results["validate-signup"]
    print(f"prompt-only touched outside scope: {po.files_outside_scope}; claimed done but acceptance_met={po.acceptance_met}")


if __name__ == "__main__":
    main()
