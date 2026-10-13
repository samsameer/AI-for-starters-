from __future__ import annotations

import copy
import fnmatch
import re
import tempfile
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

REPO: dict[str, list[str]] = {
    "app/accounts.py": [
        "from app.store import AccountStore",
        "",
        "def normalize_email(raw: str) -> str:",
        "    return raw.strip().lower()",
        "",
        "def create_account(store: AccountStore, email: str, password: str) -> dict:",
        "    store.save(email, password)",
        "    return {'status': 201}",
    ],
    "tests/test_accounts.py": [
        "def test_duplicate_username_returns_409(client):",
        "    assert client.post('/users', json=dup).status_code == 409",
    ],
    "migrations/0007_accounts.sql": ["CREATE TABLE accounts (email TEXT, password TEXT);"],
    "AGENTS.md": ["Never edit migrations/ without a human approval."],
}
UNKNOWN_KINDS = ("discoverable", "decidable", "human", "deferred")
VAGUE_ACCEPTANCE = {"tests pass", "it works", "looks good", "ci green"}


@dataclass(frozen=True)
class RepositoryFact:
    claim: str
    receipt: str
    expect: str


@dataclass
class Unknown:
    question: str
    kind: str
    probe: str = ""


@dataclass
class TaskFrame:
    goal: str
    allowed_paths: list[str]
    forbidden_paths: list[str]
    acceptance: list[str]
    facts: list[RepositoryFact] = field(default_factory=list)
    unknowns: list[Unknown] = field(default_factory=list)
    non_goals: list[str] = field(default_factory=list)


def resolve_receipt(receipt: str) -> str | None:
    match = re.fullmatch(r"(.+):(\d+)", receipt.strip())
    if not match or match.group(1) not in REPO:
        return None
    lines = REPO[match.group(1)]
    index = int(match.group(2)) - 1
    return lines[index] if 0 <= index < len(lines) else None


def overlaps(allowed: str, forbidden: str) -> bool:
    a, f = PurePosixPath(allowed), PurePosixPath(forbidden.rstrip("/*") or forbidden)
    return fnmatch.fnmatch(allowed, forbidden) or a == f or f in a.parents or a in f.parents


def validate(frame: TaskFrame) -> list[str]:
    issues: list[str] = []
    if not frame.goal.strip():
        issues.append("goal: empty")
    elif re.search(r"\.\w{2,4}\b", frame.goal) or frame.goal.lower().startswith(("edit ", "change ", "update ")):
        issues.append("goal: describes a file change, not an observable behavior")
    if not frame.allowed_paths:
        issues.append("allowed paths: empty")
    if not frame.forbidden_paths:
        issues.append("forbidden paths: empty (name the negative space)")
    for a in frame.allowed_paths:
        for f in frame.forbidden_paths:
            if overlaps(a, f):
                issues.append(f"paths: {a} is both allowed and forbidden by {f}")
    if not frame.acceptance:
        issues.append("acceptance: empty")
    issues += [f"acceptance: '{a}' is not a proof plan" for a in frame.acceptance if a.lower().strip() in VAGUE_ACCEPTANCE]
    for fact in frame.facts:
        line = resolve_receipt(fact.receipt) if fact.receipt.strip() else None
        if not fact.receipt.strip():
            issues.append(f"fact without receipt: {fact.claim}")
        elif line is None:
            issues.append(f"fact receipt does not resolve: {fact.receipt}")
        elif fact.expect.lower() not in line.lower():
            issues.append(f"fact contradicted by receipt {fact.receipt}: '{line.strip()}'")
    issues += [f"unknown has invalid kind '{u.kind}': {u.question}" for u in frame.unknowns if u.kind not in UNKNOWN_KINDS]
    return issues


def readiness(frame: TaskFrame) -> str:
    if validate(frame):
        return "BLOCKED"
    kinds = {u.kind for u in frame.unknowns}
    if "discoverable" in kinds:
        return "INVESTIGATE"
    if "human" in kinds:
        return "NEEDS_HUMAN"
    return "READY"


