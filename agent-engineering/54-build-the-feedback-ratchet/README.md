# 54 · Build a Feedback Ratchet with Ownership and Retirement

> **Short answer:** Shipping closes the build loop and opens the learning loop. A feedback ratchet routes every signal (incident, eval failure, trace, user complaint, human override) to the layer that owns its cause: eval, context, policy, runtime, backlog or the decision dataset. Each route becomes an owned, verified action with a review date and a retirement condition. Human corrections of System One verdicts become **labeled data**. A deterministic split sends part of it to the eval holdout and the rest to a training pool, which can feed RL fine-tuning (for example Cloudflare's Clef service) only after that pool is gated.

**Type:** Learn + Build · **Languages:** Python (stdlib) · **Time:** ~75 min

---

## 1. The problem

Teams collect traces, eval scores, tickets and incident reports and still don't learn from them, because nothing *promotes* an observation into a change. The telemetry exists, but the mechanism doesn't.

With decision models there is a second waste. Every time a support lead re-routes a ticket the router got wrong, they are labeling data for free. Without a ratchet that label disappears into a queue UI, and the router makes the same mistake tomorrow.

## 2. The concept

### The loop

```
signal ─► outcome / constraint it touches ─► root cause ─► owning layer ─► durable change
   ▲                                                                           │
   └──────────── next run ◄──────────── verification ◄────────────────────────┘
```

### Route to the owning layer

| Signal | Layer | Artifact |
|---|---|---|
| Human override of a router or guard verdict | **Decision dataset** | `datasets/decisions/*.jsonl` (eval holdout + training pool) |
| False positive, regression, wrong result | Evaluation | `evals/cases/` |
| Stale fact, missing context, duplicate work | Context | Retrieval sources, AGENTS.md |
| Unsafe action, authority gap | Policy | Permission policy, hooks |
| Timeout, retry storm, unavailable dependency | Runtime | Timeouts, retries, circuit breakers |
| New need, unresolved trade-off | Backlog | Shaped item with outcome and owner |

Don't add a prompt paragraph when a test, a permission rule or a labeled row can make the failure impossible.

### Every action is owned

Each action has one owner, a priority (`severity × frequency`, with severity-5 incidents fast-tracked), the artifact to change, its verification, a review date and a retirement condition. An unowned improvement is just an observation with better formatting.

### Corrections → labeled data → evals → (maybe) fine-tuning

```
override ─► (state, question, labels, model_choice, p, human_choice)
                 │ fingerprint + dedupe
                 ▼
         hash split (stable per row)
          ├─ 30% ─► EVAL HOLDOUT  {state, question, expected}       ─► threshold re-pick, regression gate
          └─ 70% ─► TRAIN POOL    {state, question, rewards{label}} ─► RL fine-tune, once gated
```

- **Hash-based split:** a row always lands in the same bucket, so retraining can never leak into the holdout.
- **Reward shape:** +1 for the human's label, −1 for the label the model wrongly chose, 0 for the rest. Confident mistakes (p ≥ 0.8) are flagged because they matter most for calibration.
- **Fine-tune gate:** no training until the holdout is large enough to judge the result, and a tuned model is accepted only if it beats the base model on the holdout. Before that point, the cheaper fix is to re-pick the threshold.

### Retire stale controls

Review a control when the architecture changes, when a lower-layer control replaces it, when the failure stays absent across the window, or when it blocks more legitimate work than the harm it prevents. Retiring also needs evidence.

## 3. What changed by Oct 2026

- **Decision models can be improved by fine-tuning on your own corrections.** Cloudflare announced an RL fine-tuning service for Clef at launch (design partners first, self-serve later), and Clef's weights are Apache-2.0, so self-hosted tuning is also possible. The exact submission format is the provider's. The lab's JSONL is illustrative.
- **Eval platforms close the loop.** LangSmith (Engine v2, Trajectories), Braintrust ("active observability", where agents query traces and open PRs), Langfuse, Phoenix and AWS AgentCore (failure insights, batch evals) can turn a flagged trace into a dataset row or a draft fix.
- **Hosted agent platforms ship outcome graders and memory stores.** Feedback can now update rubrics and long-term memory, which are both "context" layer destinations that need owners and retirement just like prompts.
- **Same ratchet, two tracks.** Product evidence changes the outcome frame, assumptions, slice and metrics (Lessons 47–53). Coding-agent corrections change tests, scope, automation and handoffs (Lesson 46). Incidents often change both.

## 4. Build it

`code/main.py` runs the ratchet on 17 signals: 12 router overrides (one of them a duplicate) and 5 other signals.

- `route()` picks the layer. Any signal carrying a `DecisionCorrection` goes to `decision_dataset`.
- `to_rows()` builds an eval row (System One `choice` question + expected label) and an RL row (per-label rewards), and assigns the split by hash.
- `ratchet()` dedupes, groups, prioritizes, sets review dates and retirement conditions.
- `fine_tune_gate()` checks holdout leakage and minimum sizes.
- `decision_brief()` drafts the decision request for the accountable owner.

```bash
python3 code/main.py
```

What to look for:

- The severity-5 "agent wrote to the billing DB" incident is fast-tracked to the top and routed to **policy**, not to a prompt.
- The CRM timeout goes to **runtime**, and stale prices go to **context**.
- The 12 overrides collapse to **11 unique rows**: 4 in the eval holdout and 7 in the training pool. The duplicate "card charged twice" is counted once.
- The fine-tune gate reports **ready** under the lab's toy minimums. In production those minimums are hundreds of rows.
- The decision brief asks a named owner to choose between keeping auto mode, assist mode for billing, or stopping, and gives a date.

## 5. Use it in production

- **Capture overrides at the source.** The queue UI, the approval dialog or the PR review should write the correction row directly, with the decision span's trace id.
- **Version the datasets.** Keep JSONL in the repo or in a dataset store, with the split stored per row. Never re-split.
- **Order of fixes for a decision model:** (1) re-pick the threshold on the grown holdout (Lesson 52), (2) improve the question's `instructions` and `criteria`, (3) switch model size (Clef-flash → Clef), and only then (4) fine-tune.
- **Practice lab (do this for real):** take one workflow, run one bounded experiment, and write a one-page decision brief for its owner. Include at least two options (one of them a cheaper manual or no-build option), the trade-offs, your recommendation, the evidence that changed your mind, and the date the decision is needed. Label simulated evidence as simulated.
- **2026 update:** treat every System One verdict as a future label. Log probabilities and route with the decision so overrides can be joined back to them. That join is what makes calibration monitoring, threshold re-picks and Clef fine-tuning possible.

## 6. Architect's lens

1. **The holdout is sacred.** The moment training data leaks into the eval set, every later "improvement" is unverifiable. Hash-based splits make leakage structurally impossible.
2. **Fine-tuning is the last step, not the first.** Thresholds and question wording are cheaper, faster and reversible. Fine-tune only when the eval shows a ceiling that those can't move.
3. **Severity overrides frequency for safety.** A single unauthorized write outranks a hundred misroutes. Encode that in the priority function, not in someone's memory.
4. **Feedback systems accumulate policy debt.** Each control costs context, latency or friction. Review dates and retirement conditions keep the system small.
5. **The decision brief is part of the ratchet.** Evidence that never reaches the accountable owner, with options and a date, doesn't change anything.

## 7. Exercises

1. Turn one real incident and one user complaint into ratchet actions with owners and verification.
2. Add a "rate limit exceeded on search API" signal and confirm it routes to **runtime**.
3. Raise `MIN_EVAL_ROWS` to 50 and explain why the gate's message is the right advice.
4. Change the reward scheme so confident mistakes get −2, and argue for or against it using calibration.
5. Trace one accepted correction back into the next outcome frame (Lesson 47) or spec (Lesson 51).

## 8. Key terms

| Term | Meaning |
|---|---|
| Feedback ratchet | The mechanism that promotes observations into owned, verified, durable changes |
| Owning layer | The earliest layer that controls the cause: eval, context, policy, runtime, backlog, dataset |
| Eval holdout | Labeled rows never used for training. They judge every change |
| Training pool | Labeled rows eligible for fine-tuning after a gate |
| Retirement condition | The evidence that lets a control be removed |

## 9. Quick check

<details><summary>1. Why split by hash instead of randomly at training time?</summary>A stable hash puts each row in the same bucket forever, so no retrain can move a holdout row into training.</details>
<details><summary>2. A router is wrong 6% of the time. Should you fine-tune first?</summary>No. Re-pick the threshold on the grown holdout and refine the question first. Fine-tune when those stop helping and the holdout can judge the result.</details>
<details><summary>3. Where does "agent wrote to production without authority" go?</summary>To the policy layer as a permission or hook, fast-tracked by severity, and verified by replaying the action and watching it get blocked.</details>

## References

- Basili, Caldiera, Rombach, *The Goal Question Metric Approach*: https://www.cs.toronto.edu/~sme/CSC444F/handouts/GQM-paper.pdf
- Fagerholm et al., *Building Blocks for Continuous Experimentation*: https://doi.org/10.1145/2601248.2601276
- Nuseibeh & Easterbrook, *Requirements Engineering: A Roadmap*: https://www.cs.toronto.edu/~sme/papers/2000/ICSE2000.pdf
- Cloudflare Clef launch (RL fine-tuning service): https://developers.cloudflare.com/changelog/post/2026-10-01-clef-workers-ai/
- InfoQ on Clef decision models: https://www.infoq.com/news/2026/10/clef-decision-models/
