# 18 · Production Agent Runtimes: Agno and Mastra

> **Short answer:** A production runtime optimizes what prototyping frameworks ignore: cheap per-request agents, typed workflow boundaries and a backend you can deploy. **Agno** (Python) builds a fresh, lightweight agent per request and keeps sessions in a database, served through its FastAPI-based AgentOS. **Mastra** (TypeScript) gives you agents, Zod-typed tools and workflows with suspend and resume, on top of the Vercel AI SDK. Pick by language first, then by whether you need speed at high fan-in or typed workflows.

**Type:** Learn + Build · **Languages:** Python (stdlib) · **Time:** ~45 min

---

## 1. The problem

LangGraph, CrewAI and Microsoft Agent Framework give you a lot of framework. Some teams want less: "an agent loop, tools, memory and a server, in the language my backend already uses, fast enough that it never shows up in a profile."

Two runtimes are the common answers in 2026: Agno for Python shops and Mastra for TypeScript shops. They are not trying to be LangGraph. They compete on fit with your stack and on operational ergonomics.

## 2. The concept

### Agno: stateless agents, stateful database

```
 request(session_id, message)
        │
   any worker ──► build Agent (microseconds) ──► load history from DB ──► run loop ──► stream events
        │                                                                    │
        └──────────────────────── append turn to DB ◄─────────────────────────┘
```

- Pure Python, no graph DSL. An `Agent` is a model, instructions, tools, and optional memory and knowledge.
- **Instantiation is cheap by design** (vendor-measured in microseconds and a few KiB per agent), so the recommended production shape is a **stateless, session-scoped API**: build the agent per request, keep all state in a database, scale workers horizontally.
- **AgentOS** is the runtime: a FastAPI app that serves agents, teams and workflows, with sessions, memory and knowledge stored in a database you own, and a control-plane UI.
- **Teams** (coordinate, route, collaborate modes) and **Workflows** (steps, conditions, loops, parallel) cover multi-agent work.
- Multimodal input and agentic RAG are built in.

### Mastra: typed primitives in TypeScript

```
 createWorkflow({ inputSchema, outputSchema })
   .then(classify)
   .branch([[amount <= 50, autoApprove], [amount > 50, humanApproval]])   ◄── suspend() here, resume(data) later
   .then(settle)
   .commit()
 every step: inputSchema ─► execute ─► outputSchema   (Zod-validated at each boundary)
```

- Three core primitives: **Agents**, **Tools** (Zod-typed input and output) and **Workflows** (`.then`, `.branch`, `.parallel`, loops, suspend and resume with stored snapshots).
- Built on the **Vercel AI SDK**; models are addressed with `provider/model` strings through a model router with fallbacks.
- Memory (working memory, semantic recall), RAG, evals, observability and storage adapters, with different backends per concern.
- Server adapters for common Node frameworks and first-class Next.js integration. **Mastra Studio** is the local UI for running and inspecting agents and workflows.
- Licensing: the core is Apache-2.0, while `ee/` directories are under a source-available enterprise license. Read both before forking.

### Choosing

| Situation | Lean toward |
|---|---|
| Python backend, FastAPI, many short-lived agents | Agno |
| TypeScript backend, Next.js, Vercel deploy | Mastra |
| Typed multi-step workflows with human pauses | Mastra workflows, or LangGraph (Lesson 13) |
| Durable state and explicit graph reasoning above all | LangGraph |
| Provider-native features first | A provider agent SDK (Lessons 16–17) |

### Where it goes wrong

- **Performance for its own sake.** Microsecond instantiation does not matter when every request waits a second for the model. It matters for high fan-in: evaluation pipelines, thousands of small agents per second.
- **Ecosystem pull.** Mastra fits best on the Vercel and Node stack; elsewhere you carry more integration work.
- **State in the wrong place.** A "stateless" agent that caches a session in process memory breaks as soon as the next request lands on a different worker.
- **License surprises.** Source-available directories are not open source.

## 3. What changed by Oct 2026

- **Agno is on a 3.x major line** (3.1.x in October; 2.x shipped earlier in the year). AgentOS is the documented production path. Check the migration notes; imports and storage classes changed between majors.
- **Mastra is well past 1.0** (core 1.76.x, with 1.77 in alpha). Any "pre-1.0" warning you read is stale. Expect frequent minor releases and check changelogs for workflow API details.
- **The Vercel AI SDK under Mastra is now v7:** ESM-only, `stopWhen: isStepCount(n)` (renamed from `stepCountIs`), stable telemetry in `@ai-sdk/otel`, system messages inside `messages` rejected by default, and a durable `WorkflowAgent`.
- **Model ids moved.** Current examples use the GPT-6 family (GPT-6.1 Sol, GPT-6 Luna) and `gemini-3.8-flash`; update hard-coded model strings, and keep a fallback list in the router.
- **MCP is stateless** (spec 2026-07-28), and both runtimes consume and expose MCP tools. Agent-to-agent calls increasingly use A2A v1.x.
- **Observability converged on OTel GenAI spans,** which both runtimes can export to Langfuse, LangSmith, Phoenix or Braintrust (Lessons 23–24).
- **2026 update, System One branches:** a workflow `.branch()` condition or an Agno team's routing decision is a `choice` question. A decision model (Jev or Clef, Lessons 55–56) can answer it in tens of milliseconds with probabilities, keeping the branch logic in code while the classification comes from a model.

