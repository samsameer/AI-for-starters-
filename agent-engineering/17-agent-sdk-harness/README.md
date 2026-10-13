# 17 · Agent SDKs: The Harness as a Library

> **Short answer:** A provider API gives you one model round-trip. An **agent SDK** gives you the harness around it: the tool loop, built-in tools, permissions, lifecycle hooks, subagents with isolated context, a session store, compaction and trace propagation. Agent = model + harness, and in 2026 the harness ships as a library you import (OpenAI Agents SDK, Google ADK, Microsoft Agent Framework, Vercel AI SDK, Pydantic AI) or as a hosted platform. Use an SDK when you would otherwise rebuild the same loop, hooks and session plumbing yourself.

**Type:** Learn + Build · **Languages:** Python (stdlib) · **Time:** ~75 min

---

## 1. The problem

Lesson 01 built an agent loop in forty lines. Production asks for much more:

- Tools that read and write files, run shell commands and fetch URLs, with a **permission** model.
- **Hooks** so security can veto a tool call and compliance can log every one.
- **Subagents** so a 20-module search does not flood the main context.
- **Sessions** that survive restarts, can be listed, forked and deleted.
- **Compaction** when the transcript outgrows the window.
- One **trace** across the orchestrator, its subagents and any subprocesses.

Every coding agent and hosted agent product has built this. Agent SDKs package that work so you can reuse it.

## 2. The concept

### Provider API vs agent SDK

| | Provider API (client SDK) | Agent SDK (harness) |
|---|---|---|
| Unit | One request/response | A run of many turns |
| Tool loop | You write it | Built in |
| Tools | Schemas you define | Built-ins plus yours plus MCP servers |
| State | Your problem | Session store |
| Policy | Your problem | Permission modes and hooks |
| Scale-out | Your problem | Subagents |

### The harness, piece by piece

```
 user prompt ──► [user_prompt_submit hook] ──► lead agent loop
                                                 │
        ┌──── tool call ─► [pre_tool_use hook] ─► permission policy: allow | ask | deny
        │                                         │
        │                                 run tool ─► [post_tool_use hook] ─► append to context
        │                                                                     │
        │                                       context > budget? ─► [pre_compact] ─► summary
        │
        └──── spawn subagents (parallel, isolated context, narrower permissions)
                 │ each returns a short summary only
                 ▼
          session store: append · load · list · fork_at · delete (cascades to subagent keys)
          trace: W3C traceparent passed to every child so the whole run is one trace
```

### Subagents: two reasons, one rule

1. **Parallelism:** independent subtasks run at the same time.
2. **Context isolation:** each subagent burns its own context reading files, and only a summary returns to the lead.

The rule: spawn a subagent when the work is big enough that its intermediate tokens would hurt the lead. Spawning one per tiny task just adds overhead.

### Hooks

The common lifecycle events, with slightly different names per SDK: session start and end, user prompt submit, before and after each tool call, before compaction, subagent stop and run stop. Hooks are deterministic code, which is why policy belongs in them and not in the prompt.

### Hosted harnesses

The same shape is also sold as a service: you send a task, the platform runs the loop in a managed sandbox with sessions, compaction and scheduling. Examples include Google's Gemini Enterprise Agent Platform (Agent Engine), AWS Bedrock AgentCore, LangSmith's managed Deep Agents and OpenAI's sandbox agents. You trade control and portability for less infrastructure.

### Where it goes wrong

- **Subagent over-spawn.** A hundred subagents for a hundred one-line tasks costs more than it saves. Batch.
- **Hook creep.** Every team adds a hook, startup slows and failures get hard to trace. Review hooks like code.
- **Session bloat.** Sessions pile up. Set retention, and make deletion cascade to subagent sessions.
- **Permission drift.** A subagent that inherits "allow everything" from its parent defeats the point of isolation.

## 3. What changed by Oct 2026

