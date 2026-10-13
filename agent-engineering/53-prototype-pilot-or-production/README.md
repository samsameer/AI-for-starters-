# 53 · Choose Prototype, Pilot or Production Deliberately

> **Short answer:** Prototype, pilot and production are different learning environments, not levels of polish. A prototype asks whether the mechanism can produce evidence at all. A pilot asks whether it works safely with a bounded real audience. Production asks whether you can own it continuously. Choose the stage that answers the current unknown with the least consequence. Move between stages through **metric gates**, which for decision models means calibration, precision, abstain rate, cost and zero guardrail breaches.

**Type:** Learn + Build · **Languages:** Python (stdlib) · **Time:** ~70 min

---

## 1. The problem

Two failures dominate:

- **Stage drift.** A prototype picks up real users, then production data, then write access, but never an owner, an SLO or a rollback. One day it is the system of record and nobody remembers agreeing to that.
- **Big-bang launch.** A model that looked good offline goes to 100% of traffic with full authority. The first distribution shift becomes an incident instead of a held gate.

Agents make both more likely. They are easy to build, so prototypes multiply. And they act, so authority creeps in through tool access.

## 2. The concept

### Three questions

| Stage | Primary question | Typical controls |
|---|---|---|
| Prototype | Can this mechanism produce the evidence at all? | Isolated sandbox, synthetic or redacted data, no production credentials, a delete-by date |
| Pilot | Does it work safely with a bounded real audience? | Named audience and owner, bounded duration and authority, audit log, rollback switch, thresholds, expand/revise/stop criteria |
| Production | Can we own it continuously? | SLO, on-call, security and privacy review, cost budget, recovery, monitoring, retirement path |

```
unknown ─► needs real users or data? ──no──► PROTOTYPE
                    │ yes
                    ▼
     consequence bounded AND operations ready? ──no──► PILOT
                    │ yes
                    ▼
               PRODUCTION
```

### Stage must be observable from the system

Write the stage into configuration, access control and telemetry, not just a banner. A prototype that can read production data is not a prototype, whatever the README says.

### Staged rollout with decision-model gates

Inside pilot and production, authority grows in steps:

```
shadow (log only, 100%) ─gate─► assist (human confirms, 10%) ─gate─► auto low-risk (25%) ─gate─► auto all (100%)
        ▲                                  │                                 │
        └────────── rollback on guardrail breach or precision collapse ◄─────┘
```

Each gate checks the Lesson 52 metrics on that stage's traffic:

| Gate | Labeled rows | Auto precision | ECE | Abstain | $/decision | Breaches |
|---|---|---|---|---|---|---|
| shadow → assist | ≥ 300 | ≥ 0.95 | ≤ 0.06 | ≤ 0.40 | ≤ 2.50 | 0 |
| assist → auto-low-risk | ≥ 500 | ≥ 0.96 | ≤ 0.05 | ≤ 0.35 | ≤ 2.20 | 0 |
| auto-low-risk → auto-all | ≥ 1000 | ≥ 0.97 | ≤ 0.05 | ≤ 0.30 | ≤ 2.00 | 0 |
| auto-all (steady state) | ≥ 2000 | ≥ 0.97 | ≤ 0.04 | ≤ 0.25 | ≤ 1.80 | 0 |

The verdicts are **promote**, **hold** (some gate missed: gather more data or fix and retry) and **rollback** (a guardrail breach, or precision more than 5 points below target: step back one stage).

## 3. What changed by Oct 2026

- **Sandboxes made safe prototypes the default.** Cloudflare Sandboxes (GA), LangSmith Sandboxes, OpenAI Agents SDK sandbox agents and AgentCore interactive shells give prototypes isolated compute and controlled egress without extra effort.
- **Permission modes encode stages.** Hosted agent platforms and agent SDKs ship `always_allow`, `always_ask` and `auto` style policies. Map them to stages: prototype uses read-only tools, pilot uses `always_ask` on writes, and production uses `auto` only for actions whose decision gate has passed.
- **Durable runtimes support long pilots.** Vercel Workflows (GA), Temporal and ADK 2.x graph workflows keep human approvals and resumable state across days, which an assist-mode pilot needs.
- **Decision models make shadow mode nearly free.** Clef-flash at tens of milliseconds and fractions of a cent per million tokens can score 100% of live traffic in shadow before it has any authority.

