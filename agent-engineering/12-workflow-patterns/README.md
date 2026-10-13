# 12 · Workflow Patterns: Simple Over Complex

> **Short answer:** A **workflow** runs LLM calls along paths your code defines. An **agent** lets the model choose its own path. Five workflow patterns cover most production needs: prompt chaining, routing, parallelization, orchestrator-workers and evaluator-optimizer. Start with direct API calls and these patterns, and promote to an agent only when you truly can't predict the steps. The 2024 advice still holds in October 2026. What changed is that the patterns are now built into harnesses and hosted platforms.

**Type:** Learn + Build · **Languages:** Python (stdlib) · **Time:** ~60 min

## 1. The problem

Teams reach for a multi-agent framework to solve problems that need a function call and an `if`. Frameworks hide prompts, hide control flow and invite complexity before it is needed. Schluntz and Zhang's "Building Effective Agents" (Dec 2024) became the standard pushback: **find the simplest thing that works, and add complexity only when it measurably improves outcomes.**

## 2. The concept

### Workflow vs agent

| | Workflow | Agent |
|---|---|---|
| Who owns the path | Your code | The model |
| Step count | Bounded, known | Unbounded, discovered |
| Debugging | Read the code | Read the trajectory |
| Cost profile | Predictable | Heavy-tailed |
| Best for | Repeatable tasks | Open-ended tasks |

Both are built from the **augmented LLM**: one model call with retrieval, tools and memory available.

### The five patterns

```
 1 chaining        in ─► LLM ─► gate ─► LLM ─► gate ─► LLM ─► out
 2 routing         in ─► classify ─┬─► handler A
                                   ├─► handler B
                                   └─► abstain ─► human
 3 parallelization in ─┬─► LLM (section 1) ─┐
                       ├─► LLM (section 2) ─┼─► aggregate / vote
                       └─► LLM (section 3) ─┘
 4 orchestrator    in ─► orchestrator plans ─► workers (chosen at runtime) ─► synthesize
 5 eval-optimizer  in ─► propose ─► evaluate ─► feedback ─┐
                           ▲──────────────────────────────┘ (until pass or budget)
```

1. **Prompt chaining.** Split a task into fixed steps, and put programmatic gates between them (length, schema, keyword checks).
2. **Routing.** Classify the input and dispatch it to a specialized prompt, model or tool. Always include an **abstain** route.
3. **Parallelization.** *Sectioning* runs independent chunks concurrently. *Voting* runs the same prompt N times and aggregates, with a quorum.
4. **Orchestrator-workers.** An orchestrator decides the subtasks at runtime and synthesizes the results. Unlike an agent, it does not loop forever.
5. **Evaluator-optimizer.** Propose, critique, revise. This is Self-Refine (Lesson 05) generalized, and it needs a clear rubric.

### When workflows win, and when agents win

- **Workflows** win when steps are enumerable, cost must be bounded, or auditors need to read the graph.
- **Agents** win when the next step depends on the last observation, when the length of work is unknown, or when you are still discovering what the workflow should be. Explore with an agent first, then codify what you learn into a workflow.

## 3. What changed by Oct 2026

- **Harness engineering is the named discipline.** The 2026 harness-engineering posts (on long-running agents, and the planner/generator/evaluator harness design) apply these five patterns at the scale of hours-long runs. Evaluator-optimizer became planner → generator → evaluator.
- **Dynamic workflows went first-party.** Coding agents ship `/workflows` commands that orchestrate many agents, and hosted agent platforms added multiagent rosters with dynamic workflows. These are orchestrator-workers as a hosted feature.
- **Context engineering is the companion discipline.** On current frontier models with 1M-token windows, the budget is still a budget. Server-side compaction and context editing decide what stays in the window.
- **API details that affect these patterns.** Current frontier models reject assistant prefill and forced `tool_choice`. For a routing classifier, use `tool_choice: auto` with `strict: true` or structured outputs, not a forced tool. Keep transcripts append-only so preserved thinking and caching keep working.
- **Routing is moving off the LLM.** Typed decision models (Jev, Clef, OpenAI Decisions API in beta) return a calibrated probability for each label in one pass. That is exactly what pattern 2 needs.

## 4. Build it

