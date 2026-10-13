# 47 · Define the Outcome Before You Choose the Output

> **Short answer:** "Build an incident assistant" names an output. "On-call engineers identify the failing service and a safe next action within two minutes, while diagnosis stays read-only" names an outcome. Write the outcome first, as six parts: user, situation, current behavior, desired outcome, constraints and non-goals. Then check it for solution leakage. Coding agents make building fast, and building the wrong thing fast is the most expensive mistake an AI team can make. Do this before any architecture or model discussion.

**Type:** Learn + Build · **Languages:** Python (stdlib) · **Time:** ~60 min

---

## 1. The problem

In 2026 a team with a coding agent can ship a working prototype in an afternoon. The bottleneck has moved from *can we build it* to *should this be the thing we build*. Most failed AI projects didn't fail because the model was weak. They failed because the team built a chatbot when the user needed a better default, or a dashboard when the user needed one number at the right moment.

The usual cause is **solution leakage**. Someone names an artifact ("assistant", "RAG", "agent", "Clef-powered router") early. After that, every later conversation optimizes the artifact instead of the result.

## 2. The concept

### The six-part outcome frame

| Part | Question | Example |
|---|---|---|
| User | Who feels the problem directly? | On-call engineer |
| Situation | When and where does it happen? | A production alert fires during an incident |
| Current behavior | What happens today, workarounds included? | Opens three dashboards and asks in chat |
| Desired outcome | What observable state should improve? | Identifies the failing service and a safe next action within two minutes |
| Constraints | Which limits are fixed, and why? | Diagnosis stays read-only; audit events remain authoritative |
| Non-goals | What tempting nearby work is excluded? | No automatic remediation; no new alert routing |

```
user + situation ──► current behavior ──► desired outcome ──► constraints ──► non-goals
                                                  │
                                                  ▼
                             "what observation would disprove this?"
```

### Solution leakage

The outcome should be satisfiable by **several** outputs: software, a runbook, a data fix, or a one-line UI change.

| Leaks a solution | States the outcome |
|---|---|
| Users get a weekly AI summary | Users understand account changes before they approve them |
| Deploy a vector database | Relevant policy evidence is available during review |
| Use a decision model to route tickets | Tickets reach the right team within five minutes with fewer than 2% bounced |

A constraint *may* name technology when compatibility really fixes it ("runs on the existing MCP server fleet"). In that case the reason must be written down.

### Constraints are part of the goal

A build that hits the outcome by breaking a constraint has not hit the outcome. "Fast but wrote to production" counts as a failure.

### The decision inventory (principal-level add-on)

Once the frame is clean, list the decisions the eventual system will make, and tag each one early:

- **Bounded answer space** ("which service?", "is this a duplicate?") → a System One candidate.
- **Open-ended output** ("write the incident summary") → System Two (LLM).
- **Irreversible or authority-bearing** ("roll back the deploy?") → a human, at least for now.

This is not architecture yet. It is a way to notice early that half the "AI feature" may be a cheap typed decision.

## 3. What changed by Oct 2026

