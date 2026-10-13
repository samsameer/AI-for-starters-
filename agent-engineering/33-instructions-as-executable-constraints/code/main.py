from __future__ import annotations

import fnmatch
import hashlib
import json
import re
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path


TODAY = date(2026, 10, 13)

RULES_MD = "\n".join([
    "# Agent rules",
    "",
    "## startup/state-read-first",
    "- category: startup",
    "- check: read_state_before_tools",
    "- severity: block",
    "- expires: 2027-01-10",
    "Read agent_state.json before the first tool call.",
    "",
    "## forbidden/no-release-script",
    "- category: forbidden",
    "- check: no_forbidden_writes",
    "- severity: block",
    "- expires: 2027-01-10",
    "- incident: INC-212",
    "Never write scripts/** or config/prod/** outside an approved release task.",
    "",
    "## done/acceptance-exit-zero",
    "- category: definition_of_done",
    "- check: acceptance_passed",
    "- severity: block",
    "- expires: 2027-01-10",
    "Done means the acceptance command exited 0 in this session.",
    "",
    "## uncertainty/question-note",
    "- category: uncertainty",
    "- check: asked_when_unsure",
    "- severity: warn",
    "- expires: 2027-01-10",
    "Below 0.7 confidence, write a question note instead of guessing.",
    "",
    "## approval/new-dependency",
    "- category: approval",
    "- check: dependencies_approved",
    "- severity: block",
    "- expires: 2027-01-10",
    "A new runtime dependency needs a recorded human approval.",
    "",
    "## style/docstring-tone",
    "- category: forbidden",
    "- check: always_true",
    "- severity: info",
    "- expires: 2026-09-01",
    "Prefer a friendly tone in docstrings.",
    "",
    "## be-careful",
    "Always be careful and test thoroughly.",
    "",
])

ROUTER_MD = "\n".join([
    "Rules: `docs/agent-rules.md`",
    "Testing: `docs/testing.md`",
    "Release work only: `docs/deploy.md`",
    "",
])

FORBIDDEN_GLOBS = ["scripts/*", "config/prod/*"]
CATEGORIES = {"startup", "forbidden", "definition_of_done", "uncertainty", "approval"}


@dataclass
class Rule:
    slug: str
    category: str
    check: str
    severity: str
    expires: str
    description: str
    incident: str = ""


@dataclass
class TurnTrace:
    tool_calls: list[str]
    edited_files: list[str]
    confidence: float
    question_notes: int
    acceptance_exit: int | None
    added_dependencies: list[str]
    approvals: list[str] = field(default_factory=list)


def parse_rules(text: str) -> tuple[list[Rule], list[str]]:
    rules: list[Rule] = []
    rejected: list[str] = []
    for block in re.split(r"\n## ", text)[1:]:
        head, _, body = block.partition("\n")
        meta = dict(re.findall(r"^-\s*(\w+):\s*(.+)$", body, flags=re.MULTILINE))
        prose = [ln.strip() for ln in body.splitlines() if ln.strip() and not ln.startswith("-")]
        if "check" not in meta or meta.get("category") not in CATEGORIES:
            rejected.append(f"{head.strip()}: aspirational (no check or unknown category)")
            continue
        rules.append(Rule(head.strip(), meta["category"], meta["check"], meta.get("severity", "warn"),
                          meta.get("expires", ""), prose[-1] if prose else "", meta.get("incident", "")))
    return rules, rejected


class RuleChecker:
    def read_state_before_tools(self, trace: TurnTrace) -> bool:
        return bool(trace.tool_calls) and trace.tool_calls[0] == "read:agent_state.json"

    def no_forbidden_writes(self, trace: TurnTrace) -> bool:
        return not any(fnmatch.fnmatch(f, g) for f in trace.edited_files for g in FORBIDDEN_GLOBS)

    def acceptance_passed(self, trace: TurnTrace) -> bool:
        return trace.acceptance_exit == 0

    def asked_when_unsure(self, trace: TurnTrace) -> bool:
        return trace.confidence >= 0.7 or trace.question_notes > 0

    def dependencies_approved(self, trace: TurnTrace) -> bool:
        return all(dep in trace.approvals for dep in trace.added_dependencies)

    def always_true(self, trace: TurnTrace) -> bool:
        return True


