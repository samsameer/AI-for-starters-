# 15 · Role-Based Agent Teams: Crews and Flows

> **Short answer:** A role-based team describes each agent as a role, a goal and a backstory, gives each piece of work a task with an `expected_output` contract, and lets a process decide the order. CrewAI is the reference framework and splits the world in two: **Crews** for autonomous, exploratory collaboration and **Flows** for event-driven, code-owned control. Ship Flows to production and call Crews from inside them where open-ended judgment is worth paying for.

**Type:** Learn + Build · **Languages:** Python (stdlib) · **Time:** ~75 min

---

## 1. The problem

"Autonomous agents collaborating" demos well. Then production asks hard questions:

- A customer reports a bad answer. Can you replay the run?
- Finance asks what one run costs. Is it four model calls or nine?
- On-call is paged at 3 a.m. Which agent stalled, and on what input?

A free-form crew where a model decides who works next answers none of these cleanly. A rigid pipeline answers all of them but loses the exploratory step that made the demo good. Role-based frameworks are useful because they let you choose per surface, not because roles are magic.

## 2. The concept

### Four primitives

| Primitive | Owns | Key fields |
|---|---|---|
| Agent | A persona and its tools | `role`, `goal`, `backstory`, `tools`, `llm` |
| Task | One unit of work and its contract | `description`, `expected_output`, `agent`, `context`, `output_pydantic`, `guardrail` |
| Crew | The team | `agents`, `tasks`, `process`, `memory` |
| Process | Who goes next | sequential or hierarchical |

Agents never address each other. Tasks name agents, `context` names upstream tasks, and the process picks the next task.

### Sequential vs hierarchical

```
Sequential:    research ──► draft ──► edit                 3 specialist calls

Hierarchical:  manager ─► research ─► manager ─► draft ─► manager ─► edit ─► manager
               every hop adds one manager call carrying the task list and prior outputs
```

Sequential is cheapest and most predictable; use it whenever the order is known. Hierarchical earns its extra calls only when the next step genuinely depends on earlier output and you have several specialists to choose from. Treat any third "consensus" style process as unavailable unless the current docs show it.

### Crews vs Flows

```
Flow (code owns control)
  @start load_request ──► @listen run_crew ──► @router quality_gate ──┬─► publish
                              │                                      └─► needs_human
                              ▼
                      Crew.kickoff()  (model owns the prose)
```

A **Flow** is plain Python: `@start` marks the entry, `@listen(step)` runs a method when another one finishes, `@router` returns a label that picks the branch, and typed state persists across steps. A **Crew** is the autonomous part. Compose them: the Flow is your audit boundary and the Crew is a step inside it.

### Contracts: `expected_output`, structured output and guardrails

- `expected_output` is the human-readable contract, and the model sees it.
- `output_pydantic` (or `output_json`) makes the contract machine-checkable for downstream steps.
- A task `guardrail` is a function that returns `(ok, result_or_feedback)`. On failure, the feedback goes back to the agent and the task retries, up to a limit.

These three settings fix the most common crew failure: task N returns "an outline" with four sections when task N+1 expected three.

### Tools and memory

Tools are plain functions with the `@tool` decorator, or `BaseTool` subclasses when they need arguments schemas, clients or caching. Memory covers within-run context, cross-run recall and per-entity facts. Recent releases put these behind a unified memory interface, so check the current docs for the class names.

### Where it goes wrong

- **Backstory bloat.** Every persona is resent on every call. Five 2,000-word backstories eat the context before any work happens.
- **Manager tax.** Hierarchical adds a call per hop, and each one carries the growing transcript.
- **Brittle handoffs.** Free-text outputs between tasks drift. Use structured output and guardrails.
- **Side effects inside a Crew.** A crew may call a tool more often than you expect. Payments, deletes and emails belong in Flow steps, not crew tools.

## 3. What changed by Oct 2026

- **CrewAI is on the 1.x line** (1.15.x in October 2026). Lessons written against 0.8x versions are out of date on imports, memory classes and Flow features.
- **Flows are the documented production path.** The docs lead with "start with a Flow" and treat Crews as steps inside one. Flow state persistence and routing (`@router`, `and_`, `or_`) are now the core of the framework.
- **Task guardrails are standard practice.** Function guardrails (and model-checked ones) with retry limits replace "hope the next agent copes".
- **Memory was consolidated** behind one memory system instead of four separately configured stores. The concepts (short-term, long-term, entity) still apply.
- **The ecosystem moved underneath.** MCP tools now target the stateless 2026-07-28 spec, frontier models reject assistant prefill and some reject forced tool choice, so structured outputs are the way to enforce `output_pydantic`-style contracts.
- **2026 update, System One gates:** the hierarchical manager's "which specialist next?" is a `choice` question, and a quality gate such as "does this brief meet the rubric?" is a `score`. A decision model (Lessons 55–56) can make both calls in tens of milliseconds and return probabilities your Flow's `@router` can threshold.

## 4. Build it

`code/main.py` implements both shapes with a fake model:

