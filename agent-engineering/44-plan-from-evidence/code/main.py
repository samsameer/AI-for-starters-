from __future__ import annotations

import json
import tempfile
from dataclasses import asdict, dataclass, replace
from pathlib import Path


@dataclass(frozen=True)
class WorkItem:
    id: str
    change: str
    evidence: tuple[str, ...]
    depends_on: tuple[str, ...]
    proof: str
    hours: float = 1.0
    irreversible: bool = False
    needs_resolved: tuple[str, ...] = ()
    resolves: tuple[str, ...] = ()


def find_cycle(items: list[WorkItem]) -> list[str]:
    graph = {i.id: list(i.depends_on) for i in items}
    color: dict[str, int] = {}
    stack: list[str] = []

    def visit(node: str) -> list[str]:
        color[node] = 1
        stack.append(node)
        for dep in graph.get(node, []):
            if color.get(dep) == 1:
                return stack[stack.index(dep):] + [dep]
            if dep in graph and color.get(dep) is None:
                found = visit(dep)
                if found:
                    return found
        color[node] = 2
        stack.pop()
        return []

    for node in sorted(graph):
        if color.get(node) is None:
            cycle = visit(node)
            if cycle:
                return cycle
    return []


def ancestors(item_id: str, by_id: dict[str, WorkItem]) -> set[str]:
    seen: set[str] = set()
    frontier = list(by_id[item_id].depends_on)
    while frontier:
        current = frontier.pop()
        if current in seen or current not in by_id:
            continue
        seen.add(current)
        frontier.extend(by_id[current].depends_on)
    return seen


def validate(items: list[WorkItem]) -> list[str]:
    issues: list[str] = []
    ids = [i.id for i in items]
    issues += [f"duplicate id: {d}" for d in sorted({x for x in ids if ids.count(x) > 1})]
    by_id = {i.id: i for i in items}
    for item in items:
        if not item.evidence:
            issues.append(f"{item.id}: no repository evidence")
        if not item.proof.strip():
            issues.append(f"{item.id}: no proof")
        elif "&&" in item.proof:
            issues.append(f"{item.id}: two proofs in one item, split it")
        missing = sorted(set(item.depends_on) - set(by_id))
        if missing:
            issues.append(f"{item.id}: depends on unknown items {missing}")
    if not any("unknown items" in i for i in issues):
        cycle = find_cycle(items)
        if cycle:
            issues.append(f"dependency cycle: {' -> '.join(cycle)}")
        else:
            for item in (i for i in items if i.irreversible):
                resolved = {u for a in ancestors(item.id, by_id) for u in by_id[a].resolves}
                for unknown in item.needs_resolved:
                    if unknown not in resolved:
                        issues.append(f"{item.id}: irreversible before '{unknown}' is resolved")
    return issues


def waves(items: list[WorkItem]) -> list[list[str]]:
    remaining = {i.id: set(i.depends_on) for i in items}
    done: set[str] = set()
    result: list[list[str]] = []
    while remaining:
        ready = sorted(k for k, deps in remaining.items() if deps <= done)
        if not ready:
            raise ValueError("cycle")
        result.append(ready)
        done.update(ready)
        for k in ready:
            del remaining[k]
    return result


def critical_path(items: list[WorkItem]) -> tuple[float, list[str]]:
    by_id = {i.id: i for i in items}
    finish: dict[str, float] = {}
    via: dict[str, str | None] = {}
    for wave in waves(items):
        for item_id in wave:
            deps = by_id[item_id].depends_on
            best = max(deps, key=lambda d: finish[d], default=None)
            finish[item_id] = (finish[best] if best else 0.0) + by_id[item_id].hours
            via[item_id] = best
    end = max(finish, key=finish.get)
    path = [end]
    while via[path[-1]]:
        path.append(via[path[-1]])
    return finish[end], path[::-1]


