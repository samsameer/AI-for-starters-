from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
from pathlib import Path
from typing import Callable

PACK_VERSION = "1.0.0"
STATE_FILES = ("agent_state.json", "task_board.json")
ALIASES = (".github/copilot-instructions.md", "GEMINI.md", ".cursor/rules/agents.md")
BUMP_BY_DIR = {"schemas": "major", "scripts": "minor", "docs": "patch", "AGENTS.md": "patch", "README.md": "patch"}
BUMP_ORDER = ["none", "patch", "minor", "major"]


def lines(*rows: str) -> str:
    return "\n".join(rows) + "\n"


def schema(required: list[str], properties: dict) -> str:
    return json.dumps({"type": "object", "required": required, "properties": properties}, indent=2) + "\n"


def pack_files() -> dict[str, str]:
    return {
        "AGENTS.md": lines(
            "# AGENTS.md", "",
            "Before acting, read in order:",
            "1. outputs/handoff/<latest>/handoff.json (where the last session stopped)",
            "2. agent_state.json and task_board.json",
            "3. docs/agent-rules.md, then the active task's scope contract", "",
            "Done means: scripts/verify_agent.py reports passed=true and a review report exists.",
            f"Pack version: {PACK_VERSION}"),
        "docs/agent-rules.md": lines(
            "# Agent rules", "",
            "- startup: read state before any tool call",
            "- forbidden: never write outside the scope contract",
            "- done: every acceptance command exits 0 on the latest run",
            "- uncertainty: open a question note instead of guessing",
            "- approval: new runtime dependencies need a human"),
        "docs/reliability-policy.md": lines(
            "# Reliability policy", "",
            "Absorbed failure modes: hallucinated action, scope creep, cascading errors, context loss, tool misuse.",
            "Overrides are HMAC-signed by a human and bound to the head commit."),
        "docs/handoff-protocol.md": lines(
            "# Handoff protocol", "",
            "Seven fields: summary, changed_files, commands_run, failed_attempts, open_risks, next_action, verdict_pointer.",
            "No clean state, no handoff. One active packet per branch and topic."),
        "docs/reviewer-rubric.md": lines(
            "# Reviewer rubric", "",
            "problem_fit, scope_discipline, assumptions, verification_quality, handoff_readiness: 0-2 each, anchored.",
            "Pass >= 7 with no zeros. System One first pass, LLM for uncertain and audited cases."),
        "schemas/agent_state.schema.json": schema(
            ["schema_version", "active_task_id", "next_action"],
            {"schema_version": {"type": "integer"}, "active_task_id": {"type": ["string", "null"]},
             "assumptions": {"type": "array"}, "blockers": {"type": "array"}, "next_action": {"type": "string"}}),
        "schemas/task_board.schema.json": schema(
            ["tasks"], {"tasks": {"type": "array", "items": {"required": ["id", "goal", "acceptance", "status"]}}}),
        "schemas/scope_contract.schema.json": schema(
            ["task_id", "allowed_files", "forbidden_files", "acceptance_criteria", "rollback_plan"],
            {"allowed_files": {"type": "array"}, "forbidden_files": {"type": "array"}}),
        "scripts/run_with_feedback.py": lines(
            "import json, subprocess, sys",
            "result = subprocess.run(sys.argv[1:], capture_output=True, text=True)",
            "record = {'command': ' '.join(sys.argv[1:]), 'exit_code': result.returncode}",
            "open('outputs/feedback_record.jsonl', 'a').write(json.dumps(record) + chr(10))",
            "sys.exit(result.returncode)"),
        "scripts/verify_agent.py": lines(
            "import json, sys",
            "verdict = json.load(open(sys.argv[1]))",
            "print('passed' if verdict.get('passed') else 'blocked')",
            "sys.exit(0 if verdict.get('passed') else 1)"),
        "scripts/init_agent.py": lines(
            "import json, pathlib",
            "state = json.loads(pathlib.Path('agent_state.json').read_text())",
            "print('next action:', state.get('next_action') or 'pick a task from the board')"),
        "scripts/generate_handoff.py": lines(
            "import json, sys",
            "fields = ['summary', 'changed_files', 'commands_run', 'failed_attempts', 'open_risks', 'next_action', 'verdict_pointer']",
            "packet = json.load(open(sys.argv[1]))",
            "missing = [f for f in fields if not packet.get(f) and f != 'failed_attempts']",
            "sys.exit('missing: ' + ', '.join(missing) if missing else 0)"),
        "README.md": lines(
            "# Agent workbench pack", "",
            "In: schemas (contract), scripts (runtime), docs (rules and rubric), AGENTS.md (router).",
            "Out: project tasks, vendor SDK calls, onboarding prose.",
            "Install: python3 bin/install.py <target> [--force] [--dry-run]"),
        "VERSION": PACK_VERSION + "\n",
    }