## 4. Build it

`code/main.py` implements both shapes in stdlib Python:

- **Python runtime shape:** `SessionDb` (in-memory `sqlite3`), a `PyAgent` that streams `tool_call`, `delta` and `completed` events, and a `stateless_endpoint` factory. Two different "workers" serve two requests in the same session and still share history through the database. A micro-benchmark builds 10,000 agent objects and checks that each costs under a millisecond.
- **TypeScript runtime shape:** `Step` with input and output schemas, a `Workflow` with `then`, `branch`, suspend and `resume`, and schema checks at every step boundary.
- `route_model`, a `provider/model` router with fallbacks.

```bash
python3 code/main.py
```

What to look for: `worker-b` answers a follow-up using the history `worker-a` wrote; the small refund auto-approves while the large one suspends with a snapshot and finishes after `resume`; a step that returns a number where a string is required is rejected at the boundary; and the router falls back to Gemini when OpenAI is marked unhealthy.

## 5. Use it in production

```python
from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.os import AgentOS

support = Agent(
    name="support",
    model="openai:gpt-6-luna",
    db=PostgresDb(db_url="postgresql+psycopg://app@db/agents"),
    add_history_to_context=True,
)
app = AgentOS(agents=[support]).get_app()
```

```typescript
import { createWorkflow, createStep } from "@mastra/core/workflows";
import { z } from "zod";

const classify = createStep({
  id: "classify",
  inputSchema: z.object({ text: z.string() }),
  outputSchema: z.object({ amount: z.number() }),
  execute: async ({ inputData }) => ({ amount: Number(inputData.text.match(/\d+/)?.[0] ?? 0) }),
});

export const refunds = createWorkflow({
  id: "refunds",
  inputSchema: z.object({ text: z.string() }),
  outputSchema: z.object({ amount: z.number() }),
}).then(classify).commit();
```

Class names and options move between releases in both projects, so treat these as shapes and confirm against the current docs.

## 6. Architect's lens

1. **Profile before choosing on speed.** Measure where a request spends its time. If the model is 95% of latency, framework overhead is noise; pick on ergonomics and team skills.
2. **Stateless workers, stateful stores.** Both runtimes scale best when every request can land on any worker. Put sessions, memory and workflow snapshots in a shared database and test failover.
3. **Typed boundaries are your contract tests.** Zod or Pydantic schemas at every step catch model drift as a validation error instead of a wrong refund.
4. **Suspend and resume needs an owner.** A suspended workflow is a pending business decision. Track the count and age of suspended runs and give them an expiry.
5. **Know your exit cost.** Keep tools behind MCP or plain functions and models behind a router, so moving between Agno, Mastra and a provider SDK is a port, not a rewrite.

## 7. Exercises

1. Add a third worker and send five interleaved requests across two sessions. Verify each session's history stays separate.
2. Add a `parallel` construct to the workflow that runs `fraud_check` and `credit_check` together and merges their outputs.
3. Make `resume` reject data that does not match the suspended step's schema.
4. Time your real agent call end to end, then compute what share is framework overhead. Does it change your choice?
5. Replace the branch condition with a `choice` question to Lesson 55's local stand-in and route on its top label and confidence.

## 8. Key terms

| Term | Meaning |
|---|---|
| Agno | Python agent runtime built for cheap, per-request agents |
| AgentOS | Agno's FastAPI-based runtime and control plane |
| Mastra | TypeScript agent framework built on the Vercel AI SDK |
| Workflow step | A unit with typed input, typed output and an execute function |
| Suspend / resume | Pausing a workflow with a stored snapshot and continuing later with new data |
| Model router | Resolves `provider/model` strings and falls back across providers |
| Mastra Studio | Local UI for running and inspecting agents and workflows |
| Source-available | Code you can read but not freely reuse commercially |

## 9. Quick check

<details><summary>1. Why is Agno's recommended backend stateless?</summary>Agents are cheap to build, so each request creates one and loads history from the database. Any worker can serve any request, which makes horizontal scaling and failover simple.</details>
<details><summary>2. What does Mastra validate at every workflow step?</summary>The step's input and output against their Zod schemas, so a malformed value fails at the boundary instead of propagating.</details>
<details><summary>3. When does microsecond agent instantiation actually matter?</summary>When you create very many short-lived agents, such as evaluation sweeps or high fan-in APIs. It does not matter when one slow model call dominates each request.</details>

## References

- Agno documentation: https://docs.agno.com/
- Agno repository: https://github.com/agno-agi/agno
- Mastra documentation: https://mastra.ai/docs
- Mastra repository and changelog: https://github.com/mastra-ai/mastra
- Vercel AI SDK: https://ai-sdk.dev/docs
- LangGraph overview: https://docs.langchain.com/oss/python/langgraph/overview