- **"Harness engineering" became a named discipline.** Teams now treat the harness (tools, permissions, context management, verification) as the main lever on agent quality, and benchmark papers ask authors to disclose the harness used.
- **Subagents went asynchronous.** Agent SDKs now run subagents in the background, stream their status as typed events and let the lead read a subagent's transcript later. Dynamic multi-agent workflows (a coordinator that spawns many agents from a plan) shipped in several coding agents and hosted platforms.
- **Sessions can fork.** Resuming "at an earlier entry" to branch a session is now standard, alongside list, load and cascading delete.
- **Transcripts are append-only.** Current frontier models preserve reasoning across turns and some reject assistant prefill, so harnesses append instead of editing history, and use server-side compaction or context editing to stay inside the window.
- **Skills and instruction files are cross-vendor.** `SKILL.md` folders with progressive disclosure, and AGENTS.md / agent instruction files, are read by most coding agents and several SDKs.
- **Permission modes grew an "auto" option**, where a classifier or decision model approves routine actions and escalates the rest, between "always ask" and "always allow".
- **MCP 2026-07-28 is stateless.** No initialize handshake and no session header; SDKs added MCP SDK 2.x support. Tools that relied on MCP sessions now pass server-minted handles.
- **SDK snapshot:** OpenAI Agents SDK 0.23 (Python), sandbox agents and resumable `RunState`; Google ADK 2.x (Python 2.11) with graph workflows, `abort_signal` cancellation and `ModelConsultTool`; Microsoft Agent Framework 1.x; Vercel AI SDK 7 with `ToolLoopAgent`, durable `WorkflowAgent`, `isStepCount` (renamed from `stepCountIs`) and telemetry in `@ai-sdk/otel`; Pydantic AI 1.x with a `DecisionModel` abstraction.
- **2026 update, System One permission gate:** the `pre_tool_use` question "should this action run?" is a `noul`. A decision model (Jev or Clef, Lessons 55–56) answers it in tens of milliseconds, so an "auto" permission mode can ask on every call; map the probability to allow, ask or deny in your own code.

## 4. Build it

`code/main.py` is a stdlib harness over a virtual filesystem:

- `ToolRegistry` with `list_dir`, `read_file`, `write_file` and `grep`.
- `PermissionPolicy` with allow, ask and deny sets plus recorded approvals.
- `Hooks` with `session_start`, `user_prompt_submit`, `pre_tool_use`, `post_tool_use`, `pre_compact`, `subagent_stop`, `stop` and `session_end`.
- `Harness`, which runs tool calls through hooks and policy, appends to context and compacts above a budget.
- `subagent_task`: three subagents run in parallel with **read-only** permissions and return one-line summaries.
- `SessionStore` with `append`, `load`, `list_sessions`, `list_subkeys`, `fork` and cascading `delete`.
- `traceparent`, which builds W3C trace-context headers so children share the parent's trace ID.

```bash
python3 code/main.py
```

What to look for: the lead's context stays near 50 characters with subagents against more than 1,100 doing the work inline; subagent writes are denied by their read-only policy; the lead's write is denied until approved, and a write outside the workspace is blocked by a hook; compaction keeps the lead under budget; a fork at entry 3; a cascading delete removing four keys; and the hook event counts.

## 5. Use it in production

| SDK | Shape | Notes for Oct 2026 |
|---|---|---|
| OpenAI Agents SDK (Py 0.23 / JS 0.20) | Agents, handoffs, guardrails, sessions | Sandbox agents, programmatic tool calling, Temporal integration |
| Google ADK 2.x | Agents plus graph workflows | Tool confirmation nodes, `ModelConsultTool`, SQLite memory, Agent Engine hosting |
| Microsoft Agent Framework 1.x | Agents plus typed workflows | Checkpoints, orchestrations, .NET and Python |
| Vercel AI SDK 7 | `ToolLoopAgent`, `WorkflowAgent` | ESM-only TypeScript, durable steps and approvals on Vercel Workflows |
| Pydantic AI 1.x | Typed agents and outputs | Decision-model backends with escalation to an LLM, durable execution integrations |

