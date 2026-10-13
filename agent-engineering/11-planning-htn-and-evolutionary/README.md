# 11 · Planning with HTN and Evolutionary Search

> **Short answer:** Use a **Hierarchical Task Network (HTN)** when a plan must be correct by construction: the LLM may suggest decompositions, but a symbolic schema accepts or rejects them (ChatHTN). Use **evolutionary search** when the goal is the *best* program and you have a machine-checkable fitness function: LLMs mutate code and a deterministic evaluator selects (AlphaEvolve). Both treat the LLM as an amplifier, not the authority. Most agent tasks need neither, so start with ReAct or plan-and-execute (Lessons 01–02).

**Type:** Build · **Languages:** Python (stdlib) · **Time:** ~75 min

## 1. The problem

ReAct, ReWOO and plan-and-execute handle most agent planning. They are weak in two places:

1. **Plans that must be sound.** Change management, scheduling, compliance workflows. A fluent plan that skips "request approval" one time in fifty is a production incident.
2. **Optimization with a scorer.** Kernels, heuristics, compiler passes. You don't want *a* correct answer here, you want a *better* one than you have.

These are different problems with different tools. What they share is that **correctness or quality is decided by something other than the LLM**.

## 2. The concept

### HTN in one table

| Element | Meaning | Example |
|---|---|---|
| Primitive task (operator) | Directly executable, with preconditions and effects | `open_pr`: needs `tests_green` and `approved`, adds `pr_open` |
| Compound task | Must be decomposed | `ship_change` |
| Method | One way to decompose a compound task, guarded by preconditions | `hotfix_path` applies only if `incident_declared` |
| State | A set of facts | `{repo_cloned, branch_open}` |

Planning means finding a decomposition into operators whose preconditions hold in sequence. HTNs predate LLMs and are still the reference for policy-bound plans, because **policy is encoded in preconditions**.

### ChatHTN: LLM as method author, not plan author

ChatHTN (Gopalakrishnan et al., arXiv:2505.11814) adds one move to classic HTN search:

```
 compound task ──► existing method applies? ── yes ──► recurse
                         │ no
                         ▼
                 ask LLM for decompositions
                         │
              validate every subtask against schema ── reject unknown / unsatisfiable
                         │ ok
                         ▼
                 recurse, then cache as a learned method
```

The LLM's suggestions enter only as *candidate* methods. The symbolic layer still checks every precondition, so every plan that comes out is sound with respect to the operator schema. Follow-up work on online method learning generalizes cached LLM decompositions so the LLM is consulted less over time.

### AlphaEvolve: LLM as mutation operator

AlphaEvolve (Novikov et al., arXiv:2506.13131, Google DeepMind, 2025) runs an evolutionary loop over code:

```
 seed program ─► LLM ensemble proposes diffs ─► evaluator scores ─► keep best ─► repeat
```

Its published results include a 4×4 complex matrix multiplication with 48 scalar multiplications and a Borg scheduling heuristic that recovered about 0.7% of Google's fleet compute. The hard constraint is that **the fitness function must be programmatic, fast and deterministic**. "Ask an LLM whether this is better" is not a fitness function, and search over prose does not converge.

### Choosing

| Problem | Reach for | Why |
|---|---|---|
| Multi-step tool use, open-ended | ReAct / plan-and-execute | Flexible, cheap to build |
| Policy-bound workflow (approvals, change control) | HTN + LLM fallback | Preconditions encode policy |
| Improve code that has tests or a benchmark | Evolutionary search | Tests are the evaluator |
| Scheduling with hard constraints | HTN or a constraint solver | Soundness by construction |

## 3. What changed by Oct 2026

- **Planner-as-tool is the common shape.** The 2026 frameworks still don't ship first-class HTN. Teams wrap a planner as a tool or as a graph node: a LangGraph 1.2 node, an ADK 2.x workflow node, or an agent SDK subagent.
- **ADK 2.0 (GA May 2026)** added a graph-based workflow engine that mixes deterministic and model-led nodes. That is a natural place to host "symbolic first, LLM fallback".
- **Evolutionary coding moved from papers to practice.** Open-source AlphaEvolve-style loops are common, and long-running agents in sandboxes (Cloudflare Sandboxes, LangSmith Sandboxes, OpenAI Agents SDK sandbox agents) make "run 1,000 candidates against the test suite" operationally cheap.
- **Harness engineering** (planner/generator/evaluator splits in the 2026 harness-engineering posts) is the same idea at the agent level: separate the proposer from the judge, and make the judge as mechanical as possible.
- **Benchmark caution.** A 2026 UC Berkeley RDI study showed automated agents reward-hacking major agent benchmarks. Evolutionary search is the most effective reward hacker you will ever build, so harden the evaluator first.

