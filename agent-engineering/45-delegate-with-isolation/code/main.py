from __future__ import annotations

import json
import tempfile
from dataclasses import asdict, dataclass, replace
from pathlib import Path, PurePosixPath


@dataclass(frozen=True)
class WorkUnit:
    id: str
    owner: str
    paths: tuple[str, ...]
    depends_on: tuple[str, ...]
    proof: str
    readonly: bool = False
    isolation: str = "worktree"
    interfaces: tuple[str, ...] = ()
    output_dir: str = ""


@dataclass(frozen=True)
class WorkerResult:
    unit_id: str
    changed: tuple[str, ...]
    proof_exit: int
    decisions: tuple[str, ...] = ()


def owns(path: str, owned: str) -> bool:
    a, b = PurePosixPath(path), PurePosixPath(owned)
    return a == b or b in a.parents


def overlap(left: str, right: str) -> bool:
    return owns(left, right) or owns(right, left)


def waves(units: list[WorkUnit]) -> list[list[str]]:
    remaining = {u.id: set(u.depends_on) for u in units}
    if any(not deps <= set(remaining) for deps in remaining.values()):
        raise ValueError("unknown dependency")
    done: set[str] = set()
    result = []
    while remaining:
        ready = sorted(k for k, deps in remaining.items() if deps <= done)
        if not ready:
            raise ValueError("dependency cycle")
        result.append(ready)
        done.update(ready)
        for k in ready:
            del remaining[k]
    return result


def check(units: list[WorkUnit], frozen_interfaces: set[str]) -> dict:
    issues: list[str] = []
    ids = [u.id for u in units]
    issues += [f"duplicate id {d}" for d in sorted({i for i in ids if ids.count(i) > 1})]
    issues += [f"{u.id}: no proof" for u in units if not u.proof.strip()]
    writers = [u for u in units if not u.readonly]
    for i, left in enumerate(writers):
        for right in writers[i + 1:]:
            issues += [f"ownership: {left.id} and {right.id} overlap at {a} / {b}"
                       for a in left.paths for b in right.paths if overlap(a, b)]
    if issues:
        return {"status": "blocked", "issues": issues, "waves": []}
    by_id = {u.id: u for u in units}
    plan_waves = waves(units)
    for wave in plan_waves:
        members = [by_id[k] for k in wave]
        wave_writers = [u for u in members if not u.readonly]
        for i, left in enumerate(members):
            for right in members[i + 1:]:
                shared = (set(left.interfaces) & set(right.interfaces)) - frozen_interfaces
                issues += [f"decision: {left.id} and {right.id} both depend on unfrozen interface '{s}'" for s in sorted(shared)]
        if len(wave_writers) > 1:
            issues += [f"filesystem: {u.id} writes in parallel without isolation" for u in wave_writers if u.isolation == "shared"]
        dirs = [u.output_dir for u in members]
        issues += [f"state: output dir '{d}' shared in wave {wave}" for d in sorted({d for d in dirs if dirs.count(d) > 1})]
    return {"status": "ready" if not issues else "blocked", "issues": issues, "waves": plan_waves}


def provision(unit: WorkUnit) -> str:
    if unit.isolation == "worktree":
        return f"git worktree add ../wt-{unit.id} -b agent/{unit.id}"
    if unit.isolation == "sandbox":
        return f"sandbox {unit.id}: own container, fresh repo clone, egress allowlist [pypi.org], output -> {unit.output_dir}"
    return "shared checkout (read-only)" if unit.readonly else "shared checkout"