```python
from pydantic_ai import Agent

agent = Agent("openai:gpt-6.1-sol", instructions="Find modules without tests.")

@agent.tool_plain
def list_dir(path: str) -> list[str]:
    return sorted(p for p in WORKSPACE if p.startswith(path))

result = agent.run_sync("Which modules lack tests?")
```

Pick by language and by which of the harness pieces you need on day one. If you need a managed sandbox and scheduling more than control, evaluate the hosted platforms first.

## 6. Architect's lens

1. **Policy lives in code, not prompts.** Permission modes and `pre_tool_use` hooks are your enforcement layer. The system prompt is advice; the hook is law.
2. **Isolation is a security boundary as much as a context trick.** Give subagents the narrowest tools and permissions their task needs. A research subagent should not be able to write.
3. **Measure context, not just tokens.** Track lead-context size per run, compaction count and subagent fan-out. Rising compaction counts mean the task decomposition is wrong.
4. **Sessions are data with a lifecycle.** Define retention, deletion cascade and who may read a transcript. Transcripts contain user data and tool output.
5. **Keep the harness portable.** Wrap the SDK behind your own interfaces for tools, hooks and sessions, and use MCP for tools, so switching SDKs or models is a week, not a quarter.

## 7. Exercises

1. Batch 20 module checks into 4 subagents of 5. Compare the lead's context and total tool calls with 20 subagents.
2. Add a rate-limiting `pre_tool_use` hook: at most 3 `write_file` calls per session.
3. Render `list_subkeys` as a tree. What does a subagent that spawns its own subagents look like?
4. Add an "auto" permission mode that calls Lesson 55's decision-model stand-in and maps P(safe) to allow (>0.9), ask (0.5–0.9) or deny.
5. Port the toy to two real SDKs from the table. Which harness pieces did each give you for free?

## 8. Key terms

| Term | Meaning |
|---|---|
| Harness | Everything around the model: loop, tools, policy, context, state |
| Agent SDK | A harness packaged as a library |
| Subagent | A child agent with its own context and permissions that returns a summary |
| Hook | Deterministic code run at a lifecycle event, able to veto or log |
| Permission mode | Default policy for tool calls: allow, ask, deny or auto |
| Session store | Persistence for transcripts, with fork and cascading delete |
| Compaction | Replacing older context with a summary to stay within the window |
| `traceparent` | W3C header that carries one trace ID across processes |

## 9. Quick check

<details><summary>1. What does a subagent save the lead agent?</summary>Context. The subagent reads files and runs tools in its own window and returns only a summary, so the lead's budget goes to coordination.</details>
<details><summary>2. Why put a "no writes outside the workspace" rule in a hook rather than the prompt?</summary>A hook runs as code on every call and cannot be talked out of its decision. A prompt instruction can be ignored or overridden by injected content.</details>
<details><summary>3. When would you choose a hosted harness over an SDK?</summary>When you need managed sandboxes, long-running or scheduled runs and built-in compaction more than you need control over the loop, and the data and vendor constraints allow it.</details>

## References

- OpenAI Agents SDK: https://openai.github.io/openai-agents-python/
- Google Agent Development Kit: https://google.github.io/adk-docs/
- Microsoft Agent Framework: https://learn.microsoft.com/en-us/agent-framework/
- Vercel AI SDK agents: https://ai-sdk.dev/docs/agents/overview
- Pydantic AI: https://ai.pydantic.dev/
- W3C Trace Context: https://www.w3.org/TR/trace-context/
- Böckeler, "Harness engineering for coding agent users" (martinfowler.com, April 2026): https://martinfowler.com/
- AGENTS.md: https://agents.md/
- Model Context Protocol specification 2026-07-28: https://modelcontextprotocol.io/specification/2026-07-28/changelog
