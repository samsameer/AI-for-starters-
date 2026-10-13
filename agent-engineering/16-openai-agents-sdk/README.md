# 16 · OpenAI Agents SDK: Handoffs, Guardrails, Sessions, Tracing

> **Short answer:** The OpenAI Agents SDK is a small, code-first framework on top of the Responses API. An `Agent` is instructions plus tools plus handoffs; a `Runner` drives the loop. Handoffs appear to the model as tools named `transfer_to_<agent>`, guardrails are tripwires on input, output and tool calls, sessions keep history, and tracing is on by default. Use it when you want multi-agent delegation with very little framework, especially on OpenAI models, though it also runs other providers.

**Type:** Learn + Build · **Languages:** Python (stdlib) · **Time:** ~75 min

---

## 1. The problem

A single agent that does everything ends up with a 6,000-token system prompt, thirty tools and confused tool selection. Splitting it into specialists helps, but then you need three things:

1. A clean way to **delegate**, so the billing specialist gets the conversation and the triage agent steps aside.
2. **Policy checks** that run whatever the model decides: no card numbers in, no internal URLs out, no $10,000 refunds.
3. **Visibility** into which agent did what, so you can debug and audit.

The Agents SDK's answer is a small set of primitives that cover exactly those three.

## 2. The concept

### The primitives

| Primitive | What it does |
|---|---|
| `Agent` | Model, instructions, tools, handoffs, guardrails, optional `output_type` |
| `Runner` | Runs the loop: call model, run tools, follow handoffs, stop on final output |
| Handoff | Delegation exposed to the model as a tool, `transfer_to_<name>` |
| Guardrail | Input, output or tool check that can raise a tripwire |
| Session | Stores conversation items between runs (SQLite, Redis, custom) |
| Tracing | Spans for agents, generations, tools, handoffs and guardrails |

### Handoffs are tools

```
user ─► triage ──transfer_to_billing──► billing ──issue_refund (needs approval)──► pause
                                                                                   │
                                     RunState saved ◄──────────────────────────────┘
                                     human approves ─► Runner resumes ─► final output
```

Because a handoff is a tool, the model chooses it with the same machinery it uses for any function, and the runtime does the switch: the target agent's instructions take over, and the history is passed along (optionally collapsed into a summary). An "agent as tool" is the other option: the sub-agent runs, returns a result, and the caller stays in charge. Use handoffs when the specialist should own the rest of the conversation, and agents-as-tools when the orchestrator should.

### Guardrails

| Kind | Runs on | Typical checks |
|---|---|---|
| Input | The first agent's input | Off-topic, PII, jailbreak attempts |
| Output | The final agent's output | Leaks, policy, schema |
| Tool | Each function-tool call | Argument limits, permissions, audit |

Input guardrails can run **in parallel** with the agent (lower latency, but tokens are wasted when they trip) or **blocking** (`run_in_parallel=False`, no waste, slower first token). A trip raises `InputGuardrailTripwireTriggered` or `OutputGuardrailTripwireTriggered`.

### Human approval and resumable runs

A tool marked as needing approval interrupts the run. The result carries the pending call and a serializable `RunState`. You approve or reject, then hand the state back to the runner, possibly days later and on another machine.

### Where it goes wrong

- **Handoff ping-pong.** Support hands back to triage, triage hands to support. Cap handoffs and turns.
- **Guardrail gaps.** Tool guardrails cover your function tools. Hosted tools (web search, file search, code interpreter, MCP) need their own policy.
- **Over-tracing.** Spans can contain user data. Decide what content is captured and where it goes before launch.

## 3. What changed by Oct 2026

- **Versions:** the Python SDK is at 0.23.x and the JS/TS SDK at 0.20.x. It is still pre-1.0, so read release notes before upgrading.
- **Resumable runs:** `RunState` can be serialized and resumed, and `add_input()` appends new user input to a paused run. Built-in **retry policies** handle transient model and tool errors.
- **Sandbox agents:** container-backed agents for long-horizon work, with mounted storage, so code and files live outside the context window.
- **Programmatic Tool Calling tool:** the model writes code that calls your tools in a sandbox, and only the final result returns to the context (the ReWOO idea from Lesson 02, productized).
- **MCP Python SDK 2.x support** (stateless MCP, spec 2026-07-28), a `@tool` alias for `@function_tool`, stricter guardrail and failed-response handling, and a dependency on the `openai>=3` client.
- **Default model and models:** recent releases default to a small, fast GPT model; the GPT-6 family (GPT-6.1 Sol, GPT-6 Luna) is current on the Responses API. Set the model explicitly and do not rely on defaults.
- **Durability:** the Temporal integration is GA, so a run can survive process restarts with each model and tool call as a durable activity. Realtime and voice agents run on `gpt-realtime-2.1`.
- **2026 update, System One guardrails:** most guardrails are yes/no questions ("does this input contain a card number?", "is this refund within policy?"). A decision model (Jev or Clef, Lessons 55–56), or OpenAI's own Decisions API in public beta since early October, answers them as calibrated probabilities in milliseconds, which makes **blocking** guardrails cheap enough to use by default.

## 4. Build it

`code/main.py` re-implements the SDK's shape with a scripted fake model:

- `Agent`, `FunctionTool` (with `needs_approval` and a per-tool guardrail), `Session`, `Span`, `RunState`, `RunResult`.
- `Runner.run` checks input guardrails (blocking or parallel), loops over model turns, turns `transfer_to_*` calls into agent switches, enforces a handoff cap, runs output guardrails and builds a span tree.
- `Runner.resume` continues an interrupted run after a human decision.
- A triage agent with billing and support specialists, a card-number input guardrail, an internal-URL output guardrail and a $500 refund cap.

```bash
python3 code/main.py
```

What to look for: the support handoff; the refund that pauses for approval and then completes after `resume`, with the full span tree; the oversized refund blocked by the tool guardrail; `wasted tokens=0` for the blocking input guardrail against `400` for the parallel one; and the handoff loop stopped at the cap.

## 5. Use it in production

```python
from agents import Agent, Runner, SQLiteSession, input_guardrail, GuardrailFunctionOutput, function_tool

@function_tool(needs_approval=True)
def issue_refund(amount: int) -> str:
    return f"refunded ${amount}"

@input_guardrail(run_in_parallel=False)
async def no_card_numbers(ctx, agent, text):
    found = any(ch.isdigit() for ch in str(text)) and "card" in str(text).lower()
    return GuardrailFunctionOutput(output_info=None, tripwire_triggered=found)

billing = Agent(name="billing", instructions="Handle refunds.", tools=[issue_refund])
triage = Agent(name="triage", instructions="Route the user.", handoffs=[billing],
               input_guardrails=[no_card_numbers])

result = await Runner.run(triage, "Refund $40 for invoice 118", session=SQLiteSession("u2"))
```

- **Sessions:** SQLite for development; Redis, SQLAlchemy or a custom backend in production.
- **Tracing:** add a trace processor to send spans to your own backend (Langfuse, LangSmith, Phoenix, any OTel collector), or disable OpenAI-hosted tracing when data must stay in-house.
- **Durability:** use the Temporal integration for runs that must survive restarts or wait on humans for long periods.
- **Alternatives:** the harness-style agent SDKs in Lesson 17, LangGraph when you want an explicit graph (Lesson 13), Microsoft Agent Framework for typed workflows (Lesson 14).

## 6. Architect's lens

1. **Handoff or agent-as-tool is an ownership decision.** Handoffs give the specialist the user; agents-as-tools keep one orchestrator accountable for the final answer. Mixing both without a rule makes traces unreadable.
2. **Blocking vs parallel guardrails is a latency-versus-cost trade.** Measure the trip rate. At a 1% trip rate, parallel is usually fine; at 20%, blocking pays for itself.
3. **Approvals are state, not callbacks.** Persist the `RunState`, give it an ID, and build the approval UI around that ID. Never keep a process blocked on a human.
4. **Bound the loop three ways:** max turns, max handoffs and a token or cost budget per run. Alert when any limit is hit.
5. **Pin the model and the SDK.** Pre-1.0 releases change defaults. An upgrade that quietly changes the default model changes your product.

## 7. Exercises

1. Add `collapse_history` to handoffs: summarize earlier turns into one item before switching agents. Compare token counts.
2. Turn the support agent into an agent-as-tool for triage. How does the span tree change?
3. Serialize `RunState` to JSON, restart the "process" (create a new `Runner`) and resume from the file.
4. Add an output guardrail that rejects any answer longer than 300 characters, and make the billing agent trip it.
5. Replace `no_card_numbers` with a `noul` question to Lesson 55's local stand-in and pick a threshold from a small labeled set.

## 8. Key terms

| Term | Meaning |
|---|---|
| Handoff | A tool that transfers the conversation to another agent |
| Agent as tool | A sub-agent called like a function; the caller keeps control |
| Tripwire | The exception raised when a guardrail rejects |
| Blocking guardrail | Runs before the agent; no wasted tokens on a trip |
| Parallel guardrail | Runs alongside the agent; faster, wastes tokens on a trip |
| `RunState` | Serializable snapshot of a paused run, used to resume |
| Session | Stored conversation items reused across runs |
| Trace processor | A hook that forwards spans to your observability backend |

## 9. Quick check

<details><summary>1. Why model a handoff as a tool?</summary>The model already knows how to choose tools, so delegation reuses the same mechanism. The runtime then does the switch deterministically: new instructions, transferred history, continued run.</details>
<details><summary>2. When should an input guardrail be blocking?</summary>When it trips often or the main call is expensive, so wasted tokens outweigh the extra latency. Also when the input must never reach the main model at all.</details>
<details><summary>3. A refund needs a manager's approval that may take a day. How do you build it?</summary>Mark the tool as needing approval, persist the interrupted `RunState` with an ID, show the pending call in an approval UI, then load the state and resume the run when the manager decides.</details>

## References

- OpenAI Agents SDK (Python): https://openai.github.io/openai-agents-python/
- Handoffs: https://openai.github.io/openai-agents-python/handoffs/
- Guardrails: https://openai.github.io/openai-agents-python/guardrails/
- Release notes: https://github.com/openai/openai-agents-python/blob/main/docs/release.md
- OpenAI Agents SDK (JS/TS): https://openai.github.io/openai-agents-js/
- Temporal integration: https://temporal.io/blog/announcing-openai-agents-sdk-integration
- OpenAI API changelog: https://developers.openai.com/api/docs/changelog