def apply_evidence(items: list[WorkItem], drop: str, receipt: str) -> list[WorkItem]:
    removed = next(i for i in items if i.id == drop)
    kept = []
    for item in items:
        if item.id == drop:
            continue
        if drop in item.depends_on:
            rewired = tuple(d for d in item.depends_on if d != drop) + tuple(d for d in removed.depends_on if d not in item.depends_on)
            item = replace(item, depends_on=rewired, evidence=item.evidence + (receipt,))
        kept.append(item)
    return kept


def next_safe(items: list[WorkItem], receipts: dict[str, int]) -> list[str]:
    done = {k for k, code in receipts.items() if code == 0}
    return sorted(i.id for i in items if i.id not in done and set(i.depends_on) <= done)


def example() -> list[WorkItem]:
    return [
        WorkItem("contract", "Write the failing test: duplicate email -> 409, typed envelope",
                 ("tests/test_accounts.py:2",), (), "python3 -m unittest tests.test_accounts (expect red)", 1.0),
        WorkItem("normalizer", "Add an email normalizer", ("app/accounts.py:6",), ("contract",),
                 "python3 -m unittest tests.test_normalize", 1.5),
        WorkItem("implementation", "Reject normalized duplicates in create_account", ("app/accounts.py:7",),
                 ("contract", "normalizer"), "python3 -m unittest tests.test_accounts", 2.0),
        WorkItem("docs", "Document the 409 response", ("docs/api.md:72",), ("contract",),
                 "python3 scripts/check_links.py", 0.5),
        WorkItem("merge-policy", "Human decides which existing duplicate account wins", ("ops/dup_report.csv:1",),
                 (), "decision recorded in docs/decisions/0012.md", 0.5, resolves=("duplicate winner policy",)),
        WorkItem("backfill", "Merge existing duplicate accounts", ("ops/dup_report.csv:1",),
                 ("implementation", "merge-policy"), "python3 scripts/backfill.py --dry-run", 1.0,
                 irreversible=True, needs_resolved=("duplicate winner policy",)),
        WorkItem("integration", "Run the full acceptance gate", ("pyproject.toml:31",),
                 ("implementation", "docs", "backfill"), "python3 -m unittest", 0.5),
    ]


def broken_plans() -> dict[str, list[WorkItem]]:
    base = example()
    swap = lambda item_id, **kw: [replace(i, **kw) if i.id == item_id else i for i in base]
    return {
        "missing evidence": swap("docs", evidence=()),
        "double proof": swap("docs", proof="check_links.py && spellcheck"),
        "unknown dependency": swap("docs", depends_on=("contract", "style-guide")),
        "cycle": swap("contract", depends_on=("integration",)),
        "irreversible too early": swap("backfill", depends_on=("implementation",)),
    }


def document(items: list[WorkItem]) -> dict:
    issues = validate(items)
    doc = {"status": "ready" if not issues else "blocked", "issues": issues, "items": [asdict(i) for i in items]}
    if not issues:
        hours, path = critical_path(items)
        doc |= {"waves": waves(items), "critical_path": path, "critical_hours": hours}
    return doc


def main() -> None:
    for name, plan in broken_plans().items():
        print(f"{name:24} -> {validate(plan)}")
    plan = example()
    doc = document(plan)
    print(f"\nv1 {doc['status']}: waves={doc['waves']}")
    print(f"   critical path {doc['critical_path']} = {doc['critical_hours']}h")
    plan = apply_evidence(plan, "normalizer", "app/accounts.py:3 normalize_email already exists")
    doc = document(plan)
    print(f"\nevidence: normalize_email exists -> drop 'normalizer'")
    print(f"v2 {doc['status']}: waves={doc['waves']}")
    print(f"   critical path {doc['critical_path']} = {doc['critical_hours']}h")
    receipts = {"contract": 0, "merge-policy": 0, "implementation": 1}
    print(f"\nresume with receipts {receipts}: next safe items = {next_safe(plan, receipts)}")
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "outputs" / "evidence-plan.json"
        out.parent.mkdir(parents=True)
        out.write_text(json.dumps(doc, indent=2))
        print(f"wrote {out.name}: {len(doc['items'])} items, status={json.loads(out.read_text())['status']}")


if __name__ == "__main__":
    main()
