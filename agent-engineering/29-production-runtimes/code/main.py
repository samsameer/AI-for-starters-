from __future__ import annotations

import json
from collections import deque
from dataclasses import dataclass, field
from typing import Callable, Iterator


STEPS = ["parse", "plan", "search", "read", "answer"]


def agent_step(name: str, payload: str) -> str:
    return f"{name}:{payload[:24]}"


def request_response(payload: str, budget_steps: int = 10) -> str:
    if len(STEPS) > budget_steps:
        return "rejected: too long for a synchronous request"
    results = [agent_step(step, payload) for step in STEPS]
    return results[-1]


def streaming(payload: str) -> Iterator[str]:
    for index, step in enumerate(STEPS):
        yield json.dumps({"seq": index, "delta": agent_step(step, payload)})


@dataclass
class Journal:
    entries: dict[str, str] = field(default_factory=dict)
    side_effects: list[str] = field(default_factory=list)


class Crash(Exception):
    pass


def durable_run(run_id: str, payload: str, journal: Journal, crash_at: str | None) -> str:
    last = ""
    for step in STEPS:
        key = f"{run_id}/{step}"
        if key in journal.entries:
            last = journal.entries[key]
            continue
        if step == crash_at:
            raise Crash(f"worker died during {step}")
        last = agent_step(step, payload)
        journal.side_effects.append(key)
        journal.entries[key] = last
    return last


@dataclass
class Job:
    job_id: str
    payload: str
    idempotency_key: str
    attempts: int = 0


@dataclass
class QueueRuntime:
    max_attempts: int = 3
    queue: deque[Job] = field(default_factory=deque)
    dlq: list[Job] = field(default_factory=list)
    done: dict[str, str] = field(default_factory=dict)

    def enqueue(self, job: Job) -> None:
        self.queue.append(job)

    def drain(self, should_fail: Callable[[Job], bool]) -> list[str]:
        log: list[str] = []
        while self.queue:
            job = self.queue.popleft()
            if job.idempotency_key in self.done:
                log.append(f"{job.job_id}: duplicate, returned cached result")
                continue
            job.attempts += 1
            if should_fail(job):
                if job.attempts < self.max_attempts:
                    log.append(f"{job.job_id}: attempt {job.attempts} failed, retry with backoff {2 ** job.attempts}s")
                    self.queue.append(job)
                else:
                    log.append(f"{job.job_id}: attempt {job.attempts} failed, moved to DLQ")
                    self.dlq.append(job)
                continue
            self.done[job.idempotency_key] = request_response(job.payload)
            log.append(f"{job.job_id}: ok after {job.attempts} attempt(s)")
        return log


@dataclass
class EventBus:
    handlers: dict[str, list[Callable[[dict[str, str]], str]]] = field(default_factory=dict)

    def on(self, event_type: str, handler: Callable[[dict[str, str]], str]) -> None:
        self.handlers.setdefault(event_type, []).append(handler)

    def emit(self, event_type: str, event: dict[str, str]) -> list[str]:
        return [handler(event) for handler in self.handlers.get(event_type, [])] or [f"no subscriber for {event_type}"]


def cron_matches(spec: str, minute: int, hour: int) -> bool:
    spec_minute, spec_hour = spec.split()[:2]
    minute_ok = spec_minute == "*" or int(spec_minute) == minute
    hour_ok = spec_hour == "*" or int(spec_hour) == hour
    return minute_ok and hour_ok


def fire_schedule(schedule: dict[str, str], hours: range) -> list[str]:
    fired = []
    for hour in hours:
        for minute in (0, 15, 30, 45):
            for name, spec in schedule.items():
                if cron_matches(spec, minute, hour):
                    fired.append(f"{hour:02d}:{minute:02d} {name}")
    return fired


def pick_shape(seconds: float, user_waiting: bool, trigger: str, needs_approval: bool) -> str:
    if trigger == "schedule":
        return "scheduled + durable"
    if trigger == "event":
        return "event-driven + durable" if seconds > 30 else "event-driven"
    if needs_approval or seconds > 300:
        return "durable workflow (journaled steps, resumable approvals)"
    if seconds > 30:
        return "queue + worker + DLQ, notify on completion"
    if user_waiting and seconds > 3:
        return "streaming"
    return "request-response"


def main() -> None:
    print("1. request-response")
    print(f"   {request_response('list project files')}")

    print("\n2. streaming")
    for chunk in streaming("review PR 812"):
        print(f"   {chunk}")

    print("\n3. durable execution (journal survives a crash)")
    journal = Journal()
    try:
        durable_run("run-7", "migrate billing docs", journal, crash_at="read")
    except Crash as exc:
        print(f"   crash: {exc}; journaled steps={len(journal.entries)}")
    result = durable_run("run-7", "migrate billing docs", journal, crash_at=None)
    print(f"   resumed -> {result}")
    print(f"   side effects executed once each: {len(journal.side_effects) == len(set(journal.side_effects))} ({len(journal.side_effects)} total)")

    print("\n4. queue + retry + DLQ + idempotency")
    runtime = QueueRuntime()
    runtime.enqueue(Job("j1", "summarize ticket 1", "ticket-1"))
    runtime.enqueue(Job("j2", "summarize ticket 2", "ticket-2"))
    runtime.enqueue(Job("j3", "summarize ticket 1", "ticket-1"))
    flaky = {"j2"}
    for line in runtime.drain(lambda job: job.job_id in flaky):
        print(f"   {line}")
    print(f"   done={len(runtime.done)} dlq={[job.job_id for job in runtime.dlq]}")

    print("\n5. event-driven")
    bus = EventBus()
    bus.on("pr.opened", lambda e: f"review agent started for {e['ref']}")
    bus.on("pr.opened", lambda e: f"scope checker queued for {e['ref']}")
    for event_type, event in (("pr.opened", {"ref": "#812"}), ("issue.labeled", {"ref": "#90"})):
        for line in bus.emit(event_type, event):
            print(f"   {event_type} -> {line}")

    print("\n6. scheduled")
    schedule = {"memory.consolidate": "0 2 * * *", "eval.nightly": "30 3 * * *", "cost.report": "0 * * * *"}
    for line in fire_schedule(schedule, range(1, 4)):
        print(f"   {line}")

    print("\nshape picker")
    cases = [
        ("chat answer", 2, True, "user", False),
        ("long answer", 12, True, "user", False),
        ("batch summarize", 120, False, "user", False),
        ("refund with approval", 40, False, "user", True),
        ("PR opened", 90, False, "event", False),
        ("nightly eval", 600, False, "schedule", False),
    ]
    for name, seconds, waiting, trigger, approval in cases:
        print(f"   {name:22} -> {pick_shape(seconds, waiting, trigger, approval)}")


if __name__ == "__main__":
    main()
