# 06 · Tool Use and Function Calling

> **Short answer:** Function calling means the model emits a structured request (tool name plus JSON arguments) and your runtime decides whether and how to execute it. Picking the right tool for a single request is largely solved. What still breaks production agents is everything around the call: vague descriptions, unvalidated arguments, side effects without approval, slow or flaky tools, and long chains of calls. Treat the tool layer as an API gateway with a contract. Do not treat it as a convenience.

**Type:** Build · **Languages:** Python (stdlib) · **Time:** ~60 min

---

## 1. The problem

Early research asked whether a model could produce a correct function call at all. Toolformer (Schick et al., NeurIPS 2023, arXiv:2302.04761) showed that models can learn when to call tools by self-supervision: insert candidate API calls into text, execute them, and keep only the ones whose results make the following text easier to predict. Tool use emerged with scale.

Today's question is different. Can the agent chain dozens of calls with memory, recover from tool errors, refuse when no tool fits, and never perform an irreversible action it was not allowed to take? The Berkeley Function Calling Leaderboard (BFCL, Patil et al., ICML 2025) reflects this shift. V4 weights agentic and multi-turn categories most heavily and keeps an explicit hallucination category for "no tool should be called". The open problems are long-horizon chains, decisions based on earlier results, memory, and abstention.

## 2. The concept

### The contract

Every provider uses the same shape, with small spelling differences:

```
name          short, verb_noun, unique
description   what it does AND when to use it   <- the model reads this to choose
input_schema  JSON Schema: types, enums, required, formats, additionalProperties:false
```

Descriptions are the most common cause of wrong-tool selection. A good one says "Use when the user names a specific order like A-100". A bad one says "Order tool".

### The loop around a call

```
 model message: [call_1 get_order] [call_2 list_orders] [call_3 issue_refund]
          │
          ▼
 ┌──────────────── preflight per call ─────────────────┐
 │ known tool? ─► breaker closed? ─► args valid? ─►    │
 │ effect allowed (read / write / irreversible)?       │
 └───────────────┬─────────────────────────┬───────────┘
          ok     │                         │ problem
                 ▼                         ▼
        run in parallel, timeout     structured error text
                 │                         │
                 └──── results keyed by call_id ────► next model turn
```

### Validation rules

1. **Required fields and unknown fields.** Missing means error. Extra means error when `additionalProperties` is false, which it should be.
2. **Types, strict by default.** Coercing `"5"` to `5` hides drift in the model's behaviour. Turn on strict schema mode at the provider, and validate again on your side.
3. **Enums and formats.** Validate dates with a parser, not a regex.
4. **Errors are observations.** Return a precise message ("'day'='next tuesday' is not an ISO date") so the model can fix the call. Never raise into the loop.

### Parallel calls and correlation ids

One assistant message can contain several calls. Run independent ones concurrently and return each result with its `call_id`. If you mix up the ids, results get routed to the wrong calls and the model reasons over the wrong data.

### Side effects and the blast radius

Tag every tool with its effect: `read`, `write`, `irreversible`. Policy, not the prompt, decides what runs unattended. A narrow `issue_refund(order_id, amount)` behind an approval step is safe. A generic `run_shell(cmd)` is not.

## 3. What changed by Oct 2026

- **Strict schemas replace forced tool choice.** Several current frontier models reject forced `tool_choice` (`any` or a named tool) and assistant prefill. The supported route is `tool_choice: auto` with strict schemas (`strict: true`) or a structured-output response format.
- **MCP went stateless.** The MCP spec revision `2026-07-28` removed the `initialize` handshake and protocol sessions, added `server/discover`, requires full JSON Schema 2020-12 in tool schemas, and makes `tools/list` order deterministic so prompt caching works. Cross-call state now travels as server-minted handles in tool arguments.
- **Tool search and deferred loading.** With hundreds of tools, agents load only the schemas they need through a search step. Several provider APIs offer a hosted tool-search tool.
- **Code instead of many calls.** Programmatic tool calling (the OpenAI Agents SDK has a dedicated tool for it) and Cloudflare Code Mode let the model write a short program that calls your tools in a sandbox. Intermediate results stay out of the context.
- **Tool security is a top risk.** OWASP's Top 10 for Agentic Applications 2026 lists Tool Misuse and Exploitation (ASI02). In early 2026, more than 30 MCP-server CVEs were reported in about 60 days, many of them command injection, and trojanized MCP servers appeared on public registries. Pin, review and sandbox third-party tools.
- **SDK changes.** Vercel AI SDK v7 replaced `ToolCallOptions` with `ToolExecutionOptions` and renamed `stepCountIs` to `isStepCount`. The OpenAI Agents SDK added an `@tool` alias and retry policies.
- **2026 update, System One tool guard:** "Should this action run?" and "which of these tools fits, or none?" are typed `noul` and `choice` questions. A decision model (Jev or Clef, Lessons 55–56) can answer them in tens of milliseconds before a call executes. Keep the threshold and the fail-open or fail-closed choice in your own code, and treat the state you send as untrusted input.

## 4. Build it

`code/main.py` builds a production-shaped registry over a toy order system:

- `validate`: a JSON Schema subset with required, unknown fields, types, enums, minimum and ISO-date format, in strict or lenient mode.
- `lint_description`: flags short descriptions, missing "use when" guidance and undocumented parameters.
- `Registry.search`: keyword tool search, showing how much schema text you avoid loading.
- `Registry.preflight`: unknown tool (with a "did you mean"), circuit breaker, validation and effect policy.
- `Registry.dispatch`: parallel execution with per-tool timeouts. Results come back in call order, keyed by `call_id`.
- `scripted_model`: three turns. Turn 1 makes six mistakes, turn 2 fixes them from the error text, turn 3 hits the open breaker.

```bash
python3 code/main.py
```

What to look for: the lint catches the weak `legacy_inventory` description. In turn 1, one call succeeds and five fail with readable reasons, including the blocked refund. Turn 2 succeeds after reading those errors. The slow legacy tool trips the breaker. Strict mode rejects `"5"` while lenient mode quietly accepts it, and the refund list stays empty.

## 5. Use it in production

- **Provider APIs:** strict tool schemas or structured outputs, `tool_choice: auto`, parallel calls on, and a hosted tool search for large catalogs.
- **MCP servers:** build against the `2026-07-28` spec and the MCP SDK 2.x line. Use server-minted handles instead of sessions, and run third-party servers in a sandbox with egress limits.
- **OpenAI Agents SDK:** function tools with Pydantic-validated arguments, guardrails, retry policies and programmatic tool calling.
- **Vercel AI SDK v7:** `tool()` definitions with Zod schemas, `ToolLoopAgent`, and `WorkflowAgent` for durable approvals that can wait hours or days.
- **Google ADK 2.x:** tool confirmation inside workflow nodes (`RequestInput`) for human approval of write actions.
- **Evaluation:** run BFCL-style suites, including hallucination cases, against your own tools before shipping.

## 6. Architect's lens

1. **The schema is a security boundary.** `additionalProperties: false`, narrow types and enums shrink what an injected prompt can make a tool do. Validate on your side even when the provider enforces strict mode.
2. **Design tools for the model, not for your codebase.** Prefer a few task-shaped tools (`refund_order`) over many thin CRUD wrappers. Each extra tool adds selection errors and context cost.
3. **Effect tiers drive approvals.** Reads run freely, writes are logged and rate-limited, and irreversible actions need a human or a policy engine. Make the tier part of the tool definition so it cannot be forgotten.
4. **Budget the tool layer.** Per-tool timeouts, circuit breakers and concurrency caps keep one slow dependency from consuming the turn. Track error rate per tool and per argument field.
5. **Log calls as spans.** Emit an OpenTelemetry `execute_tool` span per call with the tool name, `call_id`, outcome and latency (Lesson 23). Most "the agent is dumb" bugs are tool-layer bugs.

## 7. Exercises

1. Add a `no_tool` option the model can pick when nothing fits, and write three prompts where it is the right answer.
2. Lenient mode accepts `"5"`. Find an input where coercion hides a real bug, for example `"05"` as an order id or `"1e3"` as a limit.
3. Make the breaker half-open: after N seconds, allow one trial call through and close the breaker if it succeeds.
4. Add a stand-in guard `should_run(call) -> P(safe)` before `write` tools, and block below 0.8. Decide whether a guard outage should fail open or fail closed for each effect tier.
5. Export the catalog in the provider-neutral shape and as an MCP `tools/list` result. What has to change between them?

## 8. Key terms

| Term | Meaning |
|---|---|
| Function calling | The model emits a structured tool request and the runtime executes it |
| Tool schema | Name, description and JSON Schema for the arguments |
| Strict mode | Provider-side guarantee that arguments match the schema exactly |
| `call_id` | Correlation id that ties each call to its result |
| Effect tier | Read, write or irreversible; decides approval policy |
| Circuit breaker | Temporarily disables a tool after repeated failures |
| Tool search | Loading only the relevant tool schemas into context |
| Toolformer | Self-supervised learning of when to call tools (Schick et al., 2023) |
| BFCL | Berkeley Function Calling Leaderboard |

## 9. Quick check

<details><summary>1. Why return validation errors as observations instead of raising?</summary>The model can read a precise error and correct the call on the next turn. An exception ends the loop and teaches nothing.</details>
<details><summary>2. Why is lenient coercion risky?</summary>It hides drift in the model's output and can turn a malformed value into a wrong but valid one. Prefer strict schemas and explicit errors.</details>
<details><summary>3. What decides whether issue_refund runs unattended?</summary>The effect tier and the runtime policy, enforced in code. The model's own judgment is not a control.</details>

## References

- Schick et al., Toolformer (arXiv:2302.04761): https://arxiv.org/abs/2302.04761
- Berkeley Function Calling Leaderboard: https://gorilla.cs.berkeley.edu/leaderboard.html
- MCP specification 2026-07-28 changelog: https://modelcontextprotocol.io/specification/2026-07-28/changelog
- OpenAI function calling guide: https://platform.openai.com/docs/guides/function-calling
- OpenAI Agents SDK, tools: https://openai.github.io/openai-agents-python/tools/
- OWASP Top 10 for Agentic Applications 2026: https://genai.owasp.org/
- JSON Schema 2020-12: https://json-schema.org/draft/2020-12
