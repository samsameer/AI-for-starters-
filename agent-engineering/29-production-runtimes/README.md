# 29 · Production Runtimes: Queue, Event, Cron, Durable

> **Short answer:** The same agent logic can run inside six outer shells: **request-response, streaming, durable execution, queue/background, event-driven, and scheduled**. The shell decides which failures you survive: a timeout at step 37, a worker reboot, an approval that takes two days. Pick the shell from the task's duration, trigger and approval needs before you pick a framework. In Oct 2026 the hosted options are Cloudflare Agents + Sandboxes, Temporal with the OpenAI Agents SDK, Vercel Workflow, AWS Bedrock AgentCore and other hosted agent platforms. You need traces in every one of them.

**Type:** Learn + Build · **Languages:** Python (stdlib) · **Time:** ~60 min

---

## 1. The problem

A notebook agent never sees the failures production sees:

- the network drops at step 37 of 60;
- a user closes the tab during a 4-minute run;
- a node reboots in the middle of a cron job;
- a worker runs out of memory;
- a refund waits two days for a manager's approval.

A runtime "shape" is the set of guarantees around your loop: what happens on a crash, who waits, and where the result goes. If you get the shape wrong, retries compound, users hang, and failed jobs disappear without a trace.

## 2. The concept

```
               trigger                    execution                  result
 user ──► request-response ──► loop ──► reply             (≤ a few s)
 user ──► streaming        ──► loop ──► deltas ─► reply    (seconds, visible progress)
 user ──► durable workflow ──► step₁ ✓ step₂ ✓ ⚡crash ⟲ step₃ … (minutes → days)
 api  ──► queue ─► worker pool ─► result / webhook   └─► DLQ after N attempts
 event (PR, email, webhook) ──► handler(s) ──► loop
 cron ("30 3 * * *") ──► loop (+ durable, so a failed night resumes)
```

| Shape | Survives | Key metrics | Typical stack (Oct 2026) |
|---|---|---|---|
| Request-response | Nothing beyond the request | p50/p95 latency, error rate | FastAPI/Agno, Hono/Mastra, Workers |
| Streaming | Slow output (with good UX) | Time to first token, tail latency | SSE/WebSocket, AI SDK UI, WebRTC for voice |
| Durable execution | Crashes, deploys, long waits | Replays, step retries, resume time | Temporal, Vercel Workflow, LangGraph checkpoints, Restate, Cloudflare Agents |
| Queue/background | Load spikes, flaky deps | Queue depth, job latency, **DLQ size** | SQS, BullMQ, Celery, Cloudflare Queues |
| Event-driven | Bursty triggers | Event-to-start latency, drop rate | Webhooks, coding-agent routines (GitHub events), hosted agent platforms |
| Scheduled | Nothing alone; pair with durable | Missed runs, run duration | Cron + durable workflow, Routines, Managed Agents scheduled deployments |

**Durable execution** is the shape agents need most. Every step's result is written to a journal before the next step runs. After a crash the runtime replays the journal, so finished steps (and their side effects) are not repeated. This is what makes "wait 3 days for approval" a normal line of code.

## 3. What changed by Oct 2026

- **Cloudflare Agents Week (Apr 2026).** Sandboxes went GA: persistent isolated Linux sandboxes with a zero-trust egress proxy. **Code Mode** (`@cloudflare/codemode` on Dynamic Workers) lets the model write code against your tools instead of making many separate tool calls. **Project Think** is the next-gen durable agent SDK. The `agents` package (0.28.0) has experimental harnesses, including `ContainerHarness`, which runs coding agents such as Codex inside Containers. It also has `withX402` payments and MCP SDK v2.
- **Temporal + OpenAI Agents SDK** integration went GA on 2026-03-23. Model and tool calls become Temporal activities with automatic retries and replay. The OpenAI Agents SDK also added resumable `RunState`, retry policies and container-backed **Sandbox agents**.
- **Vercel Workflow GA** (TS + Python; `workflow` 5.2.x). AI SDK v7's `WorkflowAgent` turns each tool call into a `"use step"`, so approvals can last hours or days.
- **AWS Bedrock AgentCore** (GA Oct 2025) added a new runtime with consistent cold starts, interactive shell sessions (up to 10 per runtime session), a durable filesystem for suspend/resume, Memory `IngestData`, failure insights and an optimization preview.
- **Hosted agent platforms** offer a hosted harness plus sandbox with environments, sessions, vaults and **scheduled deployments**. Coding-agent **routines** run cloud agents on a schedule, on GitHub events or from an API call.
- **Sandboxes everywhere:** LangSmith Sandboxes are GA, alongside OpenAI Sandbox agents and AgentCore shells. Inngest AgentKit has had no release since Nov 2025, so check that it is maintained before you adopt it.
- **Observability:** OTel GenAI conventions are still at *Development* status and moved to `open-telemetry/semantic-conventions-genai`. MCP now carries `traceparent` in `_meta`, so traces cross tool-server boundaries.

