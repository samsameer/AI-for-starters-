# 05 · Self-Refine and CRITIC: Iterative Output Improvement

> **Short answer:** Self-Refine runs one model in three roles: generate a draft, critique it, rewrite it with the full history of earlier critiques, and repeat. CRITIC keeps the loop but grounds the critique in tools (a calculator, a lookup, tests, a linter), because a model checking its own facts tends to approve them. In production this is the evaluator-optimizer loop: generate, verify externally where you can, refine, and stop when a verifier passes or a budget runs out.

**Type:** Build · **Languages:** Python (stdlib) · **Time:** ~60 min

---

## 1. The problem

Most agent outputs are nearly right. A bullet is too long, a percentage is off, a region name is wrong, a test fails on an edge case. The natural fix is to have the agent review its own work and try again.

Self-Refine (Madaan et al., NeurIPS 2023, arXiv:2303.17651) showed that this works with a single model and no training: the paper reports an average improvement of about 20 absolute points across seven tasks. CRITIC (Gou et al., ICLR 2024, arXiv:2305.11738) found the weak spot. A model is poor at verifying hard facts it has just produced, because a hallucination looks convincing to the model that wrote it. CRITIC's fix is to send verification through external tools.

## 2. The concept

### Self-Refine: one model, three roles

```
draft_0    = generate(task)
critique_0 = feedback(task, draft_0)
draft_1    = refine(task, draft_0, critique_0, history)
critique_1 = feedback(task, draft_1)
...        stop when feedback finds nothing, or the budget is spent
```

The `history` argument matters. The refiner must see every earlier draft and critique, or it will happily undo yesterday's fix while making today's. The paper's ablation shows quality drops without it, and the demo makes the failure visible.

### CRITIC: ground the critique

```
             ┌──────────────── refine with history ◄────────────┐
             ▼                                                   │
 task ─► generate ─► draft ─► verify(draft, tools) ── issues ────┘
                                     │
                                   pass ─► ship
 tools: format linter · calculator · record lookup · tests · search
```

| Check | Self-critique | Tool-grounded |
|---|---|---|
| Style, tone, length | Decent | A linter is exact |
| Arithmetic | Often approves plausible numbers | Calculator is exact |
| Facts from a record | Approves what it just wrote | Lookup is exact |
| Code correctness | Weak | Tests or a type checker |
| Open-ended quality | Only option | Rubric judge, ideally a different model |

Where no tool exists (creative writing, tone), CRITIC falls back to Self-Refine. Do not pay for a stub verifier.

### Stop conditions

Never rely on a single condition. A robust policy is: stop when the grounded verifier passes; or when the self-critic is satisfied *and* at least two rounds ran; or when you hit the round cap; or when a draft repeats (oscillation). On the last three, escalate instead of shipping silently.

### Common failures

- **Rubber stamping:** the same model with the same framing says "looks good". Use structurally different prompts, or a different model, for the critic.
- **Over-refinement:** every round adds latency and tokens. One to three rounds is typical; after that, escalate.
- **Oscillation:** a refiner without history flips between two broken drafts.

## 3. What changed by Oct 2026

- **The loop has a standard name and packaging.** "Evaluator-optimizer" is one of the canonical workflow patterns (Lesson 12). LangChain Deep Agents 0.7 ships `RubricMiddleware`, and hosted agent platforms let you attach an outcome rubric and a grader to a run.
- **Guardrails got stricter.** The OpenAI Agents SDK's output guardrails are CRITIC-shaped validators; v0.22 tightened how guardrail trips and failed responses are handled, and v0.20 added retry policies.
- **Structured outputs replaced "please return JSON".** Current frontier models removed assistant prefill and several reject forced tool choice, so the refine step should use a structured-output schema (`strict: true` or a response format) and a schema validator acts as a free first verifier.
- **Verifiers run in sandboxes.** Tests and code checks now run in managed sandboxes (Cloudflare Sandboxes GA, LangSmith Sandboxes, OpenAI Sandbox agents), so "run the tests" is a cheap, safe critique tool.
- **Effort is a lever.** Running the generator at a higher reasoning effort sometimes removes the need for a refine round. Measure both on your eval set.
- **2026 update, System One critic and stop gate:** many critiques are typed questions: "does this bullet state a number not in the source?" (`noul`), "how well does this answer the question?" (`score`). A decision model (Jev or Clef, Lessons 55–56) answers them with calibrated probabilities in tens of milliseconds, so you can run the critic every round and keep the "good enough to stop?" threshold in code.

## 4. Build it

`code/main.py` asks for three bullets of at most 60 characters summarizing a quarter, using a small source-of-truth record. The first draft has four bullets, one over-long line, a wrong growth figure (17% instead of 20%) and the wrong top region.

