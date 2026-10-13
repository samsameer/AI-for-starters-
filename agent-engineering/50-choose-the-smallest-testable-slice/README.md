# 50 · Choose the Smallest Slice That Can Change the Decision

> **Short answer:** "Small" only helps if the slice proves something that matters. First list the proof you need, taken from the highest open risks in Lesson 49. Reject any candidate slice that doesn't cover it. Among the slices that pass, prefer high value and uncertainty reduction, low effort, low consequence and reversibility. Write a stop rule before you build. A tiny build that can't change the next decision is just unfinished work.

**Type:** Learn + Build · **Languages:** Python (stdlib) · **Time:** ~65 min

---

## 1. The problem

"Start with an MVP" is advice everyone agrees with and almost nobody applies the same way. Teams cut the wrong thing. They build a polished UI on synthetic data, which removes the data uncertainty they most needed to test. Or they build the infrastructure first, which proves the cloud works but says nothing about whether users care.

AI products add another trap: **the demo minimum**. A persuasive demo on hand-picked inputs, with nothing measured repeatably, gets mistaken for evidence.

## 2. The concept

### Vertical means evidence end to end

A useful slice runs through the minimum *real* workflow needed to observe the outcome. It can be narrow in users, data, duration and capability. It must not be narrow by removing the uncertainty you are trying to test.

| Candidate | What it actually tests |
|---|---|
| Read-only replay across real incidents, engineers review suggestions | Service identification, calibration and trust |
| Shadow-mode decision model on live alerts | Identification and calibration, not trust |
| Polished dashboard on synthetic data | Comprehension only |
| Production auto-remediation | Everything at once, at unacceptable consequence |

### Gate first, score second

```
required proof ─┬─► candidate 1 ─┐
                ├─► candidate 2 ─┼─► covers all proof? stop rule? safe? ──no──► reject
                └─► candidate 3 ─┘                │ yes
                                                  ▼
                              score = (value + uncertainty reduced)
                                      / (effort + consequence penalty)
                                                  │
                                                  ▼
                                          build one slice
```

The eligibility gate matters more than the arithmetic. A candidate that skips required proof is rejected **even when it scores higher**.

### Common false minimums

- **UI-only:** no real data, so feasibility stays unknown.
- **Infrastructure-only:** shows technical possibility but not user value.
- **Happy-path:** leaves out the exception that carries most of the risk.
- **Demo:** persuasive, but nothing is repeatable.
- **Platform:** builds shared machinery before a single workflow has earned it.

### The stop rule

Before you build, write what a failure leads to: abandon the outcome, change the user, test another mechanism, gather better evidence, or narrow authority further. If every result means "keep building", the slice isn't an experiment.

## 3. What changed by Oct 2026

- **Shadow mode is the default first slice for decision models.** A System One model (Jev, Clef-flash) can score every live event in milliseconds and log probabilities without acting. That gives real-data calibration evidence at almost no consequence.
- **"Platform first" is more tempting than ever.** Agent SDKs, MCP 2026-07-28 servers, A2A v1.0, managed agent runtimes and sandboxes are all mature enough to build a "general agent platform" in a sprint. That is still a platform minimum unless one workflow needs it.
- **Coding agents make effort estimates misleading.** When building is cheap, effort stops being the main differentiator, and consequence and reversibility become the deciding terms. The lab's score reflects that with a heavy penalty for irreversible slices.
- **Sandboxes reduce consequence.** Hosted sandboxes (Cloudflare Sandboxes GA, LangSmith Sandboxes, OpenAI Sandbox agents, AgentCore shells) let a slice touch realistic data and tools with a small blast radius.

## 4. Build it

`code/main.py` evaluates five candidate slices against a required proof set of `{service-identification, calibration, operator-trust}`:

- `gate()` rejects slices that miss required proof, have no stop rule, or are irreversible with consequence 4 or more.
- `false_minimums()` adds warnings for UI-only, happy-path, demo and platform minimums.
- `score()` divides value plus uncertainty reduction by effort plus a consequence penalty (×0.5 if reversible, ×2 if not).
- `decide()` picks the best eligible slice and returns its stop rule.

```bash
python3 code/main.py
```

What to look for: the dashboard (2.667) and the shadow-only slice (2.4) both **outscore** the winner (2.0) and still lose, because they don't prove operator trust. Auto-remediation proves everything but fails the irreversibility gate. The selected slice comes with a concrete stop rule: "stop if fewer than 6 of 10 engineers act on correct suggestions within 2 minutes".

## 5. Use it in production

- Write the required proof set into the slice's design doc and the coding agent's task brief. Agents tend to drift into adjacent work, and an explicit proof list keeps them on the slice.
- Use feature flags and read-only credentials so the slice's limits are enforced by the system, not just documented.
- Store the replay and shadow logs in your observability platform's dataset feature so the stop rule can be evaluated mechanically.
- **2026 update:** a "shadow-mode decision model" slice is the System One version of a dark launch. Log every `choice` with its probabilities, compare against what humans decided, and you have calibration evidence (Lesson 52) before the model has any authority.

## 6. Architect's lens

1. **Define the slice by what it proves, not by what it contains.** Two slices with the same features can test completely different assumptions.
2. **The cheapest wrong slice is the most expensive one.** A demo that convinces leadership without evidence creates a commitment the data may never support.
3. **Composite slices often win.** Replay plus shadow plus human review costs a little more but answers three questions in one cycle.
4. **Stop rules need a named decider.** Write who calls the stop and when. Otherwise the stop rule turns into a "discussion".
5. **Defer the platform on purpose.** Write down which reusable pieces you are postponing and what evidence would justify building them.

## 7. Exercises

1. Design three slices for one outcome at consequence levels 1, 3 and 5.
2. Add a cheap candidate that proves only `calibration`. Confirm that it stays ineligible however high it scores.
3. Remove one capability from the winning slice while keeping all of the required proof.
4. Write a stop rule for a failed pilot that names the decider and the date.
5. List the platform components your team wants to build, and the evidence that would justify each.

## 8. Key terms

| Term | Meaning |
|---|---|
| Vertical slice | A thin, end-to-end path through the real workflow |
| Required proof | The assumptions a slice must test to be eligible |
| False minimum | A small build that removes the uncertainty it should test |
| Shadow mode | The system decides and logs, but humans still act |
| Stop rule | A pre-declared result that ends or redirects the work |

## 9. Quick check

<details><summary>1. Why does a higher-scoring slice lose?</summary>It fails the eligibility gate by not proving a required assumption. Score only ranks slices that are already eligible.</details>
<details><summary>2. What does shadow mode prove, and what does it not?</summary>It proves feasibility and calibration on real data. It does not prove that users trust or act on the output.</details>
<details><summary>3. Why penalize irreversibility so heavily now that building is cheap?</summary>When effort is small, consequence and reversibility are what separate a safe experiment from an expensive commitment.</details>

## References

- Boehm, *A Spiral Model of Software Development and Enhancement*: https://dl.acm.org/doi/10.1145/12944.12948
- Lenarduzzi & Taibi, *MVP Explained: A Systematic Mapping Study* (arXiv 1609.07592): https://arxiv.org/abs/1609.07592
- Cloudflare Agents Week recap (Sandboxes): https://blog.cloudflare.com/agents-week-in-review/
- TypeSafe Jev SDK: https://github.com/typesafe-ai/typesafe-sdk-python