## 4. Build it

`code/main.py` wraps one five-step agent in all six shells:

1. `request_response`: a step budget rejects work that is too long to run synchronously.
2. `streaming`: a generator yields JSON deltas with sequence numbers.
3. `durable_run`: a journal keyed by `run_id/step`. The demo crashes at `read`, resumes, and shows that every side effect ran **exactly once**.
4. `QueueRuntime`: retry with exponential backoff, DLQ after 3 attempts, and **idempotency keys**, so a duplicate submission returns the cached result.
5. `EventBus`: fan-out to several handlers, plus a visible "no subscriber" so events are never dropped silently.
6. `fire_schedule`: a minimal cron matcher.

The script ends with `pick_shape`, a small decision table that maps duration, trigger and approval needs to a shape.

```bash
python3 code/main.py
```

## 5. Use it in production

| You need | Reach for |
|---|---|
| Edge-native agents with per-agent state, plus code execution | Cloudflare Agents SDK + Sandboxes, Code Mode for many-tool workflows |
| Bulletproof multi-day workflows in Python/TS/Go | Temporal (Python SDK 1.34) + OpenAI Agents SDK integration |
| Durable agents inside a Next.js / AI SDK app | Vercel Workflow + `WorkflowAgent` |
| AWS-native, managed runtime + memory + shells | Bedrock AgentCore |
| Hosted harness with schedules and outcomes | A hosted agent platform |
| Journaled steps over your own infra | Restate (`ctx.run`), LangGraph checkpointers |

## 6. Architect's lens

1. **Duration and approvals pick the shape.** Under ~3 s, use request-response. Under ~30 s with a user watching, stream. Anything longer, or anything that waits on a human, needs durable execution. Once you have a durable engine, queues and cron are just triggers into it.
2. **Make every side effect idempotent.** Retries are guaranteed in every shape except request-response. Key each external action (email, charge, PR comment) by `run_id/step` or a caller-supplied idempotency key.
3. **Treat the DLQ as a product surface.** Alert on DLQ growth, not on single failures. Every DLQ item should be replayable after the fix and should become an eval case (Lesson 30).
4. **Durable replay requires determinism.** Workflow code that branches on wall-clock time, randomness or a fresh LLM sample will diverge on replay. Put non-determinism inside steps or activities, whose results are journaled.
5. **Choose where the sandbox lives.** Running code next to the agent (Cloudflare Sandboxes, AgentCore shells) cuts latency but widens the blast radius. Pair it with an egress allowlist (Lesson 36). **2026 update:** a System One `noul` guard, "is this action within the task's scope?", can run in tens of ms before each tool call in the durable step (Lessons 55–56).

## 7. Exercises

1. Move the crash point in `durable_run` to `answer`. Confirm that the earlier side effects are not repeated.
2. Add jitter to the queue backoff and a `max_age` after which jobs go straight to the DLQ.
3. Add an `approval.granted` event that resumes a durable run parked at a `wait_for_approval` step.
4. Extend `cron_matches` to support `*/15` and day-of-week, and test it at the midnight boundary.
5. Pick one of your agents and fill in the shape table: duration, trigger, approvals, chosen stack, and the three metrics you would alert on.

## 8. Key terms

| Term | Meaning |
|---|---|
| Durable execution | Steps are journaled so a crashed run resumes without repeating finished steps |
| Journal | The ordered record of step results used for replay |
| Idempotency key | A caller-chosen ID that makes repeated submissions safe |
| DLQ | Dead-letter queue: where jobs go after exhausting retries |
| Routine | A coding-agent cloud run fired by a schedule, GitHub event or API call |
| Code Mode | The model writes a program against tools instead of calling them one by one |

## 9. Quick check

<details><summary>1. A refund agent must wait for manager approval that may take 48 hours. Which shape?</summary>Durable execution (Temporal, Vercel Workflow, Cloudflare Agents, Managed Agents). The run parks at the approval step and resumes later without re-running earlier steps.</details>
<details><summary>2. Why did <code>j3</code> not run in the demo?</summary>It carried the same idempotency key as <code>j1</code>, so the worker returned the cached result instead of doing the work twice.</details>
<details><summary>3. Why should a nightly cron job be durable?</summary>If it fails halfway, the next tick or a retry resumes from the last finished step instead of redoing everything, and nothing is silently lost.</details>

## References

- Cloudflare Agents Week recap: https://blog.cloudflare.com/agents-week-in-review/ · agents changelog: https://raw.githubusercontent.com/cloudflare/agents/main/packages/agents/CHANGELOG.md
- Temporal × OpenAI Agents SDK: https://temporal.io/blog/announcing-openai-agents-sdk-integration
- Vercel WorkflowAgent: https://vercel.com/kb/guide/what-is-workflowagent
- AWS Bedrock AgentCore release notes: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/release-notes.html
- LangGraph persistence: https://docs.langchain.com/oss/python/langgraph/overview
