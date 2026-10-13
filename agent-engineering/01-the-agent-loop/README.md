# 01 · The Agent Loop: Observe, Think, Act

> **Short answer:** An agent is a loop. The model reasons, asks for a tool, the harness runs it and appends the result, and the model goes again until a stop condition fires. ReAct (2022) named the pattern. In Oct 2026 the reasoning lives in a native, opaque thinking channel, not in `Thought:` text you print, but the control flow has not changed. Learn this loop cold before you touch any framework; every SDK in this course wraps it.

**Type:** Build · **Languages:** Python (stdlib) · **Time:** ~60 min

---

## 1. The problem

A bare LLM call is a function from text to text. It cannot read a file, query a database or check a claim. When its knowledge is stale it answers wrong with full confidence and stops.

The fix is small: let the model pause, request a tool, see the result and continue. Everything later in this track (memory, planning, sub-agents, evals, guards) is scaffolding around that one loop. If you cannot draw the loop and list its stop conditions, you cannot debug any agent built on top of it.

## 2. The concept

### ReAct, the original shape

Yao et al. (arXiv:2210.03629, ICLR 2023) interleaved three things in one text stream:

```
Thought: I need the capital of France.
Action: search("capital of France")
Observation: Paris is the capital of France.
Thought: Done.
Action: finish("Paris")
```

The reasoning trace lets the model form a plan, track it across steps and react when an observation surprises it. On ALFWorld and WebShop, ReAct beat imitation and RL baselines with only one or two in-context examples, and on HotpotQA grounding each step in retrieval reduced hallucination.

### The same loop in 2026

```
          ┌──────────────────────────────────────────────────────┐
 user ──► │ messages[] (append-only)                             │
          └──────────┬───────────────────────────────────────────┘
                     ▼
              model.create(messages, tools)
                     │  content = [thinking?, text?, tool_use*]
                     ▼
        stop_reason == "tool_use" ? ──yes──► run every tool_use
                     │ no                     append ONE user msg with all tool_results
                     ▼                        (matched by tool_use_id, is_error on failure)
        end_turn / refusal / max_tokens / budget ──► stop
```

### Five ingredients

| # | Ingredient | What goes wrong without it |
|---|---|---|
| 1 | **Message buffer** that only grows | Lost context, or broken thinking blocks if you edit it |
| 2 | **Tool registry** with name, description, JSON Schema | The model invents tools or arguments |
| 3 | **Stop conditions**: `end_turn`, `refusal`, `max_tokens`, guard trip | Agent never ends, or ends silently on an error |
| 4 | **Turn and token budget** | Runaway loops and runaway bills |
| 5 | **Observation formatter** that turns every failure into a `tool_result` | One HTTP 400 crashes the run instead of teaching the model |

### Why every framework looks the same underneath

Agent SDKs from frontier model providers, the OpenAI Agents SDK, LangGraph, Microsoft Agent Framework, ADK, CrewAI and the Vercel AI SDK all run this loop. They differ in what surrounds it: checkpoints, handoffs, role templates, tracing, durable execution. The 2026 name for that surrounding layer is **harness engineering** ("Agent = Model + Harness").

## 3. What changed by Oct 2026

- **Native reasoning is the default.** On current frontier models, adaptive thinking with an effort setting (`low` to `max`, including `xhigh`) replaces fixed thinking budgets, and a fixed token budget is rejected with a 400. On some flagship models thinking cannot be turned off and effort defaults to `medium`, so set it explicitly per route.
- **Thinking is opaque.** The thinking display defaults to `omitted`: you get `thinking` blocks with empty text and a signature. You still pass them back unchanged on the next turn.
- **Append-only history is now a hard rule.** "Preserved thinking" binds thinking blocks to the exact conversation that produced them. If your harness rewrites or trims earlier messages, those blocks are invalidated, and newer accounts get a 400. Use the API's context editing or server-side compaction instead of hand-editing.
- **Assistant prefill is gone** (400 on current frontier models). Use structured outputs or `strict: true` tools to shape output.
- **Forced tool choice is gone on the newest models.** `tool_choice` `any`/`tool` returns a 400 on the newest frontier models. Use `auto` plus a prompt instruction, and `strict: true` for schema-valid arguments.
- **Operator steering mid-run** uses `role: "system"` messages appended to `messages[]`, which keeps the cached prefix intact and gives you an injection-resistant channel.
- **Providers converged.** OpenAI's Responses API (GPT-6.1 Sol, GPT-6 Luna) and Google's Gemini 3.8 Flash carry reasoning across turns in their own formats. Frameworks renamed loop knobs; for example Vercel AI SDK v7 renamed `stepCountIs` to `isStepCount`.
- **Budgets moved server-side.** Provider-side task budgets tell the model how many tokens the whole loop may spend so it paces itself instead of being cut off.
- **2026 update, System One stop conditions:** "Is the task done?" and "Is this tool call in scope?" are bounded questions. A decision model (Jev or Clef, Lessons 55–56) can answer them as a `noul` probability in milliseconds, with the threshold kept in your code.

