from __future__ import annotations

import hashlib
import hmac
import json
import os
import sys
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path

COVERAGE_FLOOR = 0.80
COVERAGE_MAX_DROP = 0.01
DEMO_SECRET = "demo-only-override-secret"


@dataclass(frozen=True)
class Finding:
    code: str
    severity: str
    detail: str


@dataclass
class Artifacts:
    task_id: str
    head_commit: str
    acceptance: list[str]
    feedback: list[dict]
    scope_report: dict
    rule_report: list[dict]
    coverage: dict | None = None
    advisory: list[Finding] = field(default_factory=list)


@dataclass
class Verdict:
    task_id: str
    head_commit: str
    passed: bool
    strict: bool
    findings: list[Finding]
    overridden: list[str] = field(default_factory=list)


def acceptance_findings(art: Artifacts) -> list[Finding]:
    found: list[Finding] = []
    latest: dict[str, dict] = {}
    for record in art.feedback:
        latest[str(record["command"])] = record
        if record.get("exit_code") is None:
            found.append(Finding("feedback.null_exit", "block", f"no exit code for {record['command']}"))
    for command in art.acceptance:
        record = latest.get(command)
        if record is None:
            found.append(Finding("acceptance.missing", "block", f"never ran: {command}"))
        elif record.get("exit_code") not in (0, None):
            found.append(Finding("acceptance.failed", "block", f"exit {record['exit_code']}: {command}"))
    return found


def scope_findings(art: Artifacts) -> list[Finding]:
    found: list[Finding] = []
    if art.scope_report.get("forbidden_writes"):
        found.append(Finding("scope.forbidden", "block", f"forbidden writes {art.scope_report['forbidden_writes']}"))
    if art.scope_report.get("off_scope_writes"):
        found.append(Finding("scope.off_scope", "warn", f"off-scope writes {art.scope_report['off_scope_writes']}"))
    return found


def rule_findings(art: Artifacts) -> list[Finding]:
    return [Finding("rule.failed", "block", f"rule {row['slug']}") for row in art.rule_report if not row["passed"]]


def coverage_findings(art: Artifacts, floor: float) -> list[Finding]:
    if not art.coverage:
        return [Finding("coverage.missing", "warn", "no coverage report; floor not enforced")]
    current, previous = art.coverage["current"], art.coverage.get("previous", art.coverage["current"])
    found: list[Finding] = []
    if current < floor:
        found.append(Finding("coverage.below_floor", "block", f"{current:.0%} < floor {floor:.0%}"))
    drop = round(previous - current, 6)
    if drop > COVERAGE_MAX_DROP:
        found.append(Finding("coverage.regression", "block", f"dropped {drop:.1%} vs last merge"))
    elif drop > 0:
        found.append(Finding("coverage.minor_drop", "warn", f"dropped {drop:.1%}"))
    return found


def verify(art: Artifacts, strict: bool = False, floor: float = COVERAGE_FLOOR) -> Verdict:
    findings = acceptance_findings(art) + scope_findings(art) + rule_findings(art) + coverage_findings(art, floor)
    if strict:
        findings = [Finding(f.code, "block", f.detail) if f.severity == "warn" else f for f in findings]
    findings += [Finding(f.code, "advisory", f.detail) for f in art.advisory]
    passed = not any(f.severity == "block" for f in findings)
    return Verdict(art.task_id, art.head_commit, passed, strict, findings)


def override_secret() -> tuple[str, bool]:
    secret = os.environ.get("VERIFY_OVERRIDE_SECRET")
    return (secret, False) if secret else (DEMO_SECRET, True)


def sign(entry: dict, secret: str) -> str:
    canonical = json.dumps(entry, sort_keys=True, separators=(",", ":")).encode()
    return hmac.new(secret.encode(), canonical, hashlib.sha256).hexdigest()[:32]


def make_override(task_id: str, code: str, reason: str, user: str, head: str, secret: str) -> dict:
    if not all([task_id, code, reason, user, head]):
        raise ValueError("override needs task_id, finding code, reason, user and head commit")
    entry = {"task_id": task_id, "finding_code": code, "reason": reason, "user": user, "head_commit": head}
    return {**entry, "signature": sign(entry, secret)}