## 4. Build it

`code/main.py` contains three tools:

- `choose_stage()` maps an unknown (needs real users or data? consequence? ops ready? owner?) to a stage and its required controls, and warns when real users or data have no owner.
- `detect_drift()` compares a deployed system's declared stage with reality: users, production data, write access, missing controls.
- `run_rollout()` walks the four-stage plan over seven weekly observations using `evaluate_gate()`.

```bash
python3 code/main.py
```

What to look for:

- The refund approver, at consequence 5, goes to **pilot** even though operations are ready. It has no owner, so it gets a warning.
- `triage-demo` is declared a prototype but has real users and production data. That is drift.
- The rollout **holds** at assist when precision is 0.958, **promotes** after 70 corrected labels (Lesson 54), **rolls back** from auto-low-risk when an upstream format change causes a wrong page, and then climbs back to auto-all.

## 5. Use it in production

- Keep `stage` as a config value that also controls credentials, tool permissions and telemetry tags. A prototype build should fail to start with production credentials.
- Use feature flags or a gateway (Cloudflare AI Gateway, an LLM gateway) for traffic shares, and record the stage on every span.
- Write the pilot's exit criteria (expand, revise, stop) and the rollback receipt (who flipped what, when, and the evidence) before the pilot starts.
- **2026 update:** the gate table is the System One part of your release process. The decision model's metrics decide promotion, and code applies the verdict. The LLM (System Two) parts of the product still need their own eval gates (Lesson 30). Don't let a healthy router hide a regressed generator.

## 6. Architect's lens

1. **A stage is a promise about responsibility.** Production starts when the organization accepts ongoing ownership, not when the code is deployed.
2. **Authority grows more slowly than traffic.** It is safer to go to 100% traffic in shadow than to 10% traffic with write access.
3. **Rollback must be cheap and rehearsed.** If stepping back from auto to assist takes a deploy, people will delay it. Make it a flag.
4. **Gates without labeled data are theatre.** The `min_labeled` column is the real rate limiter on rollout speed, so budget for labeling.
5. **Retirement is a production control.** Every production system needs a defined way to be switched off, including the data and the eval set it leaves behind.

## 7. Exercises

1. Classify three of your current projects by learning stage, not by deployment status.
2. Change the refund approver to consequence 2 with an owner. What extra evidence would you want before accepting "production"?
3. Add a technical control to `detect_drift()` that fails if a prototype holds a production credential.
4. Add a `max_days_in_stage` rule that turns a long hold into a forced stop-or-revise decision.
5. Design the rollback receipt for the auto-low-risk rollback in the lab.

## 8. Key terms

| Term | Meaning |
|---|---|
| Prototype | Disposable, isolated test of a mechanism |
| Pilot | Bounded real use with an owner, audit and exit criteria |
| Production | Continuously owned service with an SLO, on-call and a retirement path |
| Stage drift | A system gaining users, data or authority without the matching controls |
| Decision gate | Metric thresholds that must hold before authority or traffic expands |

## 9. Quick check

<details><summary>1. A prototype reads production data but has no users. Is that fine?</summary>No. It has stopped being a prototype. Give it pilot controls or take away the data access.</details>
<details><summary>2. When does a gate return rollback instead of hold?</summary>On any guardrail breach, or when precision collapses well below target. Hold means "not yet". Rollback means "unsafe at this level".</details>
<details><summary>3. Why put shadow mode at 100% traffic before assist at 10%?</summary>Shadow has no authority, so full traffic gives the most calibration evidence at almost no consequence.</details>

## References

- Boehm, *A Spiral Model of Software Development and Enhancement*: https://dl.acm.org/doi/10.1145/12944.12948
- Fagerholm et al., *Building Blocks for Continuous Experimentation*: https://doi.org/10.1145/2601248.2601276
- Cloudflare Agents Week recap: https://blog.cloudflare.com/agents-week-in-review/
- AWS Bedrock AgentCore release notes: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/release-notes.html
- Vercel WorkflowAgent: https://vercel.com/kb/guide/what-is-workflowagent
