# 46 · Turn Every Agent Correction into a System Improvement

> **Short answer:** When you correct an agent in chat, you fix one run. When you turn that correction into a test, a scope rule, a script, an example or a labeled decision row, you fix every run after it. Treat each correction as evidence that some part of the work system was not executable. Put the fix at the earliest layer that can stop the failure, and give it an owner and a retirement date. Do this whenever the same correction shows up twice, or when a single occurrence is severe.

**Type:** Learn + Build · **Languages:** Python (stdlib) · **Time:** ~65 min

---

## 1. The problem

Every team that uses coding agents builds up a private folklore of corrections: "don't touch that folder", "run the migrations first", "the date format is ISO, not US". These live in chat logs and in the heads of senior engineers. The next session starts from zero, so the same mistake costs the same review time again.

The opposite failure is just as common. Every correction becomes another paragraph in the agent instruction file. The file grows to 600 lines, rules start to contradict each other, and the agent follows none of them reliably.

A principal architect sees both as one design problem. **Corrections are signals about the system, not about the prompt.** The job is to route each one to the cheapest durable control and to remove controls that have stopped earning their place.

## 2. The concept

### Promote to the earliest effective layer

| Recurring failure | Durable destination | Strength |
|---|---|---|
| Wrong result, regression | Test or eval case | Executable |
| Wrong verdict from a router, guard or judge | Labeled row in the decision eval set | Executable, and also reusable as training data |
| Off-scope or unsafe action | Scope check or permission policy | Enforced |
| Repeated setup or command mistake | Script, hook or tool | Automated |
| Repeated output-shape mistake | Canonical example plus a validator | Checked |
| Ambiguous local convention | Instruction (AGENTS.md or a Skill) plus a scenario check | Advisory |
| Product disagreement | Human decision record | Owned |

Read the table top to bottom. A type that makes a bad state impossible beats a test that catches it. A test beats a review comment. A review comment beats a sentence asking the agent to remember.

```
correction ──► root cause ──► earliest owner ──┬─► test / eval case
                                               ├─► decision-eval row (System One)
                                               ├─► scope / permission
                                               ├─► script / hook
                                               ├─► example + validator
                                               └─► human decision record
                                                         │
                                       next run starts stronger ◄┘
```

### Cause, not symptom

"The agent edited README" is a symptom. The cause might be that the task scope was only described in prose, that docs were treated as implicitly safe, or that two workers had overlapping ownership. Each cause needs a different control. A rule that only restates the symptom fails on the next variation, such as "the agent edited CHANGELOG".

### The ratchet record

For each promoted control, keep: symptom(s), root cause, consequence (1–5), recurrence count, target layer, how the control is verified, owner, and a review date.

### Promotion rule

Promote when `recurrence >= 2` or `consequence >= 4`. Everything else stays as a session note. One-off style preferences don't deserve permanent complexity.

### Controls decay

Review every control on its date. Retire or rewrite it when the architecture has changed, when a stronger executable control has replaced it, when the failure hasn't recurred over a meaningful window, or when it blocks more legitimate work than the harm it prevents. The aim is the smallest system that still keeps the judgment you paid for.

## 3. What changed by Oct 2026

- **Agent instruction files are standardized.** AGENTS.md is stewarded by the Agentic AI Foundation and read by most coding agents. Promoted *instructions* now go there or into an Agent Skill (`SKILL.md` folder), so one control reaches every tool your team uses.
- **Hooks and permission policies are first-class in coding agents and agent SDKs.** Many "please don't" rules can now be pre-tool hooks or `always_ask` policies. That moves them from advisory to enforced.
- **Decision corrections are data.** Routers and guards increasingly run on System One decision models (Jev, Clef, OpenAI Decisions API). When a human overrides one of these verdicts, the override is a labeled `(state, question, answer)` row. It goes straight into the decision eval set (Lesson 30) and can later feed Clef's RL fine-tuning service (Lessons 54, 56).
- **Coding agents can draft the control.** Background or cloud agents can open a draft PR that adds the regression test for a correction. The owner still reviews and merges it.

## 4. Build it

`code/main.py` runs the ratchet on six example corrections and four existing controls:

- `canonical_cause()` normalizes wording with a synonym map, stopwords and sorted unique words. "scope was described but not checked" and "the scope was only described, never checked" end up with the same fingerprint.
- `choose_target()` picks the earliest layer. A correction that includes a `DecisionRecord` always goes to `decision_eval`.
- `ratchet()` groups by fingerprint, applies the promotion rule, sets a review date based on consequence, and emits labeled decision rows.
- `retirement_review()` returns `retire`, `rewrite`, `candidate to retire` or `keep` for existing rules.

