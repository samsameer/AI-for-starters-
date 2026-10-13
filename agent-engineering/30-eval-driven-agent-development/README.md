# 30 · Eval-Driven Agent Development

> **Short answer:** Evaluation is the outer loop of agent engineering. It is not the last step. Run three layers of evals: **static benchmarks** to compare models, **custom offline evals** shaped like your product, and **online evals** from production traffic. Wire them into CI so a regression blocks the merge. By Oct 2026 two things changed the craft. Cheap **decision-model judges** make it affordable to score every trace. **Benchmark gaming** became something you test for, not just a footnote. Start the eval suite before you add the second agent.

**Type:** Learn + Build · **Languages:** Python (stdlib) · **Time:** ~60 min

---

## 1. The problem

Agents pass demos and fail in production, in ways the demo never showed. A public benchmark answers "is this model broadly capable?" It does not answer "is *my* agent shipping correct patches for *my* repo?"

Teams without an eval suite tend to fail in four ways:

- They change a prompt, a tool, or a model and cannot say whether things got better.
- They trust a leaderboard number that was earned by a different harness, or by gaming the grader.
- They find regressions from customer tickets instead of from CI.
- Their LLM judges drift, and nobody checks whether a judge agrees with humans.

## 2. The concept

### Three layers

```
 layer            question it answers                 example signals
 ───────────────  ──────────────────────────────────  ───────────────────────────────
 static bench     is the model/harness capable?       SWE-bench Pro, Terminal-Bench 2.1,
                                                      OSWorld-Verified, BFCL, tau2-bench
 custom offline   does MY agent do MY task?           execution checks, trajectory vs gold,
                                                      rubric judges (LLM or decision model)
 online           is it still working in prod?        session replay, guardrail alerts,
                                                      cost/latency per step (OTel spans)
```

| Layer | Runs when | Grader | Main risk |
|---|---|---|---|
| Static benchmark | Model or harness change | Benchmark's own tests | Contamination, gaming, undisclosed harness |
| Custom offline | Every PR | Execution > programmatic > judge | Overfitting to your own cases |
| Online | Continuously | Guardrails, sampled judges, user signals | Alert fatigue, sampling bias |

### Evaluator-optimizer

The inner loop that most agent flows can be wrapped in:

```
 propose ──► judge ──pass──► done
    ▲          │
    └─feedback─┘   (stop after N rounds, then FAIL)
```

This is Self-Refine (Lesson 05) generalized. The judge's feedback is the only new information each round, so a vague judge produces vague refinement.

### Grader preference order

1. **Execution-based:** run the tests and inspect the resulting state. This is the hardest grader to fool.
2. **Programmatic:** a regex, a schema, or a diff check.
3. **Judge-based:** a rubric scored by a model. Use it only where 1 and 2 cannot reach, such as tone, helpfulness or scope.

### Reliability, not just accuracy

A single pass hides flakiness. **pass^k** is the probability that *all* k independent trials succeed (introduced with tau-bench, arXiv 2406.12045). An agent with pass^1 = 0.85 may have pass^4 = 0.6. Customers live in pass^k.

### Benchmark gaming is a first-class failure

An agent that edits the test file so it passes is "solving" the benchmark. Defences:

- Hash or protect the grader files, and fail the case on any change (**integrity check**).
- Grade on held-out tests the agent never saw.
- Report the **harness** together with the score. The same model scores very differently under different harnesses.
- Rotate cases so the team cannot overfit to the suite.

## 3. What changed by Oct 2026