- `self_critic`: a lenient same-model critic. It notices bullet count but not facts, and lets a 62-character line through.
- `critic_with_tools`: a fail-fast pipeline of `format_tool`, `calculator_tool` and `lookup_tool`. Cheap checks run first.
- `refine`: applies a fix for every issue tag it knows about. With history it accumulates tags; without history it sees only the last critique.
- `run_loop`: the stop policy, including oscillation detection.
- `ground_truth_errors`: an independent audit of what actually shipped.

```bash
python3 code/main.py
```

What to look for: Self-Refine stops after two rounds and ships three errors. CRITIC with history needs four rounds (format, then arithmetic, then the lookup) and ships clean. CRITIC without history fixes the format, then reintroduces it while fixing the number, and the oscillation detector stops it with two errors still present.

## 5. Use it in production

- **OpenAI Agents SDK:** output guardrails as the verifier, with tripwires triggering a retry or escalation.
- **LangGraph 1.2:** a generate node, a verify node and a conditional edge back, with a round counter in state.
- **LangChain Deep Agents:** `RubricMiddleware` for rubric grading over long-running tasks.
- **Google ADK 2.x:** a loop node in a graph workflow with an evaluator node. `ModelConsultTool` lets a cheap generator ask a stronger model for critique under a budget.
- **Vercel AI SDK v7:** `ToolLoopAgent` with `isStepCount` as the round cap, and `experimental_decide` to put a typed decision model in the critic seat.
- **Coding agents:** tests, type checkers and linters are the CRITIC tools. Require them to pass before a change is proposed.

## 6. Architect's lens

1. **Ground first, opine second.** Order verifiers by cost: schema, linter, calculator, lookup, tests, then a model judge. Most issues die in the cheap stages.
2. **Different eyes for critique.** Use a different prompt shape, a different model, or a decision model as the critic. A critic that shares the generator's blind spots is decoration.
3. **Treat the stop policy as code.** Record why every loop stopped (`passed`, `cap`, `oscillation`). Alert when the share of capped or oscillating runs rises.
4. **Budget the loop.** Each round costs a generation and a verification. Track rounds per task and cost per accepted output, not just final quality.
5. **Audit independently.** The verifier that steers the loop should not be the only thing that judges the result. Sample shipped outputs against a held-out check.

## 7. Exercises

1. Run each loop with `max_rounds=1`. Which run is still better than the first draft, and why?
2. Make `lookup_tool` noisy: let it miss the region error 30% of the time with a seeded RNG. How often does a wrong region ship over 100 runs?
3. Run all three tools every round instead of fail-fast. Does history still matter? What do you lose in cost?
4. Add a stand-in decision gate that returns `P(bullet contains an unsupported claim)` and only calls the tools when that probability is above 0.3. Count tool calls saved.
5. Add an escalation path: when the loop stops on `cap` or `oscillation`, return a "needs review" result instead of the last draft.

## 8. Key terms

| Term | Meaning |
|---|---|
| Self-Refine | Generate, feedback and refine in one model, with history |
| CRITIC | Self-correction with tool-grounded verification |
| Evaluator-optimizer | Workflow pattern: one role scores, another revises, loop until pass |
| Output guardrail | A validator that runs on an agent's final output and can reject it |
| Refine history | Earlier drafts and critiques given to the refiner |
| Rubber stamping | A critic that approves because it shares the generator's view |
| Oscillation | A loop flipping between drafts because fixes are forgotten |

## 9. Quick check

<details><summary>1. Why did Self-Refine ship a wrong growth rate?</summary>Its critic was the same model with no tools. A plausible percentage looked fine, so the loop stopped on "no issues" with the error intact.</details>
<details><summary>2. Why does removing refine history cause oscillation?</summary>The refiner applies only the latest critique, so fixing the number re-creates the format error that an earlier round had fixed, and the loop keeps alternating.</details>
<details><summary>3. When does CRITIC reduce to Self-Refine?</summary>When no external verifier exists for the property you care about, for example tone or creativity. Then the critique is a model judgment either way.</details>

## References

- Madaan et al., Self-Refine (arXiv:2303.17651): https://arxiv.org/abs/2303.17651
- Gou et al., CRITIC (arXiv:2305.11738): https://arxiv.org/abs/2305.11738
- Huang et al., Large Language Models Cannot Self-Correct Reasoning Yet (arXiv:2310.01798): https://arxiv.org/abs/2310.01798
- OpenAI Agents SDK, guardrails: https://openai.github.io/openai-agents-python/guardrails/
- LangGraph docs: https://docs.langchain.com/oss/python/langgraph/overview
- Vercel AI SDK: https://ai-sdk.dev/docs