```bash
python3 code/main.py
```

What to look for:

- The two scope corrections collapse into **one** control with `occurrences=3`.
- The destructive-migration guard miss gets promoted on its **first** occurrence (consequence 5), and it produces a labeled row: the model said `yes` at 0.71, the human said `no`.
- The tabs preference is **not** promoted.
- "Always ask before running tests" is flagged for **rewrite**: 40 blocks a month against 1 prevention.

## 5. Use it in production

- **Where controls live:** tests in your normal suite, scope rules in the agent's permission config or pre-tool hooks, setup in a session-start script, conventions in AGENTS.md or a Skill, and decision rows in a versioned JSONL eval set.
- **Capture:** add a "promote this" action to your review flow. A PR comment or a tracing-platform annotation (LangSmith, Langfuse, Braintrust, Phoenix) can create the ratchet record with the trace attached.
- **Verify:** every control states the check that proves it works. For a test, that means it fails before the fix and passes after. For a scope rule, the replayed bad action must get blocked.
- **2026 update:** when the corrected behavior was a System One verdict (a Jev or Clef guard, router or stop condition), the durable fix is usually *not* a prompt edit. Add the labeled row, re-run the decision eval, and re-pick the threshold from the cost matrix (Lesson 52).

## 6. Architect's lens

1. **The cost curve is steep.** A correction caught by a type costs seconds. The same correction caught in review costs a reviewer's attention, and caught in production it costs an incident. Spend effort to move controls left.
2. **Instruction files are a liability as well as an asset.** Every line costs context tokens on every run and can conflict with other lines. Track instruction count like you track dependency count.
3. **Fingerprints keep the ratchet honest.** Without deduplication, ten wordings of one cause look like ten small problems instead of one big one, and your prioritization will be wrong.
4. **Retirement needs evidence too.** Don't delete a control because it feels old. Show the stronger control that replaced it, or show the quiet window.
5. **Owners, not teams.** "Platform" is not an owner. A control without a named person will outlive its purpose.

## 7. Exercises

1. Take five corrections from your last week of agent sessions. Classify the real cause and the earliest layer for each.
2. Replace one prose rule in your AGENTS.md with an executable test or hook. Then delete the prose.
3. Add a third wording of the scope correction to the lab and extend `SYNONYMS` until it collapses, without merging the unrelated date-parsing cause.
4. Add a `blast_radius` field and make it raise the review frequency.
5. Feed the lab's labeled decision row into the Lesson 55 `LocalSystemOne` eval and see whether a re-picked threshold would have held the migration.

## 8. Key terms

| Term | Meaning |
|---|---|
| Ratchet | A mechanism that lets the system improve in one direction only: fixed failures stay fixed |
| Earliest effective layer | The cheapest point in the pipeline where the failure can be made impossible or caught |
| Fingerprint | A stable hash of the normalized cause, used to group duplicates |
| Promotion rule | The recurrence or consequence threshold for making a correction permanent |
| Retirement check | A scheduled review that removes or rewrites controls that no longer pay for themselves |

## 9. Quick check

<details><summary>1. Why group by cause rather than by symptom?</summary>One cause produces many different symptoms. Grouping by cause shows the real recurrence count and leads to one control that covers every variant.</details>
<details><summary>2. A guard model wrongly allowed a risky tool call once. Should that be promoted?</summary>Yes. The consequence is high enough to promote on the first occurrence, and the correction is a labeled decision row that goes into the eval set before the threshold is re-picked.</details>
<details><summary>3. When should you retire a control?</summary>When a stronger control replaced it, when the architecture changed, when the failure stayed absent through the review window, or when its friction exceeds the harm it prevents. Record the evidence when you retire it.</details>

## References

- Basili, Caldiera, Rombach, *The Goal Question Metric Approach*: https://www.cs.toronto.edu/~sme/CSC444F/handouts/GQM-paper.pdf
- Shinn et al., *Reflexion: Language Agents with Verbal Reinforcement Learning* (arXiv 2303.11366): https://arxiv.org/abs/2303.11366
- Madaan et al., *Self-Refine* (arXiv 2303.17651): https://arxiv.org/abs/2303.17651
- AGENTS.md: https://agents.md
- Böckeler, *Harness engineering for coding agent users*: https://martinfowler.com
