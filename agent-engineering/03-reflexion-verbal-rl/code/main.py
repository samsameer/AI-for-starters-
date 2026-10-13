from __future__ import annotations

from dataclasses import dataclass, field

TARGET = 20
VALUES = range(1, 10)


@dataclass
class Reflection:
    trial: int
    text: str
    lesson: str
    expires_after: int


@dataclass
class EpisodicMemory:
    capacity: int = 4
    ttl_trials: int = 5
    items: list[Reflection] = field(default_factory=list)
    rejected: list[str] = field(default_factory=list)

    def add(self, reflection: Reflection) -> str:
        if any(r.lesson == reflection.lesson for r in self.items):
            self.rejected.append(f"duplicate lesson {reflection.lesson!r}")
            return "deduplicated"
        if reflection.lesson == "external":
            self.rejected.append(f"external failure, not a lesson: {reflection.text}")
            return "rejected as superstition"
        self.items.append(reflection)
        if len(self.items) > self.capacity:
            self.items.pop(0)
        return "stored"

    def expire(self, current_trial: int) -> None:
        self.items = [r for r in self.items if r.expires_after >= current_trial]

    def lessons(self) -> set[str]:
        return {r.lesson for r in self.items}

    def as_prompt(self) -> str:
        if not self.items:
            return "(no prior reflections)"
        return "\n".join(f"- trial {r.trial}: {r.text}" for r in self.items)


class Actor:
    def act(self, lessons: set[str], last: list[int] | None) -> list[int]:
        attempt = list(last) if last else [1, 2, 3]
        if "too_small" in lessons and sum(attempt) < TARGET:
            attempt = [min(9, v + 3) for v in attempt]
        if "too_large" in lessons and sum(attempt) > TARGET:
            attempt[-1] -= sum(attempt) - TARGET
        if "repeat" in lessons and last and attempt == last:
            attempt[0] = min(9, attempt[0] + 1)
        return attempt


@dataclass
class Verdict:
    success: bool
    delta: int
    heuristic: str | None


def evaluate(attempt: list[int], history: list[list[int]], tool_up: bool) -> Verdict:
    if not tool_up:
        return Verdict(False, 0, "tool_outage")
    if any(v not in VALUES for v in attempt):
        return Verdict(False, sum(attempt) - TARGET, "out_of_range")
    if history and attempt == history[-1]:
        return Verdict(False, sum(attempt) - TARGET, "repeat")
    total = sum(attempt)
    return Verdict(total == TARGET, total - TARGET, None)


def reflect(trial: int, attempt: list[int], verdict: Verdict, ttl: int) -> Reflection:
    if verdict.heuristic == "tool_outage":
        return Reflection(trial, "the checker was down; nothing to learn about the task", "external", trial + ttl)
    if verdict.heuristic == "repeat":
        return Reflection(trial, f"I repeated {attempt}; change at least one value", "repeat", trial + ttl)
    if verdict.delta < 0:
        return Reflection(trial, f"{attempt} sums to {sum(attempt)}, {-verdict.delta} short; raise values", "too_small", trial + ttl)
    return Reflection(trial, f"{attempt} sums to {sum(attempt)}, {verdict.delta} over; lower the last value", "too_large", trial + ttl)


@dataclass
class Trial:
    number: int
    attempt: list[int]
    verdict: Verdict
    note: str


def run(max_trials: int, use_memory: bool, outage_on: set[int]) -> tuple[list[Trial], EpisodicMemory]:
    actor = Actor()
    memory = EpisodicMemory()
    trials: list[Trial] = []
    history: list[list[int]] = []
    for number in range(1, max_trials + 1):
        memory.expire(number)
        lessons = memory.lessons() if use_memory else set()
        attempt = actor.act(lessons, history[-1] if history else None)
        verdict = evaluate(attempt, history, number not in outage_on)
        history.append(attempt)
        if verdict.success:
            trials.append(Trial(number, attempt, verdict, "success"))
            break
        reflection = reflect(number, attempt, verdict, memory.ttl_trials)
        status = memory.add(reflection) if use_memory else "memory off"
        trials.append(Trial(number, attempt, verdict, f"{reflection.text} [{status}]"))
    return trials, memory


def show(label: str, trials: list[Trial], memory: EpisodicMemory) -> None:
    print(f"\n{label}")
    print("-" * 72)
    for t in trials:
        mark = "PASS" if t.verdict.success else "fail"
        print(f"  trial {t.number}: {t.attempt} sum={sum(t.attempt):>2} {mark}  {t.note}")
    print(f"  result: {'solved' if trials[-1].verdict.success else 'not solved'} after {len(trials)} trial(s)")
    if memory.items:
        print("  episodic memory now prepended to the next prompt:")
        for line in memory.as_prompt().splitlines():
            print(f"    {line}")
    for reason in memory.rejected:
        print(f"  filtered: {reason}")


def main() -> None:
    print("=" * 72)
    print(f"LESSON 03 - REFLEXION: three ints in 1..9 that sum to {TARGET}")
    print("=" * 72)
    baseline, base_memory = run(6, use_memory=False, outage_on=set())
    show("BASELINE (no reflections carried between trials)", baseline, base_memory)
    reflexion, memory = run(6, use_memory=True, outage_on={2})
    show("REFLEXION (episodic memory on, checker outage on trial 2)", reflexion, memory)
    print()
    print("takeaways:")
    print("  - the baseline repeats itself; the evaluator's heuristic flags the loop but nothing is learned")
    print("  - reflections are specific and actionable, and they change the next attempt")
    print("  - the outage on trial 2 is not stored: reflecting on external failures breeds superstition")


if __name__ == "__main__":
    main()
