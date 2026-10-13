from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Callable

TOOLS: dict[str, Callable[..., str]] = {}
CALLS: list[str] = []


def tool(name: str) -> Callable[[Callable[..., str]], Callable[..., str]]:
    def register(fn: Callable[..., str]) -> Callable[..., str]:
        TOOLS[name] = fn
        return fn
    return register


@tool("search_notes")
def search_notes(query: str) -> str:
    CALLS.append(f"search_notes({query!r})")
    corpus = {
        "graphs": "graph runtimes checkpoint state after each node",
        "actors": "actor runtimes isolate failures behind typed messages",
        "decisions": "decision models answer typed questions in tens of milliseconds",
    }
    return "; ".join(text for key, text in corpus.items() if key in query or query == "all")


@dataclass
class Agent:
    role: str
    goal: str
    backstory: str
    tools: tuple[str, ...] = ()

    def prompt_size(self) -> int:
        return len(self.role) + len(self.goal) + len(self.backstory)


@dataclass
class Task:
    name: str
    description: str
    expected_output: str
    agent: Agent
    context: tuple[str, ...] = ()
    guardrail: Callable[[str], tuple[bool, str]] | None = None
    max_retries: int = 2


@dataclass
class Memory:
    short_term: list[str] = field(default_factory=list)
    long_term: dict[str, str] = field(default_factory=dict)
    entities: dict[str, dict[str, str]] = field(default_factory=dict)

    def recall(self, topic: str) -> str:
        return self.long_term.get(topic, "")


def fake_llm(agent: Agent, task: Task, context: str, attempt: int, memory: Memory, topic: str) -> str:
    if agent.role == "Researcher":
        prior = memory.recall(topic)
        found = TOOLS["search_notes"]("all")
        return f"FACTS: {found}" + (f" | PRIOR: {prior}" if prior else "")
    if agent.role == "Writer":
        facts = context.split("FACTS: ")[-1].split(" | ")[0].split("; ")
        if attempt == 1:
            return "Agents are great."
        return "\n".join(f"- {fact}" for fact in facts)
    if agent.role == "Editor":
        bullets = [line for line in context.splitlines() if line.startswith("- ")]
        return json.dumps({"title": f"Brief: {topic}", "points": len(bullets), "body": bullets})
    return "done"


def at_least_three_bullets(output: str) -> tuple[bool, str]:
    count = sum(1 for line in output.splitlines() if line.startswith("- "))
    return (count >= 3, output if count >= 3 else f"need 3 bullets, got {count}")


def valid_brief(output: str) -> tuple[bool, str]:
    try:
        data = json.loads(output)
    except json.JSONDecodeError:
        return False, "not JSON"
    ok = {"title", "points", "body"} <= set(data)
    return ok, output if ok else "missing keys"


def execute(task: Task, outputs: dict[str, str], memory: Memory, topic: str, llm_calls: list[str]) -> str:
    context = "\n".join(outputs[name] for name in task.context)
    for attempt in range(1, task.max_retries + 2):
        llm_calls.append(f"{task.agent.role}:{task.name}#{attempt}")
        result = fake_llm(task.agent, task, context, attempt, memory, topic)
        if task.guardrail is None:
            return result
        ok, feedback = task.guardrail(result)
        if ok:
            return result
        print(f"    guardrail rejected {task.name} attempt {attempt}: {feedback}")
    raise RuntimeError(f"{task.name} failed its guardrail")


researcher = Agent("Researcher", "Collect facts", "Careful analyst who cites sources.", ("search_notes",))
writer = Agent("Writer", "Draft a short brief", "Plain-spoken technical writer.")
editor = Agent("Editor", "Return a structured brief", "Strict editor who enforces the format.")


def make_tasks() -> list[Task]:
    return [
        Task("research", "Find facts on {topic}", "3+ facts", researcher),
        Task("draft", "Write bullets", "3+ bullet lines", writer, ("research",), at_least_three_bullets),
        Task("edit", "Return JSON", "JSON with title, points, body", editor, ("draft",), valid_brief),
    ]


