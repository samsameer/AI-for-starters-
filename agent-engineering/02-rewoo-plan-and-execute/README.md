# 02 · ReWOO and Plan-and-Execute: Decoupled Planning

> **Short answer:** ReAct thinks and acts in one interleaved stream. ReWOO plans the whole job first as a DAG with placeholders (`#E1`, `#E2`), runs the tool calls (in parallel where possible), and then makes one solver call to compose the answer. You get fewer model calls, clearer failure points and a planner you can swap for a cheaper model. Use it when the tools are known and the task is structured. Stay with ReAct when the environment keeps surprising you.

**Type:** Build · **Languages:** Python (stdlib) · **Time:** ~60 min

---

## 1. The problem

In a ReAct loop, every model call re-reads the full history: every earlier thought, call and observation. Prompt size grows with depth, and so do latency and cost. When step 6 fails, the model has to reason its way out of the error mid-stream, and the original plan exists only implicitly.

ReWOO ("Reasoning WithOut Observation", Xu et al., arXiv:2305.18323) makes a different bet. Plan everything up front without seeing any observations, fetch the evidence, then solve. You give up adaptivity and gain efficiency, parallelism and a plan you can inspect before anything runs.

## 2. The concept

### Three roles

```
Planner : question                         -> plan DAG   (1 model call)
Workers : plan DAG                         -> evidence   (tool calls only, parallel per layer)
Solver  : question + plan + evidence       -> answer     (1 model call)
```

```
 E1 search(capital of France)    E2 search(capital of Germany)       layer 1
            │                                │
 E3 search(population of #E1)    E4 search(population of #E2)        layer 2
            │                                │
 E5 round(#E3)                   E6 round(#E4)                       layer 3
             └──────────────┬───────────────┘
                     E7 compare(#E5, #E6)                            layer 4
```

### Why it is cheaper

The paper reports about 5x fewer tokens than ReAct on HotpotQA together with a small accuracy gain. Workers are tool calls, not model calls, so the model is invoked twice no matter how many steps the plan has.

### Why it fails more cleanly

If E3 fails, its dependants are skipped and the solver sees exactly which node broke. Failures are local to a node, not smeared across a transcript.

### Planner distillation

Because the planner never sees observations, its outputs are easy to collect and train on. The paper fine-tuned a small model on plans from a large one. The production version of this idea is "strong planner, cheap workers" or the reverse, chosen per task.

### The family

| Pattern | Replans? | Best for |
|---|---|---|
| ReAct (Lesson 01) | Every step | Short tasks, unknown environments |
| ReWOO | Never | Structured tasks with known tools, parallelizable evidence |
| Plan-and-Execute (LangChain, 2023) | After failures or checkpoints | ReWOO's savings with a recovery path |
| Plan-and-Act (Erdogan et al., arXiv:2503.09572) | Planner trained on synthetic plans | Long-horizon web and computer-use tasks |
| Tree search (Lesson 04) | Explores alternatives | When search is worth the token multiplier |

## 3. What changed by Oct 2026

- **Programmatic tool calling is ReWOO's descendant.** Instead of a DAG of JSON steps, the model writes a short program that calls your tools. Intermediate results stay inside the sandbox and only the final output enters the context. Frontier providers ship this as a code-execution tool that is allowed to call your custom tools. OpenAI's Agents SDK added a Programmatic Tool Calling tool, and Cloudflare calls the idea Code Mode.
- **Graph engines made the plan a first-class object.** Google ADK 2.0 (GA May 2026) has a graph-based workflow engine that mixes deterministic and model-led nodes. LangGraph 1.2 added per-node timeouts. Vercel's `WorkflowAgent` makes each tool call a durable step.
- **Plans now fan out across agents.** Coding agents' dynamic workflows and hosted agent platforms' multiagent rosters let a coordinator plan once and hand the pieces to many sub-agents. That is ReWOO's planner/worker split at the agent level.
- **Prompt caching changes the arithmetic.** A cached ReAct prefix is much cheaper to re-read than it was in 2023, so the token gap is smaller than the paper's number. Latency and parallelism are still real wins. Measure on your own traffic.
- **Effort is a planner knob.** Run the planner at `high` effort on a strong model (a flagship frontier model) and the solver or workers at `low`, or on a small, fast model.
- **2026 update, System One replan trigger:** "Is the gathered evidence enough to answer?" is a `noul` question. A decision model (Jev or Clef, Lessons 55–56) can make that call between execute and solve, so the expensive replanner runs only when it is needed.

