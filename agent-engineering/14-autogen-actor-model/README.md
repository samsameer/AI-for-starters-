# 14 · The Actor Model for Agents: Microsoft Agent Framework (formerly AutoGen)

> **Short answer:** Treat each agent as an actor: private state, an inbox, and typed handlers. Agents never call each other; they send messages, and a runtime delivers them. That gives you fault isolation, natural concurrency and a path to distribution. AutoGen v0.4 popularized this design; in 2026 it lives on in **Microsoft Agent Framework 1.x**, which absorbed AutoGen and Semantic Kernel. Use it when many agents work concurrently and one failing must not take down the rest.

**Type:** Learn + Build · **Languages:** Python (stdlib) · **Time:** ~75 min

---

## 1. The problem

The simplest multi-agent code is a call stack: agent A calls agent B, waits, then calls agent C. It is easy to read and fragile in production.

- If B raises, A's stack unwinds and the whole run is lost.
- Running B and C at the same time needs threads or async bolted on after the fact.
- Moving C to another machine means rewriting every call site.

The actor model removes the call stack between agents. Each agent only reacts to messages in its inbox, and the runtime decides when and where those messages are delivered.

## 2. The concept

### Actors

```
          ┌──────── runtime ────────┐
 publish  │  topic "review"         │
 ───────► │   ├─► style    [inbox]  │──Finding──┐
          │   ├─► security [inbox]  │──Finding──┤
          │   └─► tests    [inbox]  │──Finding──┤
          │                         │           ▼
          │              aggregator [inbox] ──► Verdict (workflow output)
          │  dead letters: unknown recipient, no handler, retries exhausted
          └─────────────────────────┘
```

An actor has three things: private state nobody else touches, an inbox, and handlers keyed by message type. A handler can update state, send messages, publish to a topic or emit an output. Two actors never share memory.

### Why decoupling delivery from handling matters

| Property | Call-stack agents | Actors |
|---|---|---|
| A failure in one agent | Unwinds the caller | Caught by the runtime: retry, dead-letter or restart |
| Concurrency | Added later | Many messages in flight by default |
| Distribution | Rewrite | Swap the transport, keep the handlers |
| Observability | Stack traces | One span per message, easy to correlate |

### Supersteps: deterministic actors

Pure actor systems deliver messages whenever they like, which makes runs hard to reproduce. Microsoft Agent Framework's workflows use a **superstep** model (the Pregel / bulk-synchronous-parallel idea): every message sent during step N is delivered together in step N+1. That adds a natural checkpoint boundary between steps, so a workflow can be paused, saved and resumed exactly.

### Team patterns

| Pattern | Who speaks next | Fits |
|---|---|---|
| Round robin | Fixed rotation | Simple review loops |
| Selector / group chat manager | A function or model picks based on the transcript | Teams where order depends on content |
| Handoff | The current agent transfers control | Triage and escalation |
| Magentic orchestration | A lead agent plans, tracks progress, reassigns | Open-ended research, web and code tasks |
| Concurrent | All agents get the same input, results are merged | Fan-out checks and voting |

### Where it goes wrong

- **Message storms.** A selector that keeps picking the same two agents loops forever. Always cap turns and supersteps.
- **Hidden shared state.** A "private" dict that two actors both reference breaks isolation and replay.
- **Silent dead letters.** If nobody watches the dead-letter queue, failures disappear.
- **Untyped payloads.** Free-text messages between agents drift. Typed messages make handler routing and validation possible.

## 3. What changed by Oct 2026

- **Microsoft Agent Framework 1.0 went GA around April 2026** for .NET and Python (Go in preview), and the Python core has moved on through many 1.x releases since. It is Microsoft's stated successor to both **AutoGen** and **Semantic Kernel**.
- **AutoGen is in maintenance mode.** Existing v0.4-era code keeps working, but new features land in Agent Framework. **AG2** is a separate community fork with its own roadmap; do not confuse the two.
- **The actor idea moved into typed workflows.** Agent Framework workflows are graphs of executors that handle typed messages, connected by edges, run in supersteps, with checkpointing and request/response pauses for human input. The orchestration patterns above (sequential, concurrent, handoff, group chat, Magentic) ship as prebuilt workflows.
- **Interop is protocol-based.** Agent Framework speaks MCP for tools (the stateless 2026-07-28 spec revision) and A2A v1.x for remote agents, so "distribution" often means "call an agent over A2A" rather than a custom transport.
- **Telemetry follows OTel GenAI conventions** (`invoke_agent`, `execute_tool` spans). These conventions now live in their own repo and are still marked Development, so pin versions (Lesson 23).
- **2026 update, System One speaker selection:** "who speaks next?" is a `choice` question over the agent names, and "is the team done?" is a `noul`. A decision model (Lessons 55–56) answers both in tens of milliseconds, replacing a full LLM call per turn in selector-style chats.

## 4. Build it

`code/main.py` contains a small actor runtime with supersteps:

- Typed messages: `ReviewRequest`, `Finding`, `Verdict`.
- `Executor` with `on(message_type, handler)` routing, plus `snapshot` and `restore` for checkpoints.
- `Runtime` with direct `send`, topic `publish`, superstep delivery in a stable order, retry once and then dead-letter, and a checkpoint after every superstep.
- Three checkers subscribe to the `review` topic. The `tests` checker times out on its first delivery. An `Aggregator` emits a `Verdict` once all three findings arrive.
- A small group-chat simulation comparing round robin with a content-aware selector.

```bash
python3 code/main.py
```

What to look for:

1. The flaky checker is retried in superstep 2 while the other actors continue; the message to a non-existent `deployer` lands in the dead-letter queue.
2. A risky diff produces a rejected verdict with reasons from two checkers.
3. A checkpoint taken after superstep 1 is restored into a fresh runtime and finishes with the same verdict.
4. The selector reaches `APPROVED` in fewer turns than round robin, because it sends the critic's "REVISE" straight back to the coder.

## 5. Use it in production

- **Microsoft Agent Framework (Python or .NET):** agents for single LLM loops; workflows with executors, edges and checkpoints for multi-step and multi-agent processes; prebuilt orchestrations for group chat, handoff and Magentic patterns.
- **Migrating from AutoGen:** map `AssistantAgent` to an Agent Framework agent, AgentChat teams to the matching orchestration, and Core actors to workflow executors. Keep message types; they port cleanly.
- **Hosting:** Azure AI Foundry's agent service runs Agent Framework agents, but nothing ties the framework to Azure.
- **Other actor-style options:** LangGraph swarm (Lesson 13), a custom runtime over NATS or Kafka when you need a specific transport, or a durable engine such as Temporal for long-lived workflows.

## 6. Architect's lens

1. **Pick the delivery semantics on purpose.** At-least-once delivery plus idempotent handlers is the realistic target. Exactly-once is a property of your handlers, not of the broker.
2. **Supersteps trade latency for reproducibility.** A fast executor waits for the slowest one in the same step. That is worth it when you need checkpoints and replay; it is not worth it for a chat UI that wants the first token fast.
3. **Watch the dead-letter queue like an error budget.** Alert on its growth rate and sample it weekly. Each new dead-letter cause is a missing handler, schema or retry rule.
4. **Bound every team.** Max turns, max supersteps and a cost ceiling per run. Multi-agent chats fail by looping, not by crashing.
5. **Type the messages, not just the tools.** Typed inter-agent messages are what make routing, validation, replay and A2A exposure possible later.

## 7. Exercises

1. Add a supervisor that restarts an executor with fresh state after two consecutive failures. What state is lost, and is that acceptable?
2. Make the aggregator time out: if a finding has not arrived within three supersteps, emit a verdict marked `incomplete`.
3. Replace the in-process `pending` list with a JSON file per superstep so two processes can share the runtime.
4. Emit a span per delivered message with `gen_ai.operation.name` and `gen_ai.agent.name` (Lesson 23).
5. Replace `select_next_speaker` with Lesson 55's local decision-model stand-in and compare turn counts.

## 8. Key terms

| Term | Meaning |
|---|---|
| Actor / executor | Private state, an inbox and typed handlers |
| Message | A typed payload; the only way actors interact |
| Topic | A named route that delivers one message to every subscriber |
| Superstep | One round where all pending messages are delivered together |
| Dead-letter queue | Where undeliverable or repeatedly failing messages are parked |
| Selector | The component that picks the next speaker in a group chat |
| Magentic orchestration | A lead agent that plans, tracks progress and reassigns work |
| AG2 | A community fork of AutoGen, separate from Microsoft's framework |

## 9. Quick check

<details><summary>1. Why does one actor's exception not crash the others?</summary>Actors do not call each other. The runtime invokes each handler and catches the exception, then retries, dead-letters or restarts that actor while every other inbox keeps being served.</details>
<details><summary>2. What do supersteps buy you over free-running actors?</summary>A deterministic delivery order and a clean boundary between steps where state can be checkpointed and later restored exactly.</details>
<details><summary>3. A team on AutoGen asks what to do in 2026. What do you tell them?</summary>AutoGen is in maintenance. Keep the actor design and the typed messages, and plan a migration to Microsoft Agent Framework workflows and orchestrations. Do not confuse it with AG2, a separate community fork.</details>

## References

- Microsoft Agent Framework overview: https://learn.microsoft.com/en-us/agent-framework/overview/agent-framework-overview
- Microsoft Agent Framework repository: https://github.com/microsoft/agent-framework
- Migration guide from AutoGen: https://learn.microsoft.com/en-us/agent-framework/migration-guide/from-autogen/
- AutoGen v0.4 redesign (Microsoft Research, Jan 2025): https://www.microsoft.com/en-us/research/articles/autogen-v0-4-reimagining-the-foundation-of-agentic-ai-for-scale-extensibility-and-robustness/
- Fourney et al., Magentic-One (arXiv:2411.04468): https://arxiv.org/abs/2411.04468
- Malewicz et al., Pregel: A System for Large-Scale Graph Processing (SIGMOD 2010): https://dl.acm.org/doi/10.1145/1807167.1807184
- OpenTelemetry GenAI semantic conventions: https://opentelemetry.io/docs/specs/semconv/gen-ai/