@dataclass
class Crew:
    tasks: list[Task]
    process: str = "sequential"
    memory: Memory = field(default_factory=Memory)
    outputs: dict[str, str] = field(default_factory=dict)

    def kickoff(self, topic: str) -> tuple[str, list[str]]:
        outputs = self.outputs
        llm_calls: list[str] = []
        remaining = list(self.tasks)
        while remaining:
            if self.process == "hierarchical":
                llm_calls.append("Manager:pick")
                ready = [t for t in remaining if all(c in outputs for c in t.context)]
                task = ready[0]
                print(f"    manager picks {task.agent.role} for {task.name}")
            else:
                task = remaining[0]
            outputs[task.name] = execute(task, outputs, self.memory, topic, llm_calls)
            self.memory.short_term.append(f"{task.name} done")
            remaining.remove(task)
        if self.process == "hierarchical":
            llm_calls.append("Manager:finish")
        self.memory.long_term[topic] = f"{json.loads(outputs['edit'])['points']} points last time"
        self.memory.short_term.clear()
        return outputs["edit"], llm_calls


class Flow:
    def __init__(self) -> None:
        self.listeners: dict[str, list[Callable[[Any], Any]]] = {}
        self.start_method: Callable[[], Any] | None = None
        self.trace: list[str] = []
        self.state: dict[str, Any] = {}

    def start(self, fn: Callable[[], Any]) -> Callable[[], Any]:
        self.start_method = fn
        return fn

    def listen(self, event: str) -> Callable[[Callable[[Any], Any]], Callable[[Any], Any]]:
        def register(fn: Callable[[Any], Any]) -> Callable[[Any], Any]:
            self.listeners.setdefault(event, []).append(fn)
            return fn
        return register

    def kickoff(self) -> Any:
        assert self.start_method is not None
        event, payload = "start", self.start_method()
        while True:
            self.trace.append(event)
            handlers = self.listeners.get(event, [])
            if not handlers:
                return payload
            event, payload = handlers[0](payload)


def build_flow(topic: str, memory: Memory) -> Flow:
    flow = Flow()

    @flow.start
    def load_request() -> Any:
        flow.state["topic"] = topic
        return topic

    @flow.listen("start")
    def run_crew(t: str) -> Any:
        brief, calls = Crew(make_tasks(), memory=memory).kickoff(t)
        flow.state["llm_calls"] = len(calls)
        return "crew_done", json.loads(brief)

    @flow.listen("crew_done")
    def route(brief: dict[str, Any]) -> Any:
        return ("publish" if brief["points"] >= 3 else "needs_human"), brief

    @flow.listen("publish")
    def publish(brief: dict[str, Any]) -> Any:
        return "published", f"published '{brief['title']}' with {brief['points']} points"

    return flow


def main() -> None:
    topic = "agent runtimes"
    print("1. sequential crew: outputs flow forward as context, guardrails force a retry")
    brief, calls = Crew(make_tasks()).kickoff(topic)
    print(f"    llm calls={len(calls)} {calls}")
    print(f"    brief={brief[:90]}...")

    print("\n2. hierarchical crew: a manager call before every task")
    _, h_calls = Crew(make_tasks(), process="hierarchical").kickoff(topic)
    print(f"    llm calls={len(h_calls)} (manager calls={sum(c.startswith('Manager') for c in h_calls)})")

    print("\n3. flow wraps the crew: code owns the route, the crew owns the prose")
    shared_memory = Memory()
    flow = build_flow(topic, shared_memory)
    print(f"    result={flow.kickoff()}")
    print(f"    events={flow.trace} state={flow.state}")

    print("\n4. long-term memory survives into the second kickoff")
    second_crew = Crew(make_tasks(), memory=shared_memory)
    second_crew.kickoff(topic)
    print(f"    long_term={shared_memory.long_term}")
    print(f"    research output tail: ...{second_crew.outputs['research'][-30:]}")

    print("\n5. prompt overhead per call from personas")
    for agent in (researcher, writer, editor):
        print(f"    {agent.role:<10} persona chars={agent.prompt_size()}")
    print(f"    tool calls={len(CALLS)}")

    print("\ncrews explore, flows decide; guardrails turn expected_output into a contract.")


if __name__ == "__main__":
    main()