## 4. Build it

`code/main.py` contains two demos:

- **HTN planner**: operators with preconditions and effects, prioritized methods, depth limit and backtracking across methods. When no method applies, a `ScriptedLLM` proposes three decompositions. One uses an unknown task (`deploy_to_prod`) and is rejected. One skips approval and is rejected as unsatisfiable. The third is accepted and **cached** as a learned method.
- **Evolutionary search**: evolves integer coefficients `(a, b, c)` toward `2x² − 3x + 5`, using mutation, crossover, elitism and a deterministic absolute-error evaluator with a seeded RNG.

```bash
python3 code/main.py
```

Look for: case B choosing `hotfix_merge` only because `incident_declared` holds, case D making **0 new LLM calls** because the learned method is reused, and the evolution reaching `error=0`.

## 5. Use it in production

- **HTN libraries:** `pyhop`/GTPyhop and SHOP3, or a small custom planner. Domain-specific planners are usually under 300 lines.
- **Hosting:** expose the planner as a tool (`plan(goal, state) -> steps`) behind MCP, or as a deterministic node in LangGraph 1.2.x or ADK 2.x.
- **LLM fallback models:** any strong model. With current frontier models, use structured outputs for the decomposition list rather than forced `tool_choice`, which those models reject.
- **Evolutionary loops:** run in sandboxes with resource limits. Evaluators should be hermetic, seeded and time-boxed.

## 6. Architect's lens

1. **Put the authority in the schema.** The value of ChatHTN is not the LLM, it is the validator. If your operators lack honest preconditions, you have an expensive plan-and-execute with extra steps.
2. **Learned methods are code you didn't review.** Persist cached decompositions with provenance (which model, which state) and put them through the same review gate as hand-written methods.
3. **Evaluator cost dominates evolution.** Budget it as candidates × evaluator seconds. A 30-second test suite and 2,000 candidates is about 17 compute-hours. Cache by program hash.
4. **Guard against Goodhart.** Hold out tests the search never sees, and re-check winners on them before you accept a result.
5. **2026 update, cheap pre-filter.** A System One decision model (Jev or Clef, Lessons 55–56) can triage LLM-proposed decompositions or mutations with a `noul` such as "does this obviously violate policy?" before the expensive symbolic or test check. It filters candidates. It never replaces the evaluator.

## 7. Exercises

1. Add effect checks at execution time. If an operator's effect doesn't appear in the observed state, backtrack to the next method.
2. Generalize learned methods: cache by `(task, relevant facts)` instead of by task alone, and show a case where the plain cache is wrong.
3. Evolve a sort function, scored by the number of passing tests out of 20. Report generations to convergence and how often a hacked solution passed.
4. Add a holdout evaluator and reject winners whose holdout error is more than twice their training error.
5. Wrap the HTN planner as a tool an agent loop can call, and measure how often the agent's free-form plan disagrees with it.

## 8. Key terms

| Term | Meaning |
|---|---|
| HTN | A planner that decomposes compound tasks via methods into operators with preconditions and effects |
| Method | A guarded rule that decomposes one compound task into subtasks |
| Operator | A primitive action with preconditions and effects |
| ChatHTN | HTN search that asks an LLM for decompositions when no method applies, then validates them |
| Fitness function | A deterministic, machine-checkable score for a candidate program |
| AlphaEvolve | LLM-proposed code mutations selected by an automated evaluator |
| Reward hacking | Search exploiting gaps in the evaluator instead of solving the task |

## 9. Quick check

<details><summary>1. Why are ChatHTN plans sound even though an LLM helps produce them?</summary>The LLM only proposes candidate decompositions. Every resulting operator sequence is still checked against preconditions and effects, and invalid proposals are rejected.</details>
<details><summary>2. Why can't you run AlphaEvolve on "write a better product description"?</summary>There is no deterministic, fast fitness function, so selection pressure is noise and the search cannot converge.</details>
<details><summary>3. Your agent mostly calls three APIs in a variable order. HTN or ReAct?</summary>ReAct (or plan-and-execute). HTN earns its cost only when policy or correctness must be enforced by construction.</details>

## References

- Gopalakrishnan et al., ChatHTN: https://arxiv.org/abs/2505.11814
- Novikov et al., AlphaEvolve: https://arxiv.org/abs/2506.13131
- GTPyhop (Nau's HTN planner in Python): https://github.com/dananau/GTPyhop
- Google ADK docs: https://google.github.io/adk-docs/