def integrate(units: list[WorkUnit], results: dict[str, WorkerResult]) -> dict:
    by_id = {u.id: u for u in units}
    merged, rejected, cancelled, log = [], {}, [], []
    for wave in waves(units):
        for unit_id in wave:
            unit = by_id[unit_id]
            if any(d in rejected or d in cancelled for d in unit.depends_on):
                cancelled.append(unit_id)
                log.append(f"cancel {unit_id}: dependency did not merge")
                continue
            result = results[unit_id]
            stray = [p for p in result.changed if not any(owns(p, o) for o in unit.paths)]
            if unit.readonly and result.changed:
                rejected[unit_id] = f"read-only unit changed {list(result.changed)}"
            elif stray:
                rejected[unit_id] = f"hidden scope expansion {stray}"
            elif result.proof_exit != 0:
                rejected[unit_id] = f"proof exited {result.proof_exit}"
            else:
                merged.append(unit_id)
                log.append(f"merge {unit_id} (files={len(result.changed)}, proof ok)"
                           + (f"; new decisions: {list(result.decisions)}" if result.decisions else ""))
                continue
            log.append(f"reject {unit_id}: {rejected[unit_id]}")
    return {"merged": merged, "rejected": rejected, "cancelled": cancelled, "log": log}


def good_plan() -> list[WorkUnit]:
    return [
        WorkUnit("research", "worker-research", ("notes/dup-emails.md",), (), "fact table with receipts",
                 readonly=True, isolation="shared", output_dir="out/research"),
        WorkUnit("api", "worker-api", ("app/api", "tests/test_api.py"), (), "python3 -m unittest tests.test_api",
                 interfaces=("AccountError envelope",), output_dir="out/api"),
        WorkUnit("docs", "worker-docs", ("docs/api.md",), (), "python3 scripts/check_links.py",
                 isolation="sandbox", interfaces=("AccountError envelope",), output_dir="out/docs"),
        WorkUnit("integration", "integrator", ("tests/test_integration.py",), ("api", "docs", "research"),
                 "python3 -m unittest", output_dir="out/integration"),
    ]


def bad_plan() -> list[WorkUnit]:
    plan = good_plan()
    return [replace(plan[0], output_dir="out/shared"),
            replace(plan[1], isolation="shared", output_dir="out/shared"),
            replace(plan[2], isolation="shared", output_dir="out/docs"),
            plan[3]]


def main() -> None:
    frozen = {"AccountError envelope"}
    print("unfrozen interface + shared checkout + shared output dir:")
    for issue in check(bad_plan(), frozen_interfaces=set())["issues"]:
        print(f"  blocked: {issue}")
    overlapping = [replace(u, paths=("app",)) if u.id == "docs" else u for u in good_plan()]
    print(f"docs unit owning 'app/': {check(overlapping, frozen)['issues']}")

    plan = good_plan()
    report = check(plan, frozen)
    print(f"\ngood plan: {report['status']}, waves={report['waves']}")
    for unit in plan:
        print(f"  {unit.id:12} {provision(unit)}")

    honest = {
        "research": WorkerResult("research", (), 0),
        "api": WorkerResult("api", ("app/api/accounts.py", "tests/test_api.py"), 0, ("409 body uses error.type",)),
        "docs": WorkerResult("docs", ("docs/api.md",), 0),
        "integration": WorkerResult("integration", ("tests/test_integration.py",), 0),
    }
    creep = {**honest, "docs": WorkerResult("docs", ("docs/api.md", "app/api/accounts.py"), 0)}
    for label, results in (("run 1, honest workers", honest), ("run 2, docs worker edits app/api", creep)):
        outcome = integrate(plan, results)
        print(f"\n{label}:")
        for line in outcome["log"]:
            print(f"  {line}")
        owned = [p for u in plan for p in u.paths]
        final = sorted({p for u in outcome["merged"] for p in results[u].changed})
        outside = [p for p in final if not any(owns(p, o) for o in owned)]
        print(f"  final changed set {final}; outside every contract: {outside or 'none'}")

    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "outputs" / "delegation-plan.json"
        out.parent.mkdir(parents=True)
        out.write_text(json.dumps({**report, "frozen_interfaces": sorted(frozen),
                                   "units": [asdict(u) | {"provision": provision(u)} for u in plan]}, indent=2))
        print(f"\nwrote {out.name} ({len(plan)} units)")


if __name__ == "__main__":
    main()
