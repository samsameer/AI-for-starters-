from __future__ import annotations

import json
import re
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path


ROUTER_LINES = [
    "# AGENTS.md",
    "",
    "Read in this order before acting:",
    "1. `agent_state.json`: where the last session stopped.",
    "2. `task_board.json`: what is in flight and what is next.",
    "3. `docs/agent-rules.md`: startup, scope and done rules (load on demand).",
    "",
    "Verification command: `python3 -m pytest -x`",
    "",
    "Definition of done: the active task is `done` on the board and the",
    "verification command exited 0.",
    "",
    "Hard rules: one task at a time; never edit `scripts/`; ask before new deps.",
]

API_ROUTER_LINES = [
    "# services/api/AGENTS.md",
    "",
    "Extends the root file for the API service.",
    "Run `python3 -m pytest services/api -x` instead of the full suite.",
]

RULES_LINES = [
    "# Agent rules",
    "",
    "## Startup",
    "## Scope",
    "## Definition of done",
    "## Uncertainty",
    "## Approval",
]


@dataclass
class AgentState:
    active_task_id: str = ""
    touched_files: list[str] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)
    next_action: str = "pick the next todo task from task_board.json"
    session: int = 0


@dataclass
class Task:
    id: str
    goal: str
    owner: str
    acceptance: list[str]
    files: list[str]
    status: str = "todo"


def seed_workbench(root: Path) -> None:
    (root / "docs").mkdir(parents=True, exist_ok=True)
    (root / "services" / "api").mkdir(parents=True, exist_ok=True)
    (root / "AGENTS.md").write_text("\n".join(ROUTER_LINES) + "\n")
    (root / "services" / "api" / "AGENTS.md").write_text("\n".join(API_ROUTER_LINES) + "\n")
    (root / "docs" / "agent-rules.md").write_text("\n".join(RULES_LINES) + "\n")
    (root / "agent_state.json").write_text(json.dumps(asdict(AgentState()), indent=2) + "\n")
    board = [
        Task("T-001", "validate /signup password length", "builder",
             ["pytest test_app.py::test_rejects_short_password"], ["app.py", "test_app.py"]),
        Task("T-002", "document the /signup contract", "builder",
             ["docs/api.md mentions the 8-character minimum"], ["docs/api.md"]),
        Task("T-003", "approve the release note", "human", ["release note signed off"], []),
    ]
    (root / "task_board.json").write_text(json.dumps([asdict(t) for t in board], indent=2) + "\n")


def lint_router(root: Path, max_lines: int = 80) -> list[str]:
    text = (root / "AGENTS.md").read_text()
    problems = []
    lines = text.splitlines()
    if not 10 <= len(lines) <= max_lines:
        problems.append(f"router has {len(lines)} lines, expected 10..{max_lines}")
    if "Verification command" not in text:
        problems.append("router does not name a verification command")
    for ref in re.findall(r"`([\w./-]+\.(?:md|json))`", text):
        if not (root / ref).exists():
            problems.append(f"router points at missing file {ref}")
    return problems


def instruction_chain(root: Path, working_file: str) -> list[str]:
    chain = []
    folder = (root / working_file).parent
    while True:
        candidate = folder / "AGENTS.md"
        if candidate.exists():
            chain.append(str(candidate.relative_to(root)))
        if folder == root:
            break
        folder = folder.parent
    return list(reversed(chain))


def load(root: Path) -> tuple[AgentState, list[Task]]:
    state = AgentState(**json.loads((root / "agent_state.json").read_text()))
    board = [Task(**t) for t in json.loads((root / "task_board.json").read_text())]
    return state, board


def save(root: Path, state: AgentState, board: list[Task]) -> None:
    (root / "agent_state.json").write_text(json.dumps(asdict(state), indent=2) + "\n")
    (root / "task_board.json").write_text(json.dumps([asdict(t) for t in board], indent=2) + "\n")


def run_one_turn(root: Path) -> str:
    state, board = load(root)
    state.session += 1
    if not state.active_task_id:
        candidate = next((t for t in board if t.status == "todo" and t.owner == "builder"), None)
        if candidate is None:
            waiting = [t.id for t in board if t.status == "todo"]
            state.next_action = f"idle: remaining tasks need a human {waiting}" if waiting else "idle: board empty"
            save(root, state, board)
            return state.next_action
        candidate.status = "in_progress"
        state.active_task_id = candidate.id
        state.next_action = f"edit {candidate.files[0]}"
        save(root, state, board)
        return f"pulled {candidate.id}"
    task = next(t for t in board if t.id == state.active_task_id)
    remaining = [f for f in task.files if f not in state.touched_files]
    if remaining:
        target = remaining[0]
        (root / target).parent.mkdir(parents=True, exist_ok=True)
        (root / target).write_text(f"work for {task.id}\n")
        state.touched_files.append(target)
        later = remaining[1:]
        state.next_action = f"edit {later[0]}" if later else f"run verification for {task.id}"
        save(root, state, board)
        return f"wrote {target}"
    task.status = "done"
    state.active_task_id = ""
    state.touched_files = []
    state.next_action = "pick the next todo task from task_board.json"
    save(root, state, board)
    return f"verified and closed {task.id}"


def snapshot(root: Path) -> dict[str, str]:
    return {p: (root / p).read_text() for p in ("agent_state.json", "task_board.json")}


def show_diff(before: dict[str, str], after: dict[str, str]) -> None:
    old_state, new_state = json.loads(before["agent_state.json"]), json.loads(after["agent_state.json"])
    for key in old_state:
        if key != "session" and old_state[key] != new_state[key]:
            print(f"      state.{key}: {old_state[key]!r} -> {new_state[key]!r}")
    old_board = {t["id"]: t["status"] for t in json.loads(before["task_board.json"])}
    for task in json.loads(after["task_board.json"]):
        if old_board[task["id"]] != task["status"]:
            print(f"      board.{task['id']}: {old_board[task['id']]} -> {task['status']}")


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        seed_workbench(root)
        print("workbench files:", sorted(str(p.relative_to(root)) for p in root.rglob("*") if p.is_file()))
        print("router lint:", lint_router(root) or "clean")
        print("instruction chain for services/api/handler.py:", instruction_chain(root, "services/api/handler.py"))
        print("instruction chain for app.py:", instruction_chain(root, "app.py"))

        print("\neach session starts cold: it reads only the files, never the previous chat")
        for _ in range(9):
            before = snapshot(root)
            event = run_one_turn(root)
            state, _ = load(root)
            print(f"  session {state.session}: {event}")
            show_diff(before, snapshot(root))
            if event.startswith("idle"):
                break

        _, board = load(root)
        print("\nfinal board:", [(t.id, t.status, t.owner) for t in board])

        bloated = root / "AGENTS.md"
        bloated.write_text(bloated.read_text() + "See `docs/style-guide.md` for tone.\n" + "Be careful.\n" * 90)
        print("lint after someone pastes a manual into the router:")
        for problem in lint_router(root):
            print(f"  - {problem}")


if __name__ == "__main__":
    main()
