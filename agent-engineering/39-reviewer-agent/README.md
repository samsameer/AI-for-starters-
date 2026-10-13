# 39 · Reviewer Agent: Separate the Builder from the Marker

> **Short answer:** A reviewer agent is a second loop with its own prompt, its own goal and read-only access to everything the builder produced. It scores a written rubric (problem fit, scope, assumptions, verification quality, handoff readiness) and writes a report a human can start from. In 2026 the cheap way to run it is a cascade: a System One `score` question rejects or passes the obvious cases in milliseconds, and only the uncertain ones reach the LLM reviewer. Add it right after the verification gate (Lesson 38), before human sign-off.

**Type:** Build · **Languages:** Python (stdlib) · **Time:** ~55 min

---

## 1. The problem

The gate from Lesson 38 says `passed: true`. Acceptance ran, scope held, coverage is fine. You merge. Two days later you learn the fix solved the wrong half of the bug.

Acceptance is necessary but not sufficient. A gate checks facts. It cannot ask:

- Did this solve the *stated* problem or a nearby, easier one?
- Did scope grow without anyone deciding it should?
- Which assumptions were silently baked into the code?
- Does the acceptance command prove the goal, or a weaker version of it?
- Can the next session pick this up without archaeology?

And the builder cannot answer them about itself. It has the same blind spots that produced the diff, and it has every incentive to read its own work kindly.

## 2. The concept

```
 builder ──► diff + agent_state + feedback + gate verdict   (read-only)
                              │
                              ▼
               gate green? ── no ──► refuse to review
                              │ yes
                              ▼
        System One first pass: 5 × `score` questions (one call)
          │                     │                         │
   any dim < 0.5 with      total ≥ 8.5 and all       anything else
   confidence ≥ 0.8        confidence ≥ 0.75
          │                     │                         │
      hard_fail            fast pass ── every Nth ──► LLM reviewer (rubric + citations)
                                                          │
                                                          ▼
                                     outputs/review/<task>.json ──► human sign-off
```

### The rubric

| Dimension | 0 | 1 | 2 |
|---|---|---|---|
| Problem fit | solves a different problem | partly solves it | solves the stated task |
| Scope discipline | forbidden paths edited | off-scope edits | inside the contract |
| Assumptions | contradicted by the diff | none recorded | recorded and reviewable |
| Verification quality | no trustworthy evidence | generic checks only | focused check proves the goal |
| Handoff readiness | no next action | task left open | closed with a next action |

Total out of 10. **Pass** at 7 or more with no zeros, **soft fail** at 5–6, **hard fail** below 5 or with any zero. Every anchor is written down. "Score 0 to 2" without anchors turns into vibes.

### Four rules that make the gap real

1. **Different role, not necessarily a different model.** Same model is fine. Same system prompt is not. The change in posture is the change in signal.
2. **Read-only.** The reviewer writes a report, never a patch. If it says "fix this", the next builder turn fixes it.
3. **Gate first.** If the verification report is missing or red, the reviewer refuses. Judgment on unverified work is wasted spend.
4. **Cite or it didn't happen.** Every score points at an artifact: a file, a trace entry, a line of state.

### Gate vs reviewer

| | Verification gate (L38) | Reviewer (this lesson) |
|---|---|---|
| Question | Did it work? | Was it the right work, done well? |
| Method | Deterministic code over artifacts | Rubric judgment (System One, then LLM) |
| Can be persuaded | No | Yes, so calibrate it |
| Decides `passed` | Yes | No; it decides pass / soft / hard fail of the review |

## 3. What changed by Oct 2026

- **Typed decision models make a cheap first pass practical.** Jev (TypeSafe AI, Sep 2026) and Cloudflare Clef / Clef-flash (Oct 2026, open weights, Jev-API compatible) answer `score` questions with a probability for every rubric level in one forward pass, typically in tens to hundreds of milliseconds. The rubric anchors *are* the `criteria` list. OpenAI's Decisions API (public beta, Oct 2026) offers the same score/choice/predicate shapes.
- **Rubric graders became platform features.** Hosted agent platforms ship "outcome" graders with a rubric, and LangChain Deep Agents 0.7 has `RubricMiddleware`. They sit on the reviewer side of the line, never in the gate.
- **Review at scale has public receipts.** Cloudflare described (Apr 2026) an AI code review system with up to seven specialist reviewers under a coordinator that de-duplicates findings, with cheaper models on specialists and the strongest model only on the coordinator.
- **Judge bias is a design input.** Position, verbosity, self-preference and authority biases in LLM judges are well documented (see Zheng et al. 2023 and later rubric studies). Mitigations are now standard practice: both orderings, short scales that reward concision, rotating judge families, stripping author names.
- **Subagents and handoffs are first-class in every agent SDK** (OpenAI Agents SDK handoffs, Google ADK 2.x workflow nodes, Microsoft Agent Framework 1.x, coding-agent CLIs with subagents). Running a reviewer role costs one config block.

## 4. Build it

`code/main.py` contains:

- `RUBRIC`: five dimensions with a question and three anchors each.
- `ReviewerInputs`: a **frozen** dataclass. The demo shows a reviewer write attempt being rejected.
- `LocalSystemOne.system_one()`: a deterministic stand-in that returns the System One response shape (`score`, `confidence`, `legend`, `probabilities`, `usage`) for five `score` questions.
- `ReviewerAgent.review()`: refuse if the gate is red, otherwise run the cascade. Thresholds live in code: fast reject, fast pass with every 3rd pass audited by the LLM, escalate the rest.
- `StubLlmReviewer`: integer rubric scores plus a citation per dimension. It also catches one thing the first pass cannot, an assumption that the diff contradicts.
- A nine-case calibration set with human-labelled verdicts, an agreement rate, and a cost comparison against "LLM on everything".