- **Build cost collapsed.** Coding agents and background agents turn a spec into a PR in minutes. That makes framing the scarcest skill on the team, not a planning ceremony.
- **The model menu is wider than "which LLM".** System One decision models (TypeSafe Jev, Cloudflare Clef, OpenAI's Decisions API in public beta) mean many outcomes need no text generation at all. Naming "an LLM agent" in the outcome closes off that option too early.
- **Vendor names churn monthly.** GPT-6.1, Gemini 3.8 and new frontier releases arrive every few weeks. An outcome that names a model ages within a quarter. An outcome that names a user result does not.
- **Hosted agent platforms ship "outcome" rubrics.** Several platforms now let you attach a grader rubric to an agent run. That only helps if the rubric encodes a real user outcome rather than "the output looks good".

## 4. Build it

`code/main.py` validates three frames:

- `leaked_terms()` scans for product forms, model names, frameworks and the proposed output itself.
- `validate()` requires all six parts, an observable bound in the outcome (a time, count or condition), and a reason for any technology-naming constraint.
- `classify()` tags each item in the decision inventory as System One candidate, System Two or human.

```bash
python3 code/main.py
```

What to look for:

- **GOOD** passes. Its MCP constraint is allowed because it carries a reason.
- **LEAKY** ("engineers use the Clef-powered incident assistant for every alert") fails three ways: it leaks a solution, it has no observable bound, and it has an unjustified "must use LangGraph".
- **VAGUE** ("support feels better") fails on missing parts and has no bound.
- The decision inventory splits into two System One candidates, one System Two task and one human decision.

## 5. Use it in production

- Put the outcome frame at the top of the design doc and the PR template. Reviewers can then reject work that serves an output nobody asked for.
- Give it to your coding agent as the first section of the task brief (Lesson 43). Agents follow concrete outcomes and constraints much better than adjectives.
- Keep `outcome-frame.json` (or equivalent) in the repo. Lessons 48–54 all read from it.
- **2026 update:** the decision inventory is the bridge to Lessons 55–57. Every bounded decision in it is a candidate for a Jev or Clef question, with a threshold that code owns. List them now so the architecture review can price them.

## 6. Architect's lens

1. **The outcome is a contract with the business.** If you can't state what would disprove it, you can't fail, and a project that can't fail can't really succeed either.
2. **Leakage is a political problem as much as a technical one.** The person who proposed "the assistant" has a stake in it. Reframing in terms of the user's result lets you change the output without making it personal.
3. **Constraints carry the risk budget.** Read-only, audit-preserving and no-new-dependency constraints are what make a fast pilot approvable by security.
4. **Non-goals protect the slice.** "No automatic remediation" is the sentence that stops a two-week pilot from turning into a six-month platform.
5. **Price the decision inventory early.** A typed decision at fractions of a cent per million tokens versus an LLM call at dollars per million changes the business case. Know which you need before anyone estimates.

## 7. Exercises

1. Rewrite a feature request from your backlog as a six-part frame and run it through the validator.
2. Add a constraint that removes at least one candidate solution. Explain which one and why.
3. Write three different outputs that would all satisfy the GOOD frame.
4. Extend `SOLUTION_TERMS` with your own stack's vocabulary and re-run it against your last three design docs.
5. For each decision in your inventory, write the threshold question you would need answered before automating it.

## 8. Key terms

| Term | Meaning |
|---|---|
| Output | An artifact the team could build |
| Outcome | An observable change in a user's situation |
| Solution leakage | Naming a product form, model or architecture inside the outcome |
| Non-goal | Adjacent work explicitly excluded from this slice |
| Decision inventory | The list of choices the system will make, tagged System One, System Two or human |

## 9. Quick check

<details><summary>1. Can a constraint name a technology?</summary>Yes, if compatibility or policy really fixes it and the reason is recorded. Otherwise it is leakage dressed up as a constraint.</details>
<details><summary>2. Why require an observable bound in the outcome?</summary>Without a time, count or condition, nobody can tell whether the outcome was reached, so it cannot drive the metrics in Lesson 52.</details>
<details><summary>3. Why tag decisions as System One or Two this early?</summary>It shows which parts need no text generation, which changes cost, latency and risk estimates before any architecture is committed.</details>

## References

- Nuseibeh & Easterbrook, *Requirements Engineering: A Roadmap* (ICSE 2000): https://www.cs.toronto.edu/~sme/papers/2000/ICSE2000.pdf
- Dardenne, van Lamsweerde, Fickas, *Goal-Directed Requirements Acquisition*: https://doi.org/10.1016/0167-6423(93)90021-G
- Pydantic AI decision models: https://pydantic.dev/docs/ai/models/decision/
- Cloudflare Clef launch changelog: https://developers.cloudflare.com/changelog/post/2026-10-01-clef-workers-ai/
