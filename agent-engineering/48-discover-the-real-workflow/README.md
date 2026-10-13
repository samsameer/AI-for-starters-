# 48 · Discover the Workflow People Actually Perform

> **Short answer:** Requirements aren't sitting in a meeting waiting to be collected. They're scattered across actions, workarounds, logs and disagreements. Rebuild today's workflow as ordered steps, each with an actor, a trigger, an action and **evidence labeled by strength** (direct, artifact, reported, inferred). Look for friction, hidden state, authority boundaries and exceptions, and keep different variants separate instead of averaging them. Do this before writing a spec, because AI features usually fail at the handoffs and exceptions nobody mapped.

**Type:** Learn + Build · **Languages:** Python (stdlib) · **Time:** ~70 min

---

## 1. The problem

Ask people what they do and they describe the process as it should be: the runbook version, the happy path. Watch them and you see something else: the side chat, the spreadsheet only one person updates, the deploy log someone checks "just in case", the approval that really happens over a phone call.

An agent designed from the described workflow automates a process that doesn't exist. It then fails at exactly the points where humans were quietly compensating.

## 2. The concept

### Model each step

| Field | Example |
|---|---|
| Actor | On-call engineer |
| Trigger | Production alert arrives |
| Action | Opens alert, searches three dashboards |
| Friction | Context switching, manual owner lookup |
| Hidden state | "Which deploys are risky" lives in someone's memory |
| Authority | Only the incident commander approves production writes |
| Evidence | Trace, recording, runbook, interview |

### The evidence ladder

1. **Direct:** observation, trace, recording, system event.
2. **Artifact:** ticket, runbook, log, completed form.
3. **Reported:** someone tells you what they do.
4. **Inferred:** the team concludes what probably happens.

All four are useful. Only the first two prove current behavior. Label each claim so that confidence doesn't quietly inflate between the interview and the spec.

```
trigger ─► actor action ─► handoff ─► next actor action ─► outcome
              ▲                ▲               ▲
          direct ev.       artifact        reported (weak!)
                               │
                    exception branch (missing deploy record)
```

### Look for four things

- **Friction:** repeated effort, waiting, re-entry, recovery work.
- **Hidden state:** facts carried in memory, chat or personal notes.
- **Authority:** who or what is *allowed* to make a consequential change.
- **Exceptions:** where the normal path stops being normal.

### Don't average away disagreement

A senior engineer checks the deploy log first. A junior engineer escalates first. The difference may come from role, risk level, expertise, a legacy process or a real policy disagreement. An averaged workflow describes nobody, so keep the variants until you know which of these it is.

### Workflow steps are where decisions hide

Every step that picks among a few options ("which service?", "escalate or handle?") is a decision point. Mark it now. Lesson 47's decision inventory becomes concrete here, tied to evidence.

## 3. What changed by Oct 2026

- **Traces are now direct evidence.** OpenTelemetry GenAI conventions (`invoke_agent`, `execute_tool`, `chat` spans, still Development status) and MCP's standardized `traceparent` in `_meta` mean existing agent and tool runs give you timestamped behavior instead of anecdotes.
- **Observability platforms expose trajectories.** LangSmith Trajectories, Langfuse, Phoenix and Braintrust let you replay what humans and agents actually did, which makes workflow discovery partly a query.
- **Agents can draft the first map.** A coding or research agent can turn a week of tickets and logs into a candidate step list. Treat that output as **inferred** until someone verifies it.
- **Decision points are now cheap to automate.** Since bounded choices can run on a System One model (Jev, Clef) in tens to hundreds of milliseconds, the discovery output should list decision points explicitly so they can be costed.

## 4. Build it

`code/main.py` models two variants (senior, junior) of the incident workflow, plus one exception branch:

- `audit()` checks contiguous ordering, branches that point to real steps and known evidence kinds. It computes the **direct-or-artifact ratio** and lists weakly evidenced steps.
- `divergence()` shows where the variants differ, without merging them.
- `decision_points()` tags each bounded step as a System One candidate (choice or noul), or as human when an authority boundary exists.

```bash
python3 code/main.py
```

What to look for:

- `STATUS needs-evidence` with a ratio of about 0.62. Three steps rest only on interviews or inference.
- The exception branch (deploy record missing → ask in chat) starts at step 2 and exposes hidden state ("deploy ownership lives in chat").
- The commander's approval is classified as **human**, even though it has only two answers.

## 5. Use it in production

- **Sources:** start with traces, tickets and audit logs. Interview afterwards, to explain what the data shows.
- **Format:** keep `workflow-evidence.json` in the repo next to the outcome frame. Every later assumption (Lesson 49) should cite a step.
- **Consent and privacy:** screen recordings and support transcripts contain personal data. Redact them before they go into any shared evidence file or eval set.
- **2026 update:** for each System One candidate, record the answer labels people actually use today. Those labels become the `choice` criteria for a Jev or Clef question, and the historical decisions become your first labeled eval rows.

## 6. Architect's lens

1. **Direct-evidence ratio is a leading indicator of project risk.** If it's below about 50%, you are designing from stories. Budget discovery time before build time.
2. **Hidden state is the integration you didn't estimate.** If the deploy-risk knowledge lives in someone's head, your agent needs a new data source or a human checkpoint, and that is scope.
3. **Authority boundaries don't move because a model is confident.** A 0.99 probability doesn't grant the right to write to production. Map authority separately from difficulty.
4. **Exceptions dominate cost.** The happy path may be 85% of volume and 20% of the effort. Size the exception paths before promising savings.
5. **Variants are product segments.** Senior and junior workflows may need different defaults, such as assist mode for one and auto mode for the other.

## 7. Exercises

1. Rebuild one workflow purely from logs, then interview one person. Mark every claim the interview added that has no direct evidence.
2. Add an authority boundary and a failure-recovery step to the lab example.
3. Upgrade the junior escalation step from inference to direct evidence (invent a trace source) and watch the ratio change.
4. Add a third variant (a night-shift contractor) and list the divergences.
5. Find a proposed feature that removes a visible step but leaves the hidden work untouched.

## 8. Key terms

| Term | Meaning |
|---|---|
| Evidence ladder | Direct > artifact > reported > inferred |
| Direct-or-artifact ratio | Share of evidence that proves current behavior |
| Hidden state | Workflow-critical facts held outside any system |
| Authority boundary | A step only a specific role may perform |
| Variant | A distinct, valid version of the workflow kept separate from the others |

## 9. Quick check

<details><summary>1. Why not merge the senior and junior workflows?</summary>The difference may reflect role, risk or a policy gap. Averaging hides the one fact that matters for design.</details>
<details><summary>2. Is an agent-generated workflow map evidence?</summary>It is an inference until it is checked against traces or artifacts.</details>
<details><summary>3. Why is a two-answer approval step not a System One candidate?</summary>It carries authority. A model can inform the commander, but the decision right stays with the human.</details>

## References

- Nuseibeh & Easterbrook, *Requirements Engineering: A Roadmap*: https://www.cs.toronto.edu/~sme/papers/2000/ICSE2000.pdf
- Gotel & Finkelstein, *An Analysis of the Requirements Traceability Problem*: https://doi.org/10.1109/ICRE.1994.292398
- OpenTelemetry GenAI semantic conventions: https://opentelemetry.io/docs/specs/semconv/gen-ai/
- MCP specification 2026-07-28 changelog: https://modelcontextprotocol.io/specification/2026-07-28/changelog