def score(rules: list[Rule], trace: TurnTrace) -> dict[str, object]:
    checker = RuleChecker()
    rows = []
    for rule in rules:
        check = getattr(checker, rule.check, None)
        passed = bool(check(trace)) if check else False
        rows.append({"slug": rule.slug, "severity": rule.severity, "passed": passed,
                     "missing_check": check is None})
    blocking = [r["slug"] for r in rows if not r["passed"] and r["severity"] == "block"]
    warnings = [r["slug"] for r in rows if not r["passed"] and r["severity"] == "warn"]
    return {"rows": rows, "blocking": blocking, "warnings": warnings, "verdict": "REFUSE" if blocking else "ALLOW"}


def write_lock(rules_path: Path, rules: list[Rule], lock_path: Path) -> str:
    digest = hashlib.sha256(rules_path.read_bytes()).hexdigest()[:12]
    lock_path.write_text(json.dumps({"source_sha": digest, "rules": [asdict(r) for r in rules]}, indent=2) + "\n")
    return digest


def lock_is_current(rules_path: Path, lock_path: Path) -> bool:
    digest = hashlib.sha256(rules_path.read_bytes()).hexdigest()[:12]
    return json.loads(lock_path.read_text())["source_sha"] == digest


def pre_tool_use_hook(tool: str, path: str) -> tuple[str, str]:
    if tool == "write" and any(fnmatch.fnmatch(path, g) for g in FORBIDDEN_GLOBS):
        return "deny", f"forbidden/no-release-script blocks write to {path}"
    return "allow", ""


def reachability(root: Path, router: str) -> list[str]:
    missing = []
    for ref in re.findall(r"`([\w./-]+\.md)`", router):
        if not (root / ref).exists():
            missing.append(ref)
    return missing


def expiry_sweep(rules: list[Rule]) -> list[str]:
    return [f"{r.slug} expired {r.expires}: justify, weaken or delete"
            for r in rules if r.expires and date.fromisoformat(r.expires) < TODAY]


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "docs").mkdir()
        rules_path = root / "docs" / "agent-rules.md"
        rules_path.write_text(RULES_MD)
        (root / "docs" / "testing.md").write_text("pytest -x\n")

        rules, rejected = parse_rules(rules_path.read_text())
        print(f"parsed {len(rules)} executable rules")
        for rule in rules:
            tag = f" [{rule.incident}]" if rule.incident else ""
            print(f"  {rule.severity:<5} {rule.category:<18} {rule.slug}{tag}")
        print("rejected:", rejected)

        lock_path = root / "docs" / "agent-rules.lock.json"
        print("\nlock written for source", write_lock(rules_path, rules, lock_path))
        rules_path.write_text(RULES_MD + "\n## approval/prod-write\n- category: approval\n- check: always_true\n- severity: block\nProd writes need approval.\n")
        print("lock current after markdown edit?", lock_is_current(rules_path, lock_path), "-> regenerate in pre-commit")

        print("\nruntime enforcement (pre-tool-use hook, before the write happens):")
        for tool, path in [("write", "app.py"), ("write", "scripts/release.sh"), ("read", "scripts/release.sh")]:
            decision, why = pre_tool_use_hook(tool, path)
            print(f"  {tool:<5} {path:<20} {decision} {why}")

        bad = TurnTrace(["grep:signup", "read:agent_state.json"], ["app.py", "scripts/release.sh"],
                        0.4, 0, 1, ["fastapi-limiter"])
        good = TurnTrace(["read:agent_state.json", "read:app.py"], ["app.py", "test_app.py"],
                         0.9, 0, 0, ["fastapi-limiter"], approvals=["fastapi-limiter"])
        for label, trace in (("bad turn", bad), ("good turn", good)):
            report = score(rules, trace)
            print(f"\n{label}: {report['verdict']}")
            for row in report["rows"]:
                print(f"  {'PASS' if row['passed'] else 'FAIL'}  {row['severity']:<5} {row['slug']}")
            if report["warnings"]:
                print(f"  warnings: {report['warnings']}")

        print("\nreachability from router, missing topic docs:", reachability(root, ROUTER_MD))
        print("expiry sweep:", expiry_sweep(rules))


if __name__ == "__main__":
    main()
