# 52 · Design Success Metrics Before the Result Exists

> **Short answer:** Metrics exist to answer a decision, not to fill a dashboard. Start from the goal, derive questions, and pick the fewest metrics that answer them. Each metric needs a direction, a threshold, a window, a source and a population. Pair outcome metrics with guardrails and counter-metrics, and write pass, fail and ambiguous rules *before* you see any data. For System One decisions the core set is **calibration, abstain rate, cost per decision and a cost-matrix threshold**.

**Type:** Learn + Build · **Languages:** Python (stdlib) · **Time:** ~70 min

---

## 1. The problem

Most AI dashboards are built after launch from whatever was easy to log: request counts, latency, thumbs-up rate. When a decision comes ("expand the pilot?"), none of those numbers can answer it, so the team argues from anecdotes. Or someone moves the threshold until the project passes.

Decision models add a specific trap. Accuracy alone tells you almost nothing. A guard that is 97% accurate might be auto-acting on 10% of cases or on 90%. It might be well calibrated, or it might say 0.95 when it is right 80% of the time. Both properties change what you can safely automate.

## 2. The concept

### Goal → Question → Metric (GQM)

```
goal: reduce time to identify the failing service without unsafe actions
  ├─ Q: how fast is the right service identified?      ─► median_identification_seconds  (outcome)
  ├─ Q: when we auto-act, how often are we right?      ─► auto_precision                 (guardrail)
  ├─ Q: can we trust the probabilities?                ─► expected_calibration_error     (guardrail)
  ├─ Q: does diagnosis stay read-only?                 ─► production_writes              (guardrail)
  ├─ Q: how much work lands back on humans?            ─► abstain_rate                   (counter)
  └─ Q: is it worth it?                                ─► cost_per_decision              (counter)
```

### A metric needs a contract

| Field | Example |
|---|---|
| Name | `auto_precision` |
| Kind | outcome, guardrail or counter |
| Direction | at least |
| Threshold | 0.97 (inclusive) |
| Window | 400 replayed alerts, last 90 days |
| Source | Labeled replay set |
| Population | On-call engineers in the pilot rotation |

Without a source and a window, nobody can reproduce the number. Without a threshold, the number can't drive a decision.

### The System One metric set

| Metric | Meaning | Why it matters |
|---|---|---|
| **Calibration (ECE, Brier)** | Does P = 0.9 mean right 90% of the time? | Thresholds only work on calibrated probabilities |
| **Abstain rate** | Share below threshold, sent to a human or System Two | The counter-metric for "automation" that just moves work around |
| **Auto precision / coverage** | Accuracy on the share you act on, and the size of that share | Together they define the product |
| **Cost per decision** | Model cost + expected error cost + human review cost | Model tokens are usually the smallest term |
| **Cost-matrix threshold** | The threshold that minimizes expected cost | Turns a product judgment into arithmetic |

For a calibrated model, the cost-minimizing auto-act threshold is roughly `1 − C_review / C_wrong`. With a wrong action costing $40 and a review costing $3, that is about 0.925. The lab finds 0.91 empirically.

### Decide before you measure

- **Fail:** any guardrail broken, whatever the outcome metrics say.
- **Ambiguous:** a metric is missing, or an outcome or counter-metric missed. Re-run on a larger set.
- **Pass:** everything met. Move to the next stage (Lesson 53).

## 3. What changed by Oct 2026

- **Decision models return probabilities by design.** Jev and Clef return a probability for every allowed answer. OpenAI's Decisions API (public beta, `gpt-6-luna`) and Vercel AI SDK `experimental_decide` return distributions too. That makes calibration a metric you *can* compute, so it is one you have to report.
- **Model cost per decision is now tiny.** Clef-flash is priced at $0.038 per million input tokens, and the OpenAI Decisions API charges for input only. At around 900 tokens per decision, model cost is a few thousandths of a cent, so error cost and human review cost decide the threshold.
- **Vendor accuracy isn't your metric.** Clef's launch benchmarks are self-reported, and a third-party review noted there is no published failure-mode guidance. Measure on your own labeled replay.
- **OTel GenAI conventions (Development status) and stable AI SDK telemetry** make it practical to log probability, threshold and route on every decision span, which ECE and abstain monitoring need.

## 4. Build it

`code/main.py` runs a full measurement plan:

- `validate_plan()` requires the contract fields plus at least one outcome, one guardrail and one counter-metric.
- `replay_log()` generates 400 deterministic decisions for two candidates: **A (calibrated)** and **B (overconfident)**.
- `expected_calibration_error()` (10 bins) and `brier_score()`.
- `operate()` computes abstain rate, auto precision, wrong auto-actions, cost per decision, median time and reviews per shift at a threshold.
- `pick_threshold()` sweeps 0.50–0.99 and picks the minimum expected cost from the cost matrix.
- `decide()` applies the predeclared fail, ambiguous and pass rules with inclusive thresholds.

```bash
python3 code/main.py
```

What to look for:

- Removing the guardrails makes the plan **invalid** before any data exists.
- Candidate A: ECE ≈ 0.014, cost-matrix threshold 0.91, abstain 10%, precision 0.972, cost about $1.30 per decision. **Pass.**
- Candidate B has the same raw score distribution but is overconfident. To be safe the sweep has to push the threshold to 0.99, so it abstains on 78% of cases. ECE ≈ 0.083 breaks the calibration guardrail. **Fail.**
- Drop the calibration value and the verdict becomes **ambiguous**, not pass.

## 5. Use it in production

- Log `{probabilities, chosen, threshold, route}` on every decision span. Compute ECE, abstain rate and precision on a weekly labeled sample.
- Keep the cost matrix in config next to the threshold, and re-pick the threshold whenever costs, the model version or the label set change.
- Use your eval platform (LangSmith, Langfuse, Phoenix, Braintrust) for the replay dataset and score history. Use Pydantic Evals or a plain script for the threshold sweep.
- **2026 update:** these metrics are the stage gates in Lesson 53 and the regression suite in Lesson 54. A Jev or Clef version bump (`jev-1.13` → next) is a model change. Re-run the plan before you switch.

## 6. Architect's lens

1. **Calibration is a prerequisite, not a nice-to-have.** An overconfident model forces very high thresholds, and high thresholds wipe out the automation the business case depends on.
2. **Abstain rate is where cost hides.** A "97% precise" system with a 78% abstain rate is mostly a human queue with extra steps. Report precision and abstain rate together, always.
3. **Thresholds are product decisions expressed as numbers.** The cost matrix makes the trade-off explicit and reviewable by non-engineers.
4. **Write the ambiguous path.** Real results are often inconclusive. Without a predeclared ambiguous path, teams round up to "pass".
5. **Drop metrics that can't change a decision.** Every metric costs collection, review and attention. If no value would change what you do next, remove it.

## 7. Exercises

1. Derive three questions from one outcome goal, and one metric contract for each.
2. Add a counter-metric for cost shifted to another role, such as incident commanders' review minutes.
3. Change `COST_WRONG_AUTO` to $400 (refunds instead of routing) and explain how the chosen threshold and abstain rate move.
4. Add a reliability diagram printout (bin, mean confidence, accuracy, count) for both candidates.
5. Find a metric on your current dashboard that couldn't change any decision. Remove it.

## 8. Key terms

| Term | Meaning |
|---|---|
| GQM | Goal → Question → Metric derivation |
| Guardrail metric | A fixed constraint that must hold. Breaking it fails the stage |
| Counter-metric | Catches harm or cost moved elsewhere |
| ECE | Expected calibration error: weighted gap between confidence and accuracy across bins |
| Cost-matrix threshold | The threshold that minimizes expected error cost plus review cost |

## 9. Quick check

<details><summary>1. Why can't a high precision alone pass a decision model?</summary>It may come from a very high threshold that sends most cases to humans. Abstain rate and cost per decision show that.</details>
<details><summary>2. Why does a missing metric give "ambiguous" rather than "pass"?</summary>The rule was decided in advance with that metric in it. Missing data can't count as a passed gate.</details>
<details><summary>3. Roughly where should a calibrated model's auto-act threshold be when a wrong action costs $40 and a review costs $3?</summary>About 1 − 3/40 ≈ 0.925. Confirm it with a sweep on labeled data.</details>

## References

- Basili, Caldiera, Rombach, *The Goal Question Metric Approach*: https://www.cs.toronto.edu/~sme/CSC444F/handouts/GQM-paper.pdf
- Basili, *Software Modeling and Measurement: The GQM Paradigm*: https://drum.lib.umd.edu/items/8119803a-362b-42ec-b6ce-2311713e7236
- Guo et al., *On Calibration of Modern Neural Networks* (arXiv 1706.04599): https://arxiv.org/abs/1706.04599
- Elkan, *The Foundations of Cost-Sensitive Learning* (IJCAI 2001): https://www.ijcai.org/Proceedings/01/IJCAI-2001-e.pdf
- Cloudflare Clef pricing and models: https://developers.cloudflare.com/changelog/post/2026-10-01-clef-workers-ai/