```bash
python3 code/main.py
```

What to look for:

- T-102 (docs-only diff for a code task) and T-103 (forbidden write) are rejected by System One for 1 cost unit each.
- T-107 was a confident fast pass, but it was the audit sample. The LLM found "ascii passwords only" contradicted by a diff that normalizes Unicode. That is why you audit fast passes.
- T-104 is the one disagreement. The human said soft fail. The rubric says 8/10 pass with only generic `pytest` evidence and no recorded assumptions. This is what calibration is for: tighten the verification anchor or the pass bar before shipping.
- T-109 is never reviewed, because its gate is red.
- The cascade costs about 62% less than sending every case to the LLM, in this toy cost model.

## 5. Use it in production

| Piece | Oct 2026 options |
|---|---|
| First-pass `score` | Jev (`typesafe-sdk`, `system_one`), Clef / Clef-flash on Workers AI, OpenAI Decisions API, Pydantic AI `DecisionModel` (an `IntEnum` field becomes a score question), Vercel AI SDK v7 `experimental_decide` |
| Escalation to LLM | Pydantic AI `FallbackModel(decision_model, llm)` hands off undecidable fields; otherwise route in your own code |
| Reviewer role | Subagent with its own prompt and read-only tools in your coding-agent CLI; OpenAI Agents SDK handoff from builder to reviewer; an ADK 2.x workflow node |
| Report delivery | CI job posts `outputs/review/<task>.json` as a PR comment; background agents' draft PRs wait on it |
| Calibration | Pydantic Evals, LangSmith, Braintrust or Arize Phoenix datasets of historical close-outs with human verdicts |

## 6. Architect's lens

1. **Thresholds belong to code, not to the model.** System One returns probabilities. Your code decides what 0.8 means. Version the thresholds next to the rubric and re-run calibration whenever either changes.
2. **Audit the fast path or it will rot.** A cascade that never checks its own fast passes cannot detect drift. Sample every Nth pass (or a fixed percentage) into the LLM reviewer and track disagreement.
3. **Specialists beat one big reviewer once the repo has distinct risk surfaces.** Security, performance and docs reviewers with small prompts, plus a coordinator that de-duplicates findings. Put the expensive model on the coordinator only.
4. **Metrics:** agreement with human verdicts (target ≥ 80% before shipping a rubric change), escalation rate, audit disagreement rate, cost per review, and *escape rate*: reviewed-pass work later reverted.
5. **Failure mode: the reviewer becomes a second builder.** If reports start carrying patches, the gap is gone. Enforce read-only at the tool layer, not only in the prompt.

## 7. Exercises

1. Add a sixth, domain-specific dimension (for example "migration safety"). Defend why the other five do not already cover it.
2. Fix the T-104 disagreement two ways: change the anchor text, then change the pass bar. Which change moves fewer other verdicts?
3. Add a confidence floor: refuse to emit a verdict when the weakest dimension's confidence is below 0.6, and surface that dimension to a human.
4. Add a "request more evidence" action that asks the builder for one focused test run before scoring. Cap it at one round so it cannot loop.
5. Swap `LocalSystemOne` for a real Jev or Clef call (Lessons 55–56). Measure latency and agreement on twenty real close-outs.

## 8. Key terms

| Term | Meaning |
|---|---|
| Reviewer agent | Separate read-only role that scores builder artifacts against a written rubric |
| Anchor | Written description of what each score level means |
| Cascade | Cheap System One first pass, LLM only for the uncertain or sampled cases |
| Audit sample | Fast passes deliberately re-reviewed by the LLM to detect drift |
| Calibration set | Historical close-outs with known verdicts, re-run on every rubric change |
| Hard fail | Total below 5 or any dimension at 0; halt and surface to a human |

## 9. Quick check

<details><summary>1. Why can the reviewer use the same model as the builder?</summary>The signal comes from role separation: a different prompt, different inputs, a different goal and no write access. Using the same prompt would collapse the gap, but using the same weights does not.</details>
<details><summary>2. Why does the reviewer refuse when the gate is red?</summary>Judgment on work that has not met its acceptance facts is wasted spend, and it invites the reviewer to argue with deterministic evidence. Fix the facts first.</details>
<details><summary>3. A System One score is 1.4 with confidence 0.55 on "verification quality". What happens?</summary>Neither the fast-reject nor the fast-pass rule fires, so the case escalates to the LLM reviewer. A mid-range score with low confidence is exactly the abstain signal the cascade is built around.</details>

## References

- Zhuge et al., "Agent-as-a-Judge: Evaluate Agents with Agents", arXiv:2410.10934: https://arxiv.org/abs/2410.10934
- Zheng et al., "Judging LLM-as-a-Judge with MT-Bench and Chatbot Arena", arXiv:2306.05685: https://arxiv.org/abs/2306.05685
- Cloudflare, Orchestrating AI Code Review at Scale: https://blog.cloudflare.com/ai-code-review/
- Cloudflare Clef launch changelog: https://developers.cloudflare.com/changelog/post/2026-10-01-clef-workers-ai/
- Pydantic AI decision models: https://pydantic.dev/docs/ai/models/decision/
- OpenAI Agents SDK handoffs: https://openai.github.io/openai-agents-python/handoffs/
- LangChain, How to calibrate LLM-as-a-judge with human corrections: https://www.langchain.com/articles/llm-as-a-judge