def investigate(frame: TaskFrame) -> TaskFrame:
    result = copy.deepcopy(frame)
    remaining = []
    for unknown in result.unknowns:
        hit = None
        if unknown.kind == "discoverable":
            hit = next(((p, i) for p, lines in REPO.items() for i, line in enumerate(lines, 1) if unknown.probe in line), None)
        if hit:
            result.facts.append(RepositoryFact(f"answered: {unknown.question}", f"{hit[0]}:{hit[1]}", unknown.probe))
        else:
            remaining.append(unknown)
    result.unknowns = remaining
    return result


def human_decides(frame: TaskFrame, answer: str) -> TaskFrame:
    result = copy.deepcopy(frame)
    for unknown in [u for u in result.unknowns if u.kind == "human"]:
        result.non_goals.append(f"{unknown.question} -> {answer}")
    result.unknowns = [u for u in result.unknowns if u.kind != "human"]
    return result


def render(frame: TaskFrame) -> str:
    out = [f"# Task frame: {frame.goal}", "", f"Status: {readiness(frame)}", "", "## Repository facts"]
    out += [f"- {f.claim} (`{f.receipt}`)" for f in frame.facts]
    out += ["", "## Allowed paths"] + [f"- `{p}`" for p in frame.allowed_paths]
    out += ["", "## Forbidden paths"] + [f"- `{p}`" for p in frame.forbidden_paths]
    out += ["", "## Acceptance evidence"] + [f"- `{a}`" for a in frame.acceptance]
    out += ["", "## Unknowns"] + ([f"- [{u.kind}] {u.question}" for u in frame.unknowns] or ["- none"])
    out += ["", "## Non-goals"] + ([f"- {n}" for n in frame.non_goals] or ["- none"])
    issues = validate(frame)
    if issues:
        out += ["", "## Blocking issues"] + [f"- {i}" for i in issues]
    return "\n".join(out) + "\n"


def example() -> TaskFrame:
    return TaskFrame(
        goal="Signing up with an email that already exists returns 409 and creates no second account",
        allowed_paths=["app/accounts.py", "tests/test_accounts.py"],
        forbidden_paths=["migrations/**", "deploy/**"],
        acceptance=["python3 -m unittest tests.test_accounts", "git diff --name-only | scope_check"],
        facts=[
            RepositoryFact("account writes go through AccountStore.save", "app/accounts.py:7", "store.save"),
            RepositoryFact("duplicates already use status 409 elsewhere", "tests/test_accounts.py:2", "409"),
            RepositoryFact("migrations need human approval", "AGENTS.md:1", "migrations"),
        ],
        unknowns=[
            Unknown("is email comparison case-insensitive?", "discoverable", "lower()"),
            Unknown("may we add a unique index on accounts.email?", "human"),
            Unknown("exact wording of the error message", "decidable"),
        ],
    )


def broken_variants() -> dict[str, TaskFrame]:
    variants = {}
    for name, mutate in {
        "file-shaped goal": lambda f: setattr(f, "goal", "edit app/accounts.py"),
        "fact with no receipt": lambda f: f.facts.append(RepositoryFact("we use bcrypt", "", "bcrypt")),
        "receipt contradicts claim": lambda f: f.facts.append(RepositoryFact("signup returns 200", "app/accounts.py:8", "200")),
        "allowed path under forbidden": lambda f: f.allowed_paths.append("migrations/0008_unique_email.sql"),
        "vague acceptance": lambda f: setattr(f, "acceptance", ["tests pass"]),
    }.items():
        frame = example()
        mutate(frame)
        variants[name] = frame
    return variants


def main() -> None:
    frame = example()
    print(f"v1 as written:          {readiness(frame)}")
    frame = investigate(frame)
    print(f"v2 after investigation: {readiness(frame)}  (resolved via {frame.facts[-1].receipt})")
    frame = human_decides(frame, "no migration in this slice; enforce in the service layer")
    print(f"v3 after human answer:  {readiness(frame)}\n")
    for name, variant in broken_variants().items():
        print(f"break '{name}': {readiness(variant)} -> {validate(variant)}")
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "outputs" / "task-frame.md"
        path.parent.mkdir(parents=True)
        path.write_text(render(frame))
        print(f"\nwrote {path.name} ({len(path.read_text().splitlines())} lines, fits on one screen)\n")
        print(path.read_text())


if __name__ == "__main__":
    main()