- `Agent`, `Task` and `Memory` dataclasses mirroring CrewAI's surface.
- A `@tool` registry and a `search_notes` tool.
- `Crew.kickoff` with sequential and hierarchical processes. The hierarchical version adds a manager call before every task and one to finish.
- Task guardrails: the writer's first draft has no bullets and is rejected, so the retry produces three. The editor's output must be JSON with `title`, `points` and `body`.
- A tiny `Flow` with `start` and `listen`, which runs the crew as one step and routes on the result in code.
- Long-term memory that the researcher reads on the second kickoff.

```bash
python3 code/main.py
```

What to look for: 4 model calls for the sequential crew against 8 for the hierarchical one on the same work; the guardrail rejection and retry; the Flow's fixed event trace `start → crew_done → publish → published`; and `PRIOR: 3 points last time` in the second run's research output.

## 5. Use it in production

```python
from crewai import Agent, Task, Crew, Process
from crewai.flow.flow import Flow, start, listen, router

def has_three_bullets(result):
    lines = [l for l in result.raw.splitlines() if l.startswith("- ")]
    return (len(lines) >= 3, result.raw if len(lines) >= 3 else "Need at least 3 bullets")

writer = Agent(role="Writer", goal="Draft a brief", backstory="Plain-spoken technical writer.")
draft = Task(description="Draft bullets on {topic}", expected_output="3+ bullet lines",
             agent=writer, guardrail=has_three_bullets)

class BriefFlow(Flow):
    @start()
    def run_crew(self):
        return Crew(agents=[writer], tasks=[draft], process=Process.sequential).kickoff(
            inputs={"topic": "agent runtimes"})

    @router(run_crew)
    def gate(self, result):
        return "publish" if result.raw.count("- ") >= 3 else "needs_human"
```

- **Flow outside, Crew inside** for anything user-facing.
- **Sequential crews** for drafting and review chains; **hierarchical** only with several specialists and output-dependent routing.
- **Observability:** CrewAI emits events you can send to Langfuse, LangSmith, Phoenix or any OTel backend (Lesson 24).
- **Alternatives:** LangGraph for explicit state machines (Lesson 13), Microsoft Agent Framework for typed workflows and group chat (Lesson 14), a provider agent SDK for handoff-centric apps (Lessons 16–17).

## 6. Architect's lens

1. **Count calls per run before you choose a process.** Sequential is N calls. Hierarchical is roughly 2N+1, with a growing prompt each time. Put the number in the design doc.
2. **Freeze personas like code.** Backstories change output quality and tone. Version them, test a few variants against an eval set, then lock one.
3. **The Flow is the unit of SLOs.** Latency, cost and success rate are measured per Flow run, with the Crew as one span inside it.
4. **Contracts at every boundary.** Each task's output is the next task's input. Structured output plus a guardrail is cheaper than a debugging session.
5. **Scope memory writes.** Writing everything to long-term memory makes retrieval noisy within weeks. Write only facts that should outlive the run.

## 7. Exercises

1. Make the hierarchical manager refuse to schedule `edit` until `draft` has at least three bullets. Trace the extra calls.
2. Add entity memory keyed by customer, and verify the second kickoff for the same customer retrieves it.
3. Add a `needs_human` branch to the Flow and send a two-bullet brief through it.
4. Replace the editor's guardrail with a 0–4 rubric `score` from Lesson 55's stand-in and route on the expected score.
5. Port the toy to the real `crewai` package. Which guarantees did the stdlib version skip?

## 8. Key terms

| Term | Meaning |
|---|---|
| Agent | Role, goal, backstory and tools |
| Task | Description, `expected_output`, assignee and optional structured output |
| Crew | A container of agents and tasks with a process |
| Process | Strategy for picking the next task: sequential or hierarchical |
| Flow | Event-driven, code-owned workflow with typed state |
| Router | A Flow step that returns a label choosing the next branch |
| Task guardrail | A check on a task's output that triggers a retry with feedback |
| Manager LLM | The extra model call in a hierarchical process that picks the next task |

## 9. Quick check

<details><summary>1. Why does the docs' production advice start with a Flow?</summary>A Flow gives deterministic control, typed state, replayable traces and a place for side effects. A Crew is variable by design, so it belongs inside a Flow step where its output can be checked.</details>
<details><summary>2. What does hierarchical cost on a five-task crew?</summary>A manager call before each task plus a final one: about six extra calls, each carrying the task list and prior outputs, on top of the five specialist calls.</details>
<details><summary>3. Task 2 keeps misreading Task 1's output. What is the fix?</summary>Give Task 1 a structured output model and a guardrail, so Task 2 receives a validated object instead of free text.</details>

## References

- CrewAI documentation: https://docs.crewai.com/
- CrewAI Flows: https://docs.crewai.com/en/concepts/flows
- CrewAI tasks and guardrails: https://docs.crewai.com/en/concepts/tasks
- CrewAI memory: https://docs.crewai.com/en/concepts/memory
- CrewAI repository and releases: https://github.com/crewAIInc/crewAI
- LangGraph overview: https://docs.langchain.com/oss/python/langgraph/overview