## 4. Build it

`code/main.py` is a stdlib loop that uses the same block shapes as the Messages API:

- `ToolRegistry`: sorted catalog (stable order keeps the prompt cache warm), required-field checks, and every failure returned as `tool_result` with `is_error: true`.
- `calculator`: an AST-based arithmetic evaluator. No `eval`.
- `ScriptedModel`: deterministic responses containing opaque `thinking` blocks, two parallel `tool_use` calls, and one malformed call.
- `AgentLoop`: turn budget, stop-reason handling, and all results for one turn returned in a single user message.
- `AppendOnlyGuard`: fingerprints each prior message and fails loudly if the harness edits history.

```bash
python3 code/main.py
```

What to look for:

1. The malformed call (`expr` instead of `expression`) comes back as an error observation, and the model recovers on the next turn.
2. With `max_turns=2` the run stops with `max_turns`, not with a crash or a fake answer.
3. The "harness bug" demo trims an old tool result in place, and the guard trips. That is the bug class preserved thinking now punishes.

## 5. Use it in production

| Need | Oct 2026 option |
|---|---|
| Own the loop | Provider API manual loop, or the SDK's built-in tool runner |
| Batteries-included coding agent | An agent SDK with built-in tools, hooks, subagents and sessions (Lesson 17) |
| Hosted loop and sandbox | Hosted agent platforms, OpenAI Agents SDK sandbox agents, Cloudflare Agents |
| Graph-shaped control | LangGraph 1.2, Google ADK 2.x graph workflows, Microsoft Agent Framework 1.x |
| TypeScript apps | Vercel AI SDK v7 `ToolLoopAgent`, or `WorkflowAgent` for durable runs |

Start with the manual loop for one week of a project. Once you can see the turns, move to a framework for durability and tracing.

## 6. Architect's lens

1. **Stop conditions are product decisions.** "No tool calls" ends the turn, but `refusal`, `max_tokens` and guard trips each need their own handling and their own metric. Track the stop-reason mix per release.
2. **Tool outputs are untrusted input.** A fetched page can say "delete the repo". Only the user and the operator grant permission (Lesson 27, OWASP ASI01 Agent Goal Hijack).
3. **Cost grows with the transcript.** Every turn re-sends history. Prompt caching, a stable tool order, context editing and compaction are what make 50–400 step runs affordable. Measure cost per completed task, not per request.
4. **Agents confuse "I failed" with "the task is impossible".** Return structured errors with a hint about what to fix, and alert on runs that end `end_turn` right after an `is_error` result (Lesson 26).
5. **Tune effort per route.** Low effort for sub-agents and simple routes, high or `xhigh` for long agentic coding. Re-run the sweep when you change model.

## 7. Exercises

1. Add a `max_tool_calls_per_turn` cap. If the model asks for three calls and you allow two, what do you return for the third so the transcript stays valid?
2. Add a `refusal` response to the script and route it to a fallback path. Log the stop reason as a metric.
3. Replace `ScriptedModel` with a real provider API call using adaptive thinking at low effort. Confirm the guard never trips.
4. Implement a `done` check as a `noul` question against a local stand-in for Jev (see Lesson 55's `LocalSystemOne`). Stop when P(done) > 0.85 and compare turn counts.
5. Run two tools concurrently with `concurrent.futures` and show that results still map correctly by `tool_use_id`.

## 8. Key terms

| Term | Meaning |
|---|---|
| Agent loop | Model call, tool execution and observation, repeated until a stop condition |
| ReAct | Yao et al. 2022: interleave reasoning and actions in one trajectory |
| Adaptive thinking | The model decides how much to reason; you steer with `effort` |
| Preserved thinking | Thinking blocks are valid only in the unedited conversation that produced them |
| `tool_use_id` | Correlates a call with its result; required for parallel calls |
| Stop reason | Why a model turn ended: `end_turn`, `tool_use`, `max_tokens`, `refusal`, ... |
| Harness | Everything around the model: loop, tools, context policy, guards, budgets |

## 9. Quick check

<details><summary>1. Why do all parallel tool results go back in one user message?</summary>That is the shape the model was trained on. Splitting them across messages teaches it to stop making parallel calls, and the ids still have to match.</details>
<details><summary>2. You want to drop old, bulky tool outputs. What do you do in 2026?</summary>Use context editing (clearing old tool results) or server-side compaction. Do not edit earlier messages in place: that invalidates preserved thinking and the prompt cache.</details>
<details><summary>3. Is "no tool calls in the response" a safe completion signal?</summary>It ends the turn, but not necessarily the task. Pair it with a verifier or a cheap "is it done?" decision for tasks with a checkable outcome.</details>

## References

- Yao et al., ReAct (arXiv:2210.03629): https://arxiv.org/abs/2210.03629
- OpenAI Agents SDK: https://openai.github.io/openai-agents-python/
- Böckeler, Harness engineering for coding agent users: https://martinfowler.com
