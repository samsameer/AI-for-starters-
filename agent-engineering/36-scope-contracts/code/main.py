from __future__ import annotations

import json
import re
import tempfile
from dataclasses import asdict, dataclass, field
from functools import lru_cache
from pathlib import Path


@dataclass
class ScopeContract:
    task_id: str
    goal: str
    allowed_files: list[str]
    forbidden_files: list[str]
    acceptance_criteria: list[str]
    rollback_plan: str
    approvals_required: list[str] = field(default_factory=list)
    hard_paths: list[str] = field(default_factory=lambda: ["scripts/**", "migrations/**", "config/prod/**"])
    soft_paths: list[str] = field(default_factory=lambda: ["docs/**", "**/*.md"])
    time_budget_minutes: int | None = None
    network_egress: list[str] | None = None
    violation_budget: int = 0


@dataclass
class RunSummary:
    touched_files: list[str]
    commands_run: list[str]
    elapsed_minutes: float
    network_hosts: list[str]
    actions: list[str] = field(default_factory=list)
    approvals: list[str] = field(default_factory=list)


@dataclass
class Finding:
    code: str
    severity: str
    detail: str


@lru_cache(maxsize=None)
def glob_regex(pattern: str) -> re.Pattern[str]:
    out, i = "", 0
    while i < len(pattern):
        if pattern.startswith("**/", i):
            out, i = out + "(?:.*/)?", i + 3
        elif pattern.startswith("**", i):
            out, i = out + ".*", i + 2
        elif pattern[i] == "*":
            out, i = out + "[^/]*", i + 1
        else:
            out, i = out + re.escape(pattern[i]), i + 1
    return re.compile(f"^{out}$")


def matches(path: str, patterns: list[str]) -> bool:
    return any(glob_regex(p).match(path) for p in patterns)


def merge_egress(a: list[str] | None, b: list[str] | None) -> list[str] | None:
    if a is None or b is None:
        return b if a is None else a
    return sorted(set(a) & set(b))


def min_optional(a: int | None, b: int | None) -> int | None:
    values = [v for v in (a, b) if v is not None]
    return min(values) if values else None


def glob_within(child: str, parents: list[str]) -> bool:
    sample_path = child.replace("**", "any/depth").replace("*", "name")
    return matches(sample_path, parents)


def merge(project: ScopeContract, task: ScopeContract) -> ScopeContract:
    allowed = [p for p in task.allowed_files if glob_within(p, project.allowed_files)]
    return ScopeContract(
        task_id=task.task_id,
        goal=task.goal,
        allowed_files=allowed,
        forbidden_files=sorted(set(project.forbidden_files) | set(task.forbidden_files)),
        acceptance_criteria=list(dict.fromkeys(project.acceptance_criteria + task.acceptance_criteria)),
        rollback_plan=task.rollback_plan or project.rollback_plan,
        approvals_required=list(dict.fromkeys(project.approvals_required + task.approvals_required)),
        hard_paths=sorted(set(project.hard_paths) | set(task.hard_paths)),
        soft_paths=sorted(set(project.soft_paths) & set(task.soft_paths)),
        time_budget_minutes=min_optional(project.time_budget_minutes, task.time_budget_minutes),
        network_egress=merge_egress(project.network_egress, task.network_egress),
        violation_budget=min(project.violation_budget, task.violation_budget),
    )


def check_feature_list(features: dict[str, object], contract: ScopeContract) -> list[Finding]:
    items = features["features"]
    active = [f["id"] for f in items if f["status"] == "in_progress"]
    findings = []
    if len(active) > 1:
        findings.append(Finding("feature.many_in_progress", "block", f"{active} in progress at once"))
    if contract.task_id not in active:
        findings.append(Finding("feature.not_active", "block", f"{contract.task_id} is not the active feature {active}"))
    return findings


def classify_path(contract: ScopeContract, path: str) -> str:
    if matches(path, contract.forbidden_files):
        return "forbidden"
    if matches(path, contract.allowed_files):
        return "allowed"
    if matches(path, contract.hard_paths):
        return "hard_off_scope"
    if matches(path, contract.soft_paths):
        return "soft_off_scope"
    return "off_scope"


def pre_action_guard(contract: ScopeContract, action: str, target: str) -> str:
    if action == "write":
        kind = classify_path(contract, target)
        return {"allowed": "allow", "soft_off_scope": "ask", "off_scope": "ask"}.get(kind, "deny")
    if action == "fetch":
        if contract.network_egress is None:
            return "allow"
        return "allow" if target in contract.network_egress else "deny"
    if action in contract.approvals_required:
        return "ask"
    return "allow"