def digest(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def manifest(files: dict[str, str]) -> dict:
    return {"version": files["VERSION"].strip(), "files": {p: digest(t) for p, t in sorted(files.items())}}


def assemble(dest: Path, files: dict[str, str]) -> int:
    changed = 0
    for rel, text in {**files, "MANIFEST.json": json.dumps(manifest(files), indent=2) + "\n"}.items():
        path = dest / rel
        if path.exists() and path.read_text() == text:
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        changed += 1
    return changed


def lint(pack: Path) -> list[str]:
    recorded = json.loads((pack / "MANIFEST.json").read_text())
    problems = [f"drift: {rel}" for rel, h in recorded["files"].items()
                if not (pack / rel).exists() or digest((pack / rel).read_text()) != h]
    if (pack / "VERSION").read_text().strip() != recorded["version"]:
        problems.append("VERSION disagrees with MANIFEST")
    return problems


def required_bump(old: dict, new: dict) -> str:
    changed = {p for p in set(old["files"]) | set(new["files"]) if old["files"].get(p) != new["files"].get(p)} - {"VERSION"}
    levels = [BUMP_BY_DIR.get(p.split("/")[0], "minor") for p in changed]
    return max(levels, key=BUMP_ORDER.index, default="none")


def install(pack: Path, target: Path, force: bool = False, dry_run: bool = False) -> list[str]:
    files = {p: (pack / p).read_text() for p in json.loads((pack / "MANIFEST.json").read_text())["files"] if p != "README.md"}
    lock = target / ".workbench-version"
    agents = target / "AGENTS.md"
    if agents.exists() and agents.read_text() != files["AGENTS.md"] and not lock.exists() and not force:
        return ["REFUSED: target has its own AGENTS.md; pass --force to replace it"]
    plan = []
    for rel, text in files.items():
        if rel == "VERSION":
            continue
        if not (target / rel).exists() or (target / rel).read_text() != text:
            plan.append(f"write {rel}")
    for alias in ALIASES:
        if not (target / alias).exists():
            plan.append(f"alias {alias} -> AGENTS.md")
    for state in STATE_FILES:
        if not (target / state).exists():
            plan.append(f"seed {state}")
    if not lock.exists() or lock.read_text().strip() != files["VERSION"].strip():
        plan.append(f"lock .workbench-version = {files['VERSION'].strip()}")
    if dry_run or not plan:
        return plan or [f"already at {files['VERSION'].strip()}: nothing to do"]
    for action in plan:
        verb, rel = action.split(" ", 2)[:2]
        path = target / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        if verb == "write":
            path.write_text(files[rel])
        elif verb == "alias":
            path.write_text("Instructions live in AGENTS.md at the repo root.\n")
        elif verb == "seed":
            seed = {"schema_version": 1, "active_task_id": None, "next_action": ""} if rel == "agent_state.json" else {"tasks": []}
            path.write_text(json.dumps(seed) + "\n")
        else:
            lock.write_text(files["VERSION"])
    return plan


def uninstall(pack: Path, target: Path) -> list[str]:
    seeds = {"agent_state.json": {"schema_version": 1, "active_task_id": None, "next_action": ""}, "task_board.json": {"tasks": []}}
    touched = [s for s in STATE_FILES if (target / s).exists() and json.loads((target / s).read_text()) != seeds[s]]
    if touched:
        return [f"REFUSED: {s} has real history; it belongs to the repo, not the pack" for s in touched]
    removed = []
    for rel in list(json.loads((pack / "MANIFEST.json").read_text())["files"]) + list(ALIASES) + [".workbench-version"]:
        if (target / rel).exists():
            (target / rel).unlink()
            removed.append(rel)
    return [f"removed {len(removed)} pack files; state files kept"]


def acceptance_strong(signup: Callable[[str], int]) -> bool:
    return signup("longenough") == 200 and signup("short") == 422


def acceptance_weak(signup: Callable[[str], int]) -> bool:
    return signup("longenough") == 200


def show_tree(root: Path) -> None:
    for path in sorted(root.rglob("*")):
        if path.is_file():
            print(f"  {path.relative_to(root)}")


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        pack = base / "agent-workbench-pack"
        files = pack_files()
        print(f"assemble: {assemble(pack, files)} files written; re-run: {assemble(pack, files)} written (idempotent)")
        show_tree(pack)
        print(f"lint: {lint(pack) or 'clean'}")

        repo = base / "fresh-repo"
        repo.mkdir()
        print(f"\ndry-run install: {len(install(pack, repo, dry_run=True))} planned actions, nothing written: {not any(repo.iterdir())}")
        print(f"install: {len(install(pack, repo))} actions; second install: {install(pack, repo)}")

        custom = base / "repo-with-own-agents-md"
        custom.mkdir()
        (custom / "AGENTS.md").write_text("team-specific rules\n")
        print(f"install over a foreign AGENTS.md: {install(pack, custom)}")

        (repo / "task_board.json").write_text(json.dumps({"tasks": [{"id": "T-001", "status": "in_progress"}]}))
        print(f"\nuninstall with real board history: {uninstall(pack, repo)}")
        clean = base / "clean-repo"
        clean.mkdir()
        install(pack, clean)
        print(f"uninstall on untouched repo: {uninstall(pack, clean)}")

        old = manifest(files)
        doc_edit = {**files, "docs/agent-rules.md": files["docs/agent-rules.md"] + "- secrets: never print env vars\n"}
        (pack / "docs/agent-rules.md").write_text(doc_edit["docs/agent-rules.md"])
        print(f"\nlint after hand edit: {lint(pack)}")
        print(f"required bump for doc edit: {required_bump(old, manifest(doc_edit))}")
        state_schema = files["schemas/agent_state.schema.json"].replace('"integer"', '"string"')
        schema_edit = {**files, "schemas/agent_state.schema.json": state_schema}
        print(f"required bump for schema edit: {required_bump(old, manifest(schema_edit))}")
        shutil.rmtree(pack)

    correct = lambda pw: 422 if len(pw) < 8 else 200
    mutant = lambda pw: 200
    print("\nchallenge the acceptance check with a deliberate wrong result:")
    for name, check in (("weak (happy path only)", acceptance_weak), ("strong (contract)", acceptance_strong)):
        print(f"  {name:24} correct={check(correct)} mutant={check(mutant)} -> "
              f"{'detects the defect' if check(correct) and not check(mutant) else 'TOO WEAK, strengthen before trusting'}")


if __name__ == "__main__":
    main()