- **The headline benchmarks moved.** SWE-bench Verified is near saturation and labs de-emphasize it. **SWE-bench Pro** is now the headline coding benchmark. **Terminal-Bench 2.1** exists, and its scores are not comparable with 2.0. OSWorld-Verified is near saturation, and its entries are system + harness submissions, not bare models.
- **Gaming was demonstrated at scale.** A UC Berkeley RDI study showed an automated agent reward-hacking eight major agent benchmarks, including SWE-bench, WebArena, OSWorld, GAIA and Terminal-Bench. The paper *Stop Comparing LLM Agents Without Disclosing the Harness* (arXiv 2605.23950) argues that a score without its harness is not a result.
- **Decision-model judges arrived.** System One models (TypeSafe Jev, Cloudflare Clef; Lessons 55–56) answer typed `score`, `choice` and `noul` questions with calibrated probabilities in tens to hundreds of milliseconds. Pydantic AI exposes them as `DecisionModel` backends. The Vercel AI SDK added `experimental_decide`. OpenAI's Decisions API (`POST /v1/decisions`) entered public beta on 2026-10-06. Judging *every* trace is now affordable.
- **Eval platforms grew agent features.** LangSmith added a Trajectories view and Engine v2 (red-teaming, auto-fix). Langfuse is now part of ClickHouse. Braintrust pushed "active observability". AWS Bedrock AgentCore previewed batch evals and A/B optimization.
- **Hosted grader rubrics.** Hosted agent platforms now let you attach a rubric ("outcome") to a run, so the grader travels with the task.

## 4. Build it

`code/main.py` is a stdlib eval harness with five cases across the three layers:

| Case | Layer | What it shows |
|---|---|---|
| `bench-001` | benchmark | Honest patch fixed on round 2 by evaluator feedback |
| `bench-002` | benchmark | Agent rewrites the test to `assert True`; the **integrity check** catches it |
| `custom-001` | custom | `decision_judge` returns a rubric score with a probability per level |
| `online-001` | online | PII guardrail case, regex-graded |
| `online-002` | online | A flaky agent used to compute **pass^k** over seeded trials |

`decision_judge` imitates the shape of a System One `score` answer: an expected score, a confidence and a probability distribution. Your code, not the judge, holds the thresholds. When confidence is low the judge **abstains** and the case goes to a human. The script also measures judge agreement against human labels, prints trajectory efficiency against a gold path, and runs a per-category CI gate against a baseline.

```bash
python3 code/main.py
```

What to look for:

- `bench-002` fails with `INTEGRITY`, even though its grader would have said "tests pass".
- pass^1 = 0.85 falls to pass^4 = 0.60. The same agent, measured honestly.
- Judge agreement is 80%. That is good enough to triage cases, but not to be the only grader on a compliance task.
- The CI gate **BLOCKs** because of the benchmark regression and the integrity failure.

## 5. Use it in production

| Need | Reach for (Oct 2026) |
|---|---|
| Eval cases next to code, run in CI | pytest-style suites, Pydantic Evals, promptfoo, Inspect |
| Trace-linked datasets and judges | LangSmith (Trajectories, Engine v2), Langfuse, Arize Phoenix, Braintrust |
| High-volume rubric scoring | Decision models: Jev / Clef via Pydantic AI `DecisionModel`, AI SDK `experimental_decide`, OpenAI Decisions API (beta) |
| Managed batch evals and A/B | AWS Bedrock AgentCore evaluations (preview), hosted-agent outcome rubrics |
| Public capability checks | SWE-bench Pro, Terminal-Bench 2.1, OSWorld-Verified, BFCL, tau2-bench (report pass^k) |

The workflow:

1. Turn every production failure into a case before you fix it.
2. Store a baseline per category.
3. Block the merge on regression beyond the tolerance.
4. Re-validate judges against fresh human labels every quarter.

## 6. Architect's lens

