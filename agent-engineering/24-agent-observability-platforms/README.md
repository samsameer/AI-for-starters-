# 24 · Agent Observability Platforms: Langfuse, Phoenix, Opik and Peers

> **Short answer:** OTel GenAI (Lesson 23) defines what a trace looks like. An observability platform ingests those traces, runs evaluations on them, versions your prompts, and shows you which change made production worse. In Oct 2026 the open-source core is **Langfuse** (MIT core, now owned by **ClickHouse**), **Arize Phoenix** (Elastic License 2.0) and **Comet Opik** (Apache 2.0). The commercial side includes **LangSmith**, **Braintrust**, Datadog LLM Observability and cloud-native options such as AWS AgentCore. Choose by license, hosting model and the eval-to-fix loop you need, not by trace viewer polish.

**Type:** Learn · **Languages:** Python (stdlib) · **Time:** ~45 min

---

## 1. The problem

A team ships an agent, wires up tracing, and gets a beautiful waterfall view of every run. Two weeks later, customers complain that answers got worse. Nobody can say:

- **Which runs** are bad. Most failures don't raise exceptions; they return confident, wrong text.
- **Since when.** There is no baseline score to compare against.
- **Because of what.** The prompt was edited three times, the model alias moved, and a tool's API changed. None of those changes is linked to the traces.

Tracing on its own is expensive logging. Observability for agents means **traces + evaluations + versions**, joined.

## 2. The concept

### The loop

```
 agent ──OTel spans──► collector ──► platform
                                       │
             ┌─────────────────────────┼──────────────────────────┐
             ▼                         ▼                          ▼
      online evals             prompt / config versions     human annotation
   (judges, guards, rules)      attached to every trace       queues
             │                         │                          │
             └──────────► dashboards, alerts, regression bisect ◄─┘
                                       │
                                       ▼
                         offline datasets → CI evals (Lesson 30)
```

### Platform map, Oct 2026

| Platform | License / hosting | Strongest at |
|---|---|---|
| **Langfuse** | MIT core; cloud or self-host; acquired by ClickHouse | All-round: tracing, prompt management, datasets, evals, sessions; OTel-native |
| **Arize Phoenix** | Elastic License 2.0; self-host; Arize AX managed | OpenInference auto-instrumentation, RAG relevance, trace clustering and drift |
| **Comet Opik** | Apache 2.0; cloud or self-host | Prompt optimization experiments, guardrails, LLM-judge metrics |
| **LangSmith** | Commercial (free tier) | LangGraph integration, Trajectories view, Engine v2 auto-fix and red-teaming, voice tracing |
| **Braintrust** | Commercial | Eval-first workflow; "active observability" where agents query traces and open fixes |
| **Datadog LLM Observability** | Commercial | Teams already on Datadog; maps GenAI attributes into its schema |
| **AWS AgentCore** | Managed | Failure insights and optimization recommendations for AgentCore-hosted agents (preview) |

### Evaluators, from cheapest to most expensive

| Evaluator | Example | Notes |
|---|---|---|
| Deterministic rule | JSON schema, regex, tool-error count | Free, exact, narrow |
| Grounded check | Compare the claimed fact to a source of truth | Strongest signal when you have ground truth |
| Decision model | Jev / Clef `score` or `noul` with probabilities | Tens of ms, cheap enough for 100% of traffic |
| LLM-as-judge | Rubric scoring by a frontier model | Flexible. Costly, and needs calibration against humans |
| Human annotation | Queue of sampled or flagged traces | The ground truth for calibrating everything above |

## 3. What changed by Oct 2026

- **Langfuse was acquired by ClickHouse** (reported around Jan 2026). The project remains open source (the Python SDK is in the 4.x line) and ClickHouse was already its analytics store. For buyers, check the roadmap, the license of any newly added enterprise modules, and the self-host support terms.
- **Arize Phoenix** ships fast (major version 20 by Oct 2026) and is still under ELv2. That is fine for internal use, but it restricts offering Phoenix as a managed service.
- **LangSmith** added Engine (May) and Engine v2 (Sep), which red-team and auto-fix, plus a Trajectories view and voice tracing. Secondary coverage lists a 5k traces/month free tier.
- **Braintrust** pushes "active observability": agents themselves query traces and propose fixes as pull requests.
- **AWS AgentCore** added failure insights and an optimization preview (recommendations, batch evals, A/B tests).
- **Everything speaks OTel.** You can dual-export to two platforms during an evaluation period. Platform lock-in has moved from the trace format to datasets, eval definitions and prompt registries.
- **2026 update, System One judges:** decision models are now a practical online-eval tier. A Jev or Clef `score` question ("Rate scope adherence 0–3") returns a full probability distribution in tens of milliseconds, which makes scoring 100% of traffic affordable. Keep LLM judges for the sampled, nuanced cases (Lessons 55–56).

## 4. Build it

`code/main.py` is a minimal observability pipeline:

- `synthesize()` creates 60 seeded traces across two prompt versions (`v12`, `v13`). `v13` silently raises the wrong-fact rate. A quarter of the traces carry noisy human labels.
- `grounded_judge()` checks answers against a source of truth. `decision_style_scores()` converts that into probabilities, the way a decision model would report them.
- `evaluate()` tags traces: `wrong_fact`, `scope_creep`, `tool_error`, `guard_block`, `slow`.
- `dashboard()` prints failure rate, correctness, p50 latency and cost per prompt version, the top tags and the affected sessions.
- `bisect_regression()` finds the prompt version that caused the regression. `judge_agreement()` compares the judge with human labels. `pick_platform()` ranks platforms against a needs set.

```bash
python3 code/main.py
```

What to look for: `v13` is flagged as the regression. Judge-human agreement is well below 100%, partly because the human labels are noisy. Calibration runs in both directions.

## 5. Use it in production

- **Start OTel-first** (Lesson 23). Export through a Collector so you can switch or dual-run platforms.
- **Version everything a run depends on:** prompt id and version, model snapshot, tool schema hash, retrieval index version. Attach them as span attributes.
- **Three eval tiers:** deterministic and grounded checks on 100% of traffic, a decision-model tier on 100%, and LLM judges plus human review on a sample and on every flagged trace.
- **Close the loop:** flagged traces go into datasets, datasets feed CI evals, and CI gates prompt releases (Lesson 30).
- **Self-host checklist:** storage growth (traces are large), PII redaction before ingest, retention policy, SSO and RBAC, and the license terms (MIT, Apache 2.0, ELv2).

## 6. Architect's lens

1. **Judge the judges.** Measure every automated evaluator against a human-labeled slice and track its agreement and confusion matrix over time. An uncalibrated judge is a random number generator with a dashboard.
2. **Eval cost scales with traffic.** An LLM judge on every trace can cost as much as the agent itself. Tier the evaluators, and reserve the expensive ones for sampled or flagged traces.
3. **Ownership changes are risk events.** After the ClickHouse acquisition, re-check the roadmap, license and support terms. Keep data export (OTel plus dataset dumps) tested so switching stays possible.
4. **Alert on rates, not events.** One wrong answer is noise. A doubling of the `wrong_fact` rate within an hour of a prompt release is an incident. Use per-version baselines.
5. **Sessions beat traces for agents.** Many failures span turns: a constraint lost by turn 7, or a tool error that is retried silently. Group traces by `gen_ai.conversation.id` and evaluate at the session level as well.

## 7. Exercises

1. Add a `v14` that fixes correctness but doubles latency. How should the dashboard present this trade-off?
2. Replace the 0.5 thresholds with values chosen to maximize agreement with the human labels. Does that overfit to 15 labels?
3. Add a session-level evaluator: a session fails if any turn has `wrong_fact` or `scope_creep`. Compare session and trace failure rates.
4. Export the traces as OTLP-shaped JSON and import them into a local Langfuse or Phoenix. What did the platform show that your dashboard missed?
5. Write a one-page platform decision record for your team covering license, hosting, data residency, eval features, cost at 10M spans a month, and the exit plan.

## 8. Key terms

| Term | Meaning |
|---|---|
| Online eval | Evaluator that runs on production traces as they arrive |
| Offline eval | Evaluator run on a fixed dataset, usually in CI |
| Prompt management | Versioned prompts whose version is recorded on every trace |
| LLM-as-judge | A model scores outputs against a rubric |
| Judge calibration | Measuring evaluator agreement with human labels |
| Regression bisect | Finding which version change caused a quality drop |
| Trace clustering | Grouping similar runs to find failure patterns and drift |
| ELv2 | Elastic License 2.0: source-available, with limits on offering the software as a managed service |

## 9. Quick check

<details><summary>1. Why is tracing alone not observability for agents?</summary>Most agent failures are wrong-but-plausible outputs. Without evaluations you can't find them, and without versions on traces you can't tell which change caused them.</details>
<details><summary>2. You need open source, self-hosting and prompt management. What do you shortlist?</summary>Langfuse (MIT core) and Opik (Apache 2.0). Phoenix if ELv2 is acceptable and RAG or drift analysis matters most.</details>
<details><summary>3. Where does a decision model fit in the eval stack?</summary>As the cheap, typed tier that can score 100% of traffic with probabilities, between deterministic rules and sampled LLM judges or human review.</details>

## References

- Langfuse docs: https://langfuse.com/docs
- Arize Phoenix docs: https://arize.com/docs/phoenix
- Comet Opik: https://www.comet.com/docs/opik/
- LangSmith August 2026 newsletter: https://www.langchain.com/blog/august-2026-langchain-newsletter
- Platform comparison coverage (2026): https://www.marktechpost.com/2026/08/09/top-llm-observability-and-evaluation-platforms-in-2026-langfuse-langsmith-braintrust-arize-and-more-compared/
- AWS AgentCore release notes: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/release-notes.html
- Zheng et al., Judging LLM-as-a-Judge: https://arxiv.org/abs/2306.05685
