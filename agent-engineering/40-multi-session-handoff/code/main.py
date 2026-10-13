from __future__ import annotations

import hashlib
import json
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path

TAIL_K = 3
WRAP_UP_CONTEXT = 0.6
TEMP_SUFFIXES = (".tmp", ".orig", ".rej")


@dataclass
class WorkbenchSnapshot:
    task_id: str
    topic: str
    branch: str
    expected_branch: str
    head_commit: str
    last_green_commit: str
    state: dict
    verdict: dict
    review: dict
    feedback: list[dict]
    changed_files: list[str]
    uncommitted: list[str] = field(default_factory=list)
    untracked: list[str] = field(default_factory=list)
    board_status: str = "done"


@dataclass
class HandoffPayload:
    task_id: str
    status: str
    branch: str
    last_known_good_commit: str
    summary: str
    changed_files: list[str]
    commands_run: list[str]
    failed_attempts: list[str]
    open_risks: list[dict]
    next_action: str
    verdict_pointer: dict
    resume: dict
    feedback_tail: list[dict]


class SessionStore:
    def __init__(self) -> None:
        self.sessions: dict[str, list[dict]] = {}
        self.parents: dict[str, tuple[str, int] | None] = {}

    def start(self, session_id: str) -> str:
        self.sessions[session_id] = []
        self.parents[session_id] = None
        return session_id

    def append(self, session_id: str, role: str, text: str) -> int:
        entries = self.sessions[session_id]
        entries.append({"index": len(entries), "role": role, "text": text})
        return len(entries) - 1

    def edit(self, session_id: str, index: int, text: str) -> None:
        raise PermissionError(f"{session_id}[{index}] is append-only; fork instead of rewriting history")

    def resume(self, session_id: str) -> str:
        return session_id

    def fork(self, session_id: str, at_index: int) -> str:
        children = [s for s, p in self.parents.items() if p and p[0] == session_id]
        child = f"{session_id}.fork{len(children) + 1}"
        self.sessions[child] = [dict(e) for e in self.sessions[session_id][: at_index + 1]]
        self.parents[child] = (session_id, at_index)
        return child


def clean_state_issues(snap: WorkbenchSnapshot) -> list[str]:
    issues = [f"uncommitted change: {p}" for p in snap.uncommitted]
    issues += [f"temp artifact left behind: {p}" for p in snap.untracked if p.endswith(TEMP_SUFFIXES)]
    named_risks = " ".join(snap.state.get("blockers", []))
    last = {}
    for record in snap.feedback:
        last[record["command"]] = record["exit_code"]
    for command, code in last.items():
        if code != 0 and command not in named_risks:
            issues.append(f"silent red check: {command} last exited {code}")
    if snap.verdict.get("passed") and snap.board_status != "done":
        issues.append(f"stale board: gate passed but board says {snap.board_status}")
    if snap.branch != snap.expected_branch:
        issues.append(f"wrong branch: on {snap.branch}, expected {snap.expected_branch}")
    return issues


def trim_feedback(records: list[dict]) -> list[dict]:
    keep = set(range(max(0, len(records) - TAIL_K), len(records)))
    keep |= {i for i, r in enumerate(records) if r.get("exit_code") != 0}
    return [records[i] | {"seq": i} for i in sorted(keep)]


def derive_risks(snap: WorkbenchSnapshot) -> list[dict]:
    risks = [{"severity": f["severity"], "detail": f["detail"]}
             for f in snap.verdict.get("findings", []) if f["severity"] in ("warn", "block")]
    risks += [{"severity": "warn", "detail": f"open blocker: {b}"} for b in snap.state.get("blockers", [])]
    if snap.review.get("total", 10) < 7:
        risks.append({"severity": "warn", "detail": f"review total {snap.review['total']} below 7"})
    return sorted(risks, key=lambda r: (r["severity"] != "block", r["detail"]))


def decide_continuation(context_used: float, dead_end_from: int | None, last_good_entry: int) -> dict:
    if context_used >= WRAP_UP_CONTEXT:
        return {"mode": "fresh_session_from_packet", "reason": f"context at {context_used:.0%} >= {WRAP_UP_CONTEXT:.0%} budget"}
    if dead_end_from is not None:
        return {"mode": "fork", "at_entry": last_good_entry, "reason": f"entries from {dead_end_from} are a dead end"}
    return {"mode": "resume", "reason": "context healthy, transcript still useful"}


def generate_handoff(snap: WorkbenchSnapshot, session_id: str, continuation: dict) -> tuple[str, HandoffPayload]:
    issues = clean_state_issues(snap)
    if issues:
        raise RuntimeError("refusing to write a handoff on a dirty workbench: " + "; ".join(issues))
    next_action = snap.state.get("next_action") or ""
    if not next_action:
        raise RuntimeError("no next_action: this would be a status report, not a handoff")
    failed = [f"{r['command']} -> exit {r['exit_code']}" for r in snap.feedback if r["exit_code"] != 0]
    payload = HandoffPayload(
        task_id=snap.task_id,
        status="active",
        branch=snap.branch,
        last_known_good_commit=snap.last_green_commit,
        summary=f"{snap.task_id} ({snap.topic}): gate passed={snap.verdict.get('passed')}, "
                f"review={snap.review.get('verdict')} {snap.review.get('total')}/10",
        changed_files=sorted(snap.changed_files),
        commands_run=sorted({r["command"] for r in snap.feedback}),
        failed_attempts=failed,
        open_risks=derive_risks(snap),
        next_action=next_action,
        verdict_pointer={"verification": f"outputs/verification/{snap.task_id}.json",
                         "review": f"outputs/review/{snap.task_id}.json"},
        resume={"session_id": session_id, **continuation},
        feedback_tail=trim_feedback(snap.feedback),
    )
    return render_markdown(payload), payload