def apply_overrides(verdict: Verdict, overrides: list[dict], secret: str) -> Verdict:
    accepted: set[str] = set()
    for entry in overrides:
        body = {k: v for k, v in entry.items() if k != "signature"}
        valid = hmac.compare_digest(sign(body, secret), entry.get("signature", ""))
        same_commit = body.get("head_commit") == verdict.head_commit
        if valid and same_commit and body.get("task_id") == verdict.task_id:
            accepted.add(body["finding_code"])
    remaining = [f for f in verdict.findings if f.code not in accepted]
    passed = not any(f.severity == "block" for f in remaining)
    return Verdict(verdict.task_id, verdict.head_commit, passed, verdict.strict, verdict.findings, sorted(accepted))


def scenarios() -> list[Artifacts]:
    accept = ["python3 -m unittest tests.test_signup"]
    clean_scope = {"forbidden_writes": [], "off_scope_writes": []}
    return [
        Artifacts("T-001", "a1b2c3d", accept, [{"command": accept[0], "exit_code": 0}], clean_scope,
                  [{"slug": "done/tests-pass", "passed": True}], {"current": 0.84, "previous": 0.845}),
        Artifacts("T-002", "b2c3d4e", accept, [{"command": accept[0], "exit_code": 0}],
                  {"forbidden_writes": ["scripts/release.sh"], "off_scope_writes": ["README.md"]},
                  [{"slug": "forbidden/no-release-script", "passed": False}], {"current": 0.62, "previous": 0.80}),
        Artifacts("T-003", "c3d4e5f", accept, [{"command": "ruff check .", "exit_code": 0}], clean_scope,
                  [{"slug": "done/tests-pass", "passed": False}]),
        Artifacts("T-004", "d4e5f6a", accept,
                  [{"command": accept[0], "exit_code": 1}, {"command": accept[0], "exit_code": 0}],
                  {"forbidden_writes": [], "off_scope_writes": ["docs/api.md"]},
                  [{"slug": "done/tests-pass", "passed": True}], {"current": 0.86, "previous": 0.86},
                  [Finding("system_one.goal_fit", "advisory", "diff relates to goal: P(yes)=0.91 (Jev noul, advisory)")]),
    ]


def show(verdict: Verdict) -> None:
    mode = " strict" if verdict.strict else ""
    extra = f" overrides={verdict.overridden}" if verdict.overridden else ""
    print(f"{verdict.task_id}{mode}: passed={verdict.passed}{extra}")
    for f in verdict.findings:
        print(f"   [{f.severity:8}] {f.code}: {f.detail}")


def main() -> None:
    strict = "--strict" in sys.argv
    secret, demo = override_secret()
    with tempfile.TemporaryDirectory() as tmp:
        out_dir = Path(tmp) / "outputs" / "verification"
        out_dir.mkdir(parents=True)
        verdicts = {}
        for art in scenarios():
            verdict = verify(art, strict=strict)
            verdicts[art.task_id] = verdict
            (out_dir / f"{art.task_id}.json").write_text(json.dumps(asdict(verdict), indent=2))
            show(verdict)
        print(f"\nreports written: {sorted(p.name for p in out_dir.iterdir())}")
    print(f"\noverride secret: {'DEMO (set VERIFY_OVERRIDE_SECRET in real use)' if demo else 'from env'}")
    strict_t4 = verify(scenarios()[3], strict=True)
    show(strict_t4)
    good = make_override("T-004", "scope.off_scope", "API doc update approved in review", "alice", "d4e5f6a", secret)
    stale = make_override("T-004", "scope.off_scope", "approved last week", "alice", "0000000", secret)
    forged = {**good, "user": "agent-self-approval"}
    for label, entry in (("stale-commit", stale), ("forged", forged), ("signed", good)):
        result = apply_overrides(strict_t4, [entry], secret)
        print(f"   {label:12} -> passed={result.passed} accepted={result.overridden}")


if __name__ == "__main__":
    main()
