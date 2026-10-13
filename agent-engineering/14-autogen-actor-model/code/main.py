from __future__ import annotations

import copy
import json
from dataclasses import asdict, dataclass, field
from typing import Any, Callable


@dataclass(frozen=True)
class ReviewRequest:
    change_id: str
    diff: str


@dataclass(frozen=True)
class Finding:
    change_id: str
    checker: str
    passed: bool
    detail: str


@dataclass(frozen=True)
class Verdict:
    change_id: str
    approved: bool
    reasons: tuple[str, ...]


@dataclass
class Envelope:
    sender: str
    recipient: str
    payload: Any
    attempt: int = 1


class Executor:
    def __init__(self, name: str) -> None:
        self.name = name
        self.handlers: dict[type, Callable[[Any, "Runtime"], None]] = {}

    def on(self, message_type: type, handler: Callable[[Any, "Runtime"], None]) -> None:
        self.handlers[message_type] = handler

    def snapshot(self) -> dict[str, Any]:
        return {}

    def restore(self, saved: dict[str, Any]) -> None:
        pass


@dataclass
class Runtime:
    executors: dict[str, Executor] = field(default_factory=dict)
    subscriptions: dict[str, list[str]] = field(default_factory=dict)
    pending: list[Envelope] = field(default_factory=list)
    dead_letters: list[tuple[str, str]] = field(default_factory=list)
    outputs: list[Any] = field(default_factory=list)
    checkpoints: list[dict[str, Any]] = field(default_factory=list)
    max_attempts: int = 2
    current_sender: str = "client"

    def register(self, executor: Executor, topics: tuple[str, ...] = ()) -> None:
        self.executors[executor.name] = executor
        for topic in topics:
            self.subscriptions.setdefault(topic, []).append(executor.name)

    def send(self, recipient: str, payload: Any) -> None:
        self.pending.append(Envelope(self.current_sender, recipient, payload))

    def publish(self, topic: str, payload: Any) -> None:
        for recipient in self.subscriptions.get(topic, []):
            self.send(recipient, payload)

    def yield_output(self, payload: Any) -> None:
        self.outputs.append(payload)

    def superstep(self, number: int) -> None:
        batch = sorted(self.pending, key=lambda e: (e.recipient, e.sender))
        self.pending = []
        for envelope in batch:
            label = f"{envelope.sender}->{envelope.recipient} {type(envelope.payload).__name__}"
            executor = self.executors.get(envelope.recipient)
            if executor is None:
                self.dead_letters.append((label, "no such executor"))
                print(f"  step {number} DLQ   {label}: no such executor")
                continue
            handler = executor.handlers.get(type(envelope.payload))
            if handler is None:
                self.dead_letters.append((label, "no handler for type"))
                print(f"  step {number} DLQ   {label}: no handler for type")
                continue
            self.current_sender = executor.name
            try:
                handler(envelope.payload, self)
                print(f"  step {number} ok    {label}")
            except Exception as error:
                if envelope.attempt < self.max_attempts:
                    self.pending.append(Envelope(envelope.sender, envelope.recipient, envelope.payload, envelope.attempt + 1))
                    print(f"  step {number} retry {label}: {error}")
                else:
                    self.dead_letters.append((label, str(error)))
                    print(f"  step {number} DLQ   {label}: {error}")
        self.checkpoints.append(self.capture())

    def capture(self) -> dict[str, Any]:
        return {
            "pending": [copy.deepcopy(e) for e in self.pending],
            "states": {name: copy.deepcopy(ex.snapshot()) for name, ex in self.executors.items()},
        }

    def restore(self, checkpoint: dict[str, Any]) -> None:
        self.pending = [copy.deepcopy(e) for e in checkpoint["pending"]]
        for name, saved in checkpoint["states"].items():
            self.executors[name].restore(copy.deepcopy(saved))

    def run(self, max_supersteps: int = 10) -> int:
        steps = 0
        while self.pending and steps < max_supersteps:
            steps += 1
            self.superstep(steps)
        self.current_sender = "client"
        return steps


def make_checker(name: str, rule: Callable[[str], tuple[bool, str]], failures_before_success: int = 0) -> Executor:
    checker = Executor(name)
    remaining = {"failures": failures_before_success}

    def handle(request: ReviewRequest, runtime: Runtime) -> None:
        if remaining["failures"] > 0:
            remaining["failures"] -= 1
            raise TimeoutError("sandbox did not answer")
        passed, detail = rule(request.diff)
        runtime.send("aggregator", Finding(request.change_id, name, passed, detail))

    checker.on(ReviewRequest, handle)
    return checker