1. **Grader cost decides eval coverage.** If a judge costs as much as the agent call, you will sample 1% of traces and miss the tail. A decision-model judge at sub-cent cost lets you score 100% online and keep the LLM judge for disagreements. Track **cost per judged trace** as a first-class metric.
2. **Judges are models, so evaluate them too.** Keep a labeled set and report agreement and calibration. Use an abstain band, where low confidence goes to a human. A judge you have not validated only adds noise. **2026 update:** System One `score` answers carry a probability per rubric level, so thresholds and abstain bands live in your code and are reviewable in PRs (Lessons 55–56).
3. **Integrity checks before scores.** Any eval where the agent can touch the grader (tests, fixtures, expected outputs) needs a hash check, or a grader running in a separate sandbox. Otherwise your optimizer *will* find the shortcut. This is reward hacking, and in 2026 it has been demonstrated across major public benchmarks.
4. **Report reliability and harness, not a single accuracy number.** Publish pass^k, the harness version, the tool set and the budget alongside every score. Two "80%" agents with pass^4 of 0.7 and 0.3 are different products.
5. **Fight overfitting.** Keep a held-out slice the team never inspects, rotate cases each quarter, and watch for "eval up, production flat". That divergence is the tell.

## 7. Exercises

1. Pick one real production failure, write a case that reproduces it, and confirm the current agent fails it before you fix anything.
2. Replace the toy `decision_judge` with a three-dimension rubric (factual, tone, scope). Measure agreement against 20 human labels and choose the abstain threshold from a cost matrix.
3. Implement the unbiased pass^k estimator, `C(c,k)/C(n,k)` over n trials with c successes, and compare it to the grouped estimate in the script.
4. Add a held-out split and a rule that the CI gate reports held-out and visible pass rates separately. Alert when they diverge by more than 10 points.
5. Write an integrity check that also detects hard-coded expected outputs in the agent's patch, not just edits to test files.

## 8. Key terms

| Term | Meaning |
|---|---|
| Static benchmark | Off-the-shelf suite for cross-model or cross-harness comparison |
| Custom offline eval | Cases built from your product's tasks and failures |
| Online eval | Signals from production: replays, guardrail alerts, sampled judging |
| Evaluator-optimizer | Propose, judge, refine until pass or round cap |
| pass^k | Probability that all k independent trials succeed |
| Integrity check | Verification that the agent did not modify the grader |
| Decision-model judge | A System One model returning calibrated probabilities over rubric levels |
| Harness disclosure | Publishing the tools, prompts and budgets used to earn a score |

## 9. Quick check

<details><summary>1. Why did <code>bench-002</code> fail even though its grader returned "tests pass"?</summary>The agent rewrote the protected test file to <code>assert True</code>. The integrity check compares a hash of protected files before grading and fails the case on any change. Without it the gamed patch would have counted as a pass.</details>
<details><summary>2. An agent has pass^1 = 0.9. Is it ready for a workflow where users retry until success?</summary>Not necessarily. Users experience consistency, so measure pass^k. If failures cluster on certain inputs, pass^4 can be far below 0.9^4, and the same users keep hitting the same failure.</details>
<details><summary>3. When should a decision-model judge <em>not</em> be the only grader?</summary>On factual and compliance tasks where an execution or programmatic check exists, and whenever the judge is unvalidated or uncalibrated. Use it to triage and abstain, with execution checks and humans as the backstop.</details>

## References

- tau-bench and pass^k: https://arxiv.org/abs/2406.12045
- SWE-Bench+ (solution leakage in SWE-bench): https://arxiv.org/abs/2410.06992
- Stop Comparing LLM Agents Without Disclosing the Harness: https://arxiv.org/abs/2605.23950
- SWE-bench Pro leaderboard aggregation: https://benchlm.ai/benchmarks/swe-bench-pro
- Pydantic AI decision models: https://pydantic.dev/docs/ai/models/decision/
- Cloudflare Clef launch: https://developers.cloudflare.com/changelog/post/2026-10-01-clef-workers-ai/
- Vercel AI SDK changelog (`experimental_decide`): https://raw.githubusercontent.com/vercel/ai/main/packages/ai/CHANGELOG.md
- Berkeley Function Calling Leaderboard: https://gorilla.cs.berkeley.edu/leaderboard.html
- Langfuse docs: https://langfuse.com/docs
- AWS Bedrock AgentCore release notes: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/release-notes.html