`code/main.py` implements all five patterns against a `ScriptedLLM` and counts the LLM calls per pattern:

- `prompt_chain()` with a gate after each step.
- `route()` with a **confidence threshold** and an abstain path to a human. The classifier returns a probability per label, so this step makes zero LLM calls.
- `parallel_sections()` using a thread pool, and `parallel_vote()` with a **quorum** that returns `no-consensus` when votes split.
- `orchestrator_workers()`, where the orchestrator's plan picks two of three workers at runtime.
- `evaluator_optimizer()` with **best-so-far retention** and a round budget.

```bash
python3 code/main.py
```

Look for: "hello, quick question" escalated at p=0.33, the migration vote returning `no-consensus`, the orchestrator skipping `style_review`, and the rubric score climbing 1 → 2 → 3.

## 5. Use it in production

- **Direct SDKs first:** a provider SDK such as `openai` (Responses API) or `google-genai`. Each pattern is 10–30 lines.
- **When you need durability or resume:** LangGraph 1.2.x (Lesson 13), Microsoft Agent Framework workflows (Lesson 14), or Vercel `WorkflowAgent` / Vercel Workflows.
- **When you want a harness:** agent SDK subagents (Lesson 17), or OpenAI Agents SDK handoffs and agents-as-tools (Lesson 16).
- **When you want it hosted:** hosted agent platform dynamic workflows, or Google's Gemini Enterprise Agent Platform.

## 6. Architect's lens

1. **Count the calls.** Write down the worst-case LLM calls per request for each pattern. Voting multiplies cost by N. An evaluator-optimizer multiplies it by rounds × 2. Put the numbers in the design doc.
2. **Every router needs an abstain path.** Misroutes are silent failures. A threshold plus a human or fallback queue turns them into measurable escalations.
3. **Gates are code, not prompts.** Schema, length, regex and test checks between steps are cheap and deterministic. Use an LLM judge only when no mechanical check exists.
4. **Promote patterns by evidence.** Move from workflow to agent only when the trajectory logs show that the fixed path fails on a meaningful share of real inputs.
5. **2026 update, System One routing.** Patterns 2 (router), 3 (vote) and 5 (judge) are all typed decisions. A decision model such as Jev or Clef (Lessons 55–57) answers them as `choice`, `noul` or `score` with calibrated probabilities in milliseconds. Keep the LLM for the generating steps.

## 7. Exercises

1. Sweep the routing threshold from 0.3 to 0.9 on 30 labeled tickets and plot automation rate against misroute rate.
2. Add a per-call timeout to `parallel_vote` and decide how to count missing votes.
3. Make the evaluator-optimizer stop early when the score fails to improve for two rounds.
4. Combine routing and chaining: the router picks one of three chains. Compare total tokens with a single large prompt.
5. Draw the graph of one of your production features. Count the steps. Is an agent actually justified?

## 8. Key terms

| Term | Meaning |
|---|---|
| Workflow | An engineer-owned path of LLM and tool calls |
| Agent | A model-owned path in which the LLM chooses tools and steps dynamically |
| Augmented LLM | One model call with retrieval, tools and memory |
| Abstain path | The route taken when the router is not confident enough |
| Quorum | The minimum vote share required to accept a parallel-vote result |
| Evaluator-optimizer | A propose → critique → revise loop with a rubric and budget |
| Harness engineering | Designing the code around a model: loops, tools, context, checks |

## 9. Quick check

<details><summary>1. What is the difference between orchestrator-workers and an agent?</summary>The orchestrator chooses subtasks at runtime but runs a bounded plan once and then synthesizes. An agent keeps looping and choosing actions until it decides it is done.</details>
<details><summary>2. Why keep the best-so-far in an evaluator-optimizer?</summary>A later revision can be worse. Without retention, a good early answer gets overwritten by a bad final one.</details>
<details><summary>3. On current frontier models, how do you force a router to return one of N labels?</summary>Not with forced <code>tool_choice</code> or prefill, which are rejected. Use structured outputs or <code>strict</code> tools with <code>auto</code>, or use a typed decision model for the classification itself.</details>

## References

- Madaan et al., Self-Refine: https://arxiv.org/abs/2303.17651