def bullets(items: list[str]) -> list[str]:
    return [f"- {item}" for item in items] or ["- none"]


def render_markdown(p: HandoffPayload) -> str:
    lines = [f"# Handoff: {p.task_id} [{p.status}]", "",
             f"Branch `{p.branch}`, last known good `{p.last_known_good_commit}`.", "",
             f"**Summary.** {p.summary}", "", "## Changed files", *bullets([f"`{f}`" for f in p.changed_files]),
             "", "## Commands run", *bullets([f"`{c}`" for c in p.commands_run]),
             "", "## Failed attempts", *bullets(p.failed_attempts),
             "", "## Open risks", *bullets([f"[{r['severity']}] {r['detail']}" for r in p.open_risks]),
             "", "## Next action", p.next_action,
             "", "## Resume", f"{p.resume['mode']} from session `{p.resume['session_id']}`: {p.resume['reason']}",
             "", "## Receipts", *bullets([f"{k}: `{v}`" for k, v in p.verdict_pointer.items()])]
    return "\n".join(lines) + "\n"


class HandoffRegistry:
    def __init__(self) -> None:
        self.entries: list[dict] = []

    def publish(self, payload: HandoffPayload, topic: str) -> None:
        for entry in self.entries:
            if entry["branch"] == payload.branch and entry["topic"] == topic and entry["status"] == "active":
                entry["status"] = "superseded"
        self.entries.append({"task_id": payload.task_id, "branch": payload.branch, "topic": topic, "status": "active"})

    def active(self, branch: str, topic: str) -> list[dict]:
        return [e for e in self.entries if e["branch"] == branch and e["topic"] == topic and e["status"] == "active"]


def snapshot(dirty: bool) -> WorkbenchSnapshot:
    feedback = [
        {"command": "python3 -m unittest tests.test_signup", "exit_code": 1},
        {"command": "ruff check app", "exit_code": 0},
        {"command": "python3 -m unittest tests.test_signup", "exit_code": 0},
        {"command": "python3 -m unittest", "exit_code": 0},
        {"command": "ruff check app", "exit_code": 0},
    ]
    if dirty:
        feedback.append({"command": "python3 -m unittest tests.test_rate_limit", "exit_code": 1})
    return WorkbenchSnapshot(
        task_id="T-014", topic="signup-validation", branch="agent/T-014" if not dirty else "main",
        expected_branch="agent/T-014", head_commit="9f8e7d6", last_green_commit="9f8e7d6",
        state={"active_task_id": None, "blockers": ["awaiting decision on rate-limit window"],
               "next_action": "open PR from agent/T-014 and request review"},
        verdict={"passed": True, "findings": [{"severity": "warn", "detail": "off-scope: README.md"}]},
        review={"verdict": "pass", "total": 8},
        feedback=feedback,
        changed_files=["tests/test_signup.py", "app/signup.py", "README.md"],
        uncommitted=["app/signup.py"] if dirty else [],
        untracked=["app/signup.py.orig", "scratch.tmp"] if dirty else [],
        board_status="in_progress" if dirty else "done",
    )


def main() -> None:
    store = SessionStore()
    sid = store.start("sess-041")
    for i, text in enumerate(["read state", "plan", "edit signup", "try regex validator", "regex loops", "revert, use length check", "tests green"]):
        store.append(sid, "assistant" if i % 2 else "user", text)
    try:
        store.edit(sid, 3, "pretend the regex never happened")
    except PermissionError as err:
        print(f"edit rejected: {err}")
    print("\ncontinuation decisions:")
    for label, ctx, dead in (("healthy", 0.35, None), ("dead end at entry 3", 0.40, 3), ("long session", 0.72, None)):
        choice = decide_continuation(ctx, dead, last_good_entry=2)
        target = store.fork(sid, choice["at_entry"]) if choice["mode"] == "fork" else store.resume(sid)
        print(f"  {label:20} -> {choice['mode']:26} target={target} ({choice['reason']})")
    print(f"  fork lineage: {store.parents}")

    print("\nsession end on a dirty workbench:")
    try:
        generate_handoff(snapshot(dirty=True), sid, decide_continuation(0.72, None, 2))
    except RuntimeError as err:
        for issue in str(err).split(": ", 1)[1].split("; "):
            print(f"  blocked: {issue}")

    continuation = decide_continuation(0.72, None, 2)
    md, payload = generate_handoff(snapshot(dirty=False), sid, continuation)
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "outputs" / "handoff" / sid
        out.mkdir(parents=True)
        digests = []
        for _ in range(2):
            md_again, payload_again = generate_handoff(snapshot(dirty=False), sid, continuation)
            body = json.dumps(asdict(payload_again), indent=2, sort_keys=True)
            (out / "handoff.json").write_text(body)
            (out / "handoff.md").write_text(md_again)
            digests.append(hashlib.sha256((body + md_again).encode()).hexdigest()[:16])
        print(f"\nclean workbench -> packet written twice, digests {digests}, identical={digests[0] == digests[1]}")
        print(f"files: {sorted(p.name for p in out.iterdir())}\n")
    print(md)
    registry = HandoffRegistry()
    registry.publish(payload, "signup-validation")
    registry.publish(payload, "signup-validation")
    print(f"registry: {[e['status'] for e in registry.entries]}; active for branch: {len(registry.active(payload.branch, 'signup-validation'))}")


if __name__ == "__main__":
    main()