class Aggregator(Executor):
    def __init__(self, expected: set[str]) -> None:
        super().__init__("aggregator")
        self.expected = expected
        self.findings: dict[str, dict[str, Finding]] = {}
        self.on(Finding, self.collect)

    def collect(self, finding: Finding, runtime: Runtime) -> None:
        bucket = self.findings.setdefault(finding.change_id, {})
        bucket[finding.checker] = finding
        if set(bucket) == self.expected:
            failed = tuple(f"{f.checker}: {f.detail}" for f in bucket.values() if not f.passed)
            runtime.yield_output(Verdict(finding.change_id, not failed, failed or ("all checks passed",)))

    def snapshot(self) -> dict[str, Any]:
        return {cid: {k: asdict(v) for k, v in fs.items()} for cid, fs in self.findings.items()}

    def restore(self, saved: dict[str, Any]) -> None:
        self.findings = {cid: {k: Finding(**v) for k, v in fs.items()} for cid, fs in saved.items()}


def style_rule(diff: str) -> tuple[bool, str]:
    long_lines = [line for line in diff.splitlines() if len(line) > 60]
    return (not long_lines, f"{len(long_lines)} line(s) over 60 chars")


def security_rule(diff: str) -> tuple[bool, str]:
    risky = "eval(" in diff or "shell=True" in diff
    return (not risky, "dangerous call found" if risky else "no dangerous calls")


def test_rule(diff: str) -> tuple[bool, str]:
    return ("def test_" in diff, "tests present" if "def test_" in diff else "no tests added")


def build_review_runtime() -> Runtime:
    runtime = Runtime()
    runtime.register(make_checker("style", style_rule), topics=("review",))
    runtime.register(make_checker("security", security_rule), topics=("review",))
    runtime.register(make_checker("tests", test_rule, failures_before_success=1), topics=("review",))
    runtime.register(Aggregator({"style", "security", "tests"}))
    return runtime


DIFF = "def parse(x):\n    return int(x)\n\ndef test_parse():\n    assert parse('3') == 3\n"
BAD_DIFF = "def run(cmd):\n    return subprocess.run(cmd, shell=True)\n"


def select_next_speaker(transcript: list[tuple[str, str]]) -> str:
    if not transcript:
        return "planner"
    last_speaker, last_text = transcript[-1]
    if last_speaker == "planner":
        return "coder"
    if last_speaker == "coder":
        return "critic"
    return "coder" if "REVISE" in last_text else "planner"


def group_chat(select: Callable[[list[tuple[str, str]]], str], max_turns: int) -> list[tuple[str, str]]:
    scripts = {
        "planner": iter(["plan: add retry with backoff", "plan: done"]),
        "coder": iter(["code v1: retry forever", "code v2: retry 3x with jitter", "code v3: polish"]),
        "critic": iter(["REVISE: unbounded retries", "APPROVED", "APPROVED"]),
    }
    transcript: list[tuple[str, str]] = []
    for _ in range(max_turns):
        speaker = select(transcript)
        transcript.append((speaker, next(scripts[speaker], "(nothing to add)")))
        if transcript[-1][1] == "APPROVED":
            break
    return transcript


def round_robin(transcript: list[tuple[str, str]]) -> str:
    order = ["planner", "coder", "critic"]
    return order[len(transcript) % len(order)]


def main() -> None:
    print("1. pub/sub fan-out in supersteps, one flaky checker retried, one bad address dead-lettered")
    runtime = build_review_runtime()
    runtime.publish("review", ReviewRequest("PR-7", DIFF))
    runtime.send("deployer", ReviewRequest("PR-7", DIFF))
    steps = runtime.run()
    print(f"  supersteps={steps} verdict={runtime.outputs}")
    print(f"  dead letters={runtime.dead_letters}")

    print("\n2. a risky change: same runtime, same actors, rejected verdict with reasons")
    runtime.publish("review", ReviewRequest("PR-8", BAD_DIFF))
    runtime.run()
    print(f"  verdict={runtime.outputs[-1]}")

    print("\n3. checkpoint at a superstep boundary, restore into a fresh runtime, finish identically")
    original = build_review_runtime()
    original.publish("review", ReviewRequest("PR-9", DIFF))
    original.superstep(1)
    saved = original.checkpoints[-1]
    print(f"  saved {len(saved['pending'])} pending message(s) after superstep 1")
    resumed = build_review_runtime()
    resumed.executors["tests"] = make_checker("tests", test_rule)
    resumed.restore(saved)
    resumed.run()
    print(f"  resumed verdict={resumed.outputs}")
    print(f"  checkpoint is plain data: {len(json.dumps(saved, default=str))} bytes")

    print("\n4. team topologies: round robin vs selector")
    for name, selector in [("round_robin", round_robin), ("selector", select_next_speaker)]:
        transcript = group_chat(selector, max_turns=8)
        turns = " | ".join(f"{s}: {t}" for s, t in transcript)
        print(f"  {name:<11} turns={len(transcript)}  {turns}")

    print("\nmessages are the only interface: failures stay inside one actor, and state checkpoints between supersteps.")


if __name__ == "__main__":
    main()