def scope_check(contract: ScopeContract, run: RunSummary) -> tuple[list[Finding], bool]:
    findings: list[Finding] = []
    buckets: dict[str, list[str]] = {}
    for path in run.touched_files:
        buckets.setdefault(classify_path(contract, path), []).append(path)
    severity = {"forbidden": "block", "hard_off_scope": "block", "off_scope": "warn", "soft_off_scope": "info"}
    for kind, sev in severity.items():
        if buckets.get(kind):
            findings.append(Finding(f"scope.{kind}", sev, str(buckets[kind])))
    missing = [c for c in contract.acceptance_criteria if c not in run.commands_run]
    if missing:
        findings.append(Finding("acceptance.not_run", "block", str(missing)))
    if contract.time_budget_minutes is not None and run.elapsed_minutes > contract.time_budget_minutes:
        findings.append(Finding("time.over_budget", "block", f"{run.elapsed_minutes}m > {contract.time_budget_minutes}m"))
    if contract.network_egress is not None:
        bad = [h for h in run.network_hosts if h not in contract.network_egress]
        if bad:
            findings.append(Finding("network.egress", "block", str(bad)))
    unapproved = [a for a in run.actions if a in contract.approvals_required and a not in run.approvals]
    if unapproved:
        findings.append(Finding("approval.missing", "block", str(unapproved)))
    warns = sum(1 for f in findings if f.severity == "warn")
    passed = warns <= contract.violation_budget and not any(f.severity == "block" for f in findings)
    return findings, passed


def main() -> None:
    project = ScopeContract(
        task_id="PROJECT", goal="project defaults",
        allowed_files=["app/**", "tests/**", "docs/**"],
        forbidden_files=["config/prod/**", ".env*"],
        acceptance_criteria=[], rollback_plan="git revert the merge commit; redeploy previous tag",
        approvals_required=["add_dependency"], time_budget_minutes=60, violation_budget=1,
        network_egress=["pypi.org", "api.openai.com"],
    )
    task = ScopeContract(
        task_id="import-pdf", goal="import a PDF into the library",
        allowed_files=["app/importers/**", "tests/test_import*.py", "deploy/**"],
        forbidden_files=["migrations/**"],
        acceptance_criteria=["pytest tests/test_import.py"],
        rollback_plan="git revert the task commit; delete rows tagged import-pdf",
        time_budget_minutes=30, network_egress=["pypi.org"],
    )
    effective = merge(project, task)
    print("effective contract (least privilege):")
    for key in ("allowed_files", "forbidden_files", "approvals_required", "time_budget_minutes", "network_egress", "violation_budget"):
        print(f"  {key}: {getattr(effective, key)}")

    features = {"project": "knowledge-base", "features": [
        {"id": "import-pdf", "status": "in_progress", "done_when": "pytest tests/test_import.py"},
        {"id": "full-text-search", "status": "todo", "done_when": "ranked results with snippets"},
    ]}
    print("\nfeature list check:", [asdict(f) for f in check_feature_list(features, effective)] or "one active feature, matches contract")

    print("\npre-action guard (runs before each tool call):")
    for action, target in [("write", "app/importers/pdf.py"), ("write", "docs/import.md"), ("write", "app/router.py"),
                           ("write", "scripts/release.sh"), ("write", "config/prod/db.yaml"),
                           ("fetch", "pypi.org"), ("fetch", "paste.example.net"), ("add_dependency", "pypdf")]:
        print(f"  {action:<15} {target:<24} -> {pre_action_guard(effective, action, target)}")

    clean = RunSummary(["app/importers/pdf.py", "tests/test_import.py", "docs/import.md"],
                       ["pytest tests/test_import.py"], 21.0, ["pypi.org"], ["add_dependency"], ["add_dependency"])
    creep = RunSummary(["app/importers/pdf.py", "app/router.py", "app/settings_page.py", "README.md",
                        "scripts/release.sh", "migrations/004_pdf.sql"],
                       [], 44.5, ["pypi.org", "paste.example.net"], ["add_dependency"], [])

    with tempfile.TemporaryDirectory() as tmp:
        closed = Path(tmp) / "scope" / "closed"
        closed.mkdir(parents=True)
        for label, run in (("clean run", clean), ("creeping run", creep)):
            findings, passed = scope_check(effective, run)
            print(f"\n{label}: {'PASS' if passed else 'BLOCK'}")
            for f in findings:
                print(f"  [{f.severity:<5}] {f.code:<22} {f.detail}")
            record = {"task_id": effective.task_id, "run": label, "passed": passed,
                      "findings": [asdict(f) for f in findings], "rollback_plan": effective.rollback_plan}
            (closed / f"{effective.task_id}-{label.split()[0]}.json").write_text(json.dumps(record, indent=2) + "\n")
        print(f"\narchived contracts: {sorted(p.name for p in closed.iterdir())}")


if __name__ == "__main__":
    main()