## 4. Build it

`code/main.py` contains:

- `Step` and `Plan`, with `#En` references parsed into dependencies.
- `validate_plan`: unknown tools, dangling references and self-references are rejected before any tool runs.
- `levels`: a topological layering, so each layer runs in parallel through a `ThreadPoolExecutor`.
- Failure propagation: a step whose dependency failed is skipped with a clear error instead of being called with garbage.
- `react_cost`: toy accounting of how many characters ReAct would send across 8 model calls, compared with ReWOO's 2.
- `plan_and_execute`: a replanner that repairs a typo'd query after the first round fails.

```bash
python3 code/main.py
```

Look for the four execution layers, the roughly 4x prompt-size gap on this toy (character counts, not real tokens), the two rejected plan errors, and the replanner recovering in round 2.

## 5. Use it in production

- **Provider APIs:** programmatic tool calling for "call many tools, return one summary" jobs. Use a plain call with structured outputs when you want a JSON plan you validate yourself.
- **LangGraph 1.2:** plan-and-execute as an explicit graph with a replanner node and checkpoints.
- **Google ADK 2.x:** graph workflows with tool-confirmation nodes for human approval.
- **CrewAI Flows / Microsoft Agent Framework workflows:** predefined task graphs when the plan is known at design time.
- **Durable runners** (Temporal, Vercel Workflows, Restate): make each worker step resumable so a crash at layer 3 does not redo layers 1 and 2.

## 6. Architect's lens

1. **Validate the plan like code.** Check for a DAG, resolved references, known tools and argument types before execution. A bad plan caught at validation costs one model call. Caught at the solver, it costs the whole run.
2. **A static plan is a liability in open environments.** If observations routinely change what should happen next, ReWOO will execute stale intentions. Use a replanner, or fall back to ReAct.
3. **Parallelism has a blast radius.** Rate limits, ordering and partial failure all show up at once. Cap concurrency per tool and make writes idempotent.
4. **Plans are good telemetry.** Log the plan, the layer timings and the failed nodes. Plan-shape drift is an early warning that tools or prompts changed.
5. **Keep the solver honest.** Tell it which nodes failed. A solver that only sees successful evidence will confidently paper over the gaps.

## 7. Exercises

1. Add a `max_parallel` setting per tool (for example `search` = 2) and show the layer schedule still holds.
2. Add a replanner trigger that fires when any node fails *or* the solver reports missing evidence. What is the minimum change that turns ReWOO into Plan-and-Execute?
3. Rewrite the plan as a Python function that calls the tools directly (the programmatic tool-calling shape). What did you gain, and what can you no longer validate statically?
4. Re-run the cost comparison assuming 90% of ReAct's history is a cache hit billed at 10%. How big is the gap now?
5. Add an "is the evidence sufficient?" `noul` gate before the solver using Lesson 55's local stand-in.

## 8. Key terms

| Term | Meaning |
|---|---|
| ReWOO | Plan without observations, gather evidence, then solve |
| Evidence reference | A placeholder like `#E2` replaced with an earlier step's output |
| Layer | A set of plan steps whose dependencies are all satisfied, so they can run in parallel |
| Replanner | A model call that revises the plan after seeing failures |
| Programmatic tool calling | The model writes code that calls tools, so intermediate results skip the context |
| Planner distillation | Training a small planner on a large model's plans |

## 9. Quick check

<details><summary>1. Why can ReWOO's workers run in parallel and ReAct's steps usually cannot?</summary>The full dependency graph is known before execution, so independent nodes can run together. ReAct decides each step after seeing the previous observation.</details>
<details><summary>2. When does ReWOO lose to ReAct?</summary>When the environment is unknown or observations change what the right next step is. A static plan then executes wrong intentions.</details>
<details><summary>3. Does prompt caching remove ReWOO's advantage?</summary>It narrows the token-cost gap, but ReWOO still makes fewer model calls, parallelizes evidence and gives you a plan you can validate up front.</details>

## References

- Xu et al., ReWOO (arXiv:2305.18323): https://arxiv.org/abs/2305.18323
- Erdogan et al., Plan-and-Act (arXiv:2503.09572): https://arxiv.org/abs/2503.09572
- LangGraph docs: https://docs.langchain.com/oss/python/langgraph/overview
- Google ADK: https://google.github.io/adk-docs/
