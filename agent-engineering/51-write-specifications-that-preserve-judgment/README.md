# 51 · Write Specifications That Preserve Judgment

> **Short answer:** A good spec for a coding agent (or a human team) fixes the outcome, the invariants and the proof, and leaves cheap, reversible choices open. Mark every decision **locked** (a human decides), **bounded** (the agent decides within explicit limits) or **delegated** (the agent decides and explains). Back every claim with proof from the right layer. That gives you an executable contract, not a screenplay. Use it for any task you hand to an agent that takes more than a few minutes.

**Type:** Learn + Build · **Languages:** Python (stdlib) · **Time:** ~75 min

---

## 1. The problem

There are two ways to fail a coding agent:

- **Underspecify:** "Build the incident helper." The agent guesses the system, chooses its own authority and declares victory on a demo.
- **Overspecify:** a 40-step script naming every file and function. The agent copies a design that may already be wrong and can't use its judgment where it's actually good, such as local structure, naming and refactors.

Modern agents are strong at implementation choices and weak at knowing which choices they aren't allowed to make. The spec has to say which is which.

## 2. The concept

### Six surfaces

| Surface | Purpose |
|---|---|
| Outcome | The observable result (from Lesson 47) |
| Invariants | What must always remain true |
| Examples | Normal, edge, failure and forbidden cases that reveal intent |
| Non-goals | Nearby behavior that is excluded |
| Decision policy | Locked, bounded or delegated, for each decision |
| Proof | The evidence required before "done" |

### Three decision modes

```
decision ──► consequence & reversibility?
               │ high or irreversible ──► LOCKED     ──► human checkpoint
               │ known safe range      ──► BOUNDED    ──► agent chooses within config limits
               │ cheap & reversible    ──► DELEGATED  ──► agent chooses, explains, proves
```

The lab enforces one rule mechanically: **consequence ≥ 4 or irreversible ⇒ locked.** A schema will happily accept `mode: "delegated"` on "may the system write to production?". The product risk won't.

### Examples beat adjectives

"Robust", "helpful" and "production-ready" can't be executed. Four examples can: one normal, one edge, one failure and one forbidden. Examples don't replace invariants, though. One passing case can't prove a universal rule.

### Proof must match the claim

| Claim layer | Adequate proof |
|---|---|
| Function contract | Unit test |
| Serialization or transport | Wire test |
| Interface path | Browser or user-journey test |
| Behavior over representative cases | Replay set |
| Authority held | Audit log |

A lower layer never proves a higher-layer claim. A unit test that mocks the write tool doesn't prove that no production writes happened.

### Thresholds live in config, not prose

Bounded decisions point at a config key (`auto_show_threshold: 0.82`), not at a sentence in the prompt. Code reads the config, evals tune it, and the agent never invents it.

## 3. What changed by Oct 2026

- **Specs compile to several targets.** The same decision policy feeds AGENTS.md or a Skill (the readable brief), the agent SDK's permission policy (`always_allow`, `always_ask`, `auto` modes are now common on hosted agent platforms) and pre-tool hooks. The lab prints both the brief and the permission policy from one spec.
- **Structured outputs replaced prompt tricks.** Current frontier models have removed assistant prefill and often reject forced tool choice. Output shape now belongs in a schema (`strict` tools, structured outputs), and a spec should name the schema rather than describe the format in prose.
- **Durable approvals exist.** Vercel `WorkflowAgent`, Temporal integrations and ADK 2.x `RequestInput` let a locked decision pause a run for hours or days until a human approves. Locked no longer means "the agent can't do the task".
- **Bounded decisions can be typed.** Many bounded choices ("show the guess or say unsure?") are System One questions with a threshold in config, rather than a judgment the LLM makes inside its reasoning.

## 4. Build it

`code/main.py` validates a specification for the incident slice and derives its artifacts:

- `validate()` checks that every surface is present, that failure and forbidden examples exist, that modes are valid, that locked and bounded decisions have rationales, that high-consequence or irreversible decisions are locked, that bounded decisions reference real config keys, and that proof layers are adequate.
- `agent_brief()` renders the text to drop into AGENTS.md or a Skill.
- `permission_policy()` maps tools to `always_allow` or `always_ask`.

```bash
python3 code/main.py
```

What to look for: the spec is `executable`. The brief separates "you decide", "you decide within limits" and "stop and ask a human". `k8s.rollout_restart` gets `always_ask`. The mutated spec (production write delegated, audit proof swapped for a unit test) produces two findings, and the first one reads "schema accepts it, product risk does not".

## 5. Use it in production

- Keep the spec as a structured file (YAML or JSON) in the repo and generate the agent brief and permission config from it, so they can't drift apart.
- Coding agents: put the brief in the task, and enforce the locked items with permission policies or hooks, not just words.
- Reviewers check proof against claim layers. "Tests pass" is not an answer to "authority held".
- **2026 update:** for every bounded decision that is a classification or yes/no ("is this guess confident enough to show?"), write it as a System One question (Jev, Clef) whose threshold sits in the spec's config block. The spec owns the threshold, the eval set tunes it (Lesson 52), and the agent never sees or edits it.

## 6. Architect's lens

1. **Locked decisions are your liability surface.** List them in the architecture review. Each one should map to a human role, a durable approval mechanism and an audit record.
2. **Delegation is how you get speed safely.** Over-locking turns the agent into a typist and the reviewer into the bottleneck. Delegate everything cheap and reversible, and ask for an explanation.
3. **Proof layering prevents the most common false "done".** Most agent PRs that are "done but wrong" have unit-level proof for a replay- or audit-level claim.
4. **Record the reason for each constraint.** Locked and bounded choices need their rationale so the next team can relax them when evidence changes, without archaeology.
5. **One spec, many renderings.** Brief, permissions and config generated from one source is the cheapest way to keep humans, agents and runtime enforcement consistent.

## 7. Exercises

1. Turn a backlog ticket into the six surfaces, then run it through `validate()`.
2. Replace three implementation instructions in an existing prompt with one invariant and two examples.
3. Mark every decision in your current agent task. Justify each locked and bounded choice in one line.
4. Add a `journey` proof for a UI claim and confirm that a `unit` proof is rejected for it.
5. Extend `permission_policy()` to emit a pre-tool hook config for your coding agent of choice.

## 8. Key terms

| Term | Meaning |
|---|---|
| Invariant | A condition that must hold in every run |
| Locked / bounded / delegated | Who owns a decision and within what limits |
| Proof layer | The level of evidence a claim needs (unit → audit) |
| Executable spec | A spec that a validator, a permission engine and an agent can all consume |
| Config-owned threshold | A decision boundary stored in config and tuned by evals, never in the prompt |

## 9. Quick check

<details><summary>1. Why can't "may the system write to production?" be delegated even if the schema allows it?</summary>It is irreversible and high-consequence. The validator encodes the product risk that the schema can't see.</details>
<details><summary>2. Is a unit test that mocks the write tool proof that no writes happened?</summary>No. That is an audit-layer claim, and only an audit log of the real run proves it.</details>
<details><summary>3. Where should the "show the guess" threshold live?</summary>In the spec's config block, tuned on a labeled eval set, and never in the prompt.</details>

## References

- Nuseibeh & Easterbrook, *Requirements Engineering: A Roadmap*: https://www.cs.toronto.edu/~sme/papers/2000/ICSE2000.pdf
- Zave & Jackson, *Four Dark Corners of Requirements Engineering*: https://doi.org/10.1145/237432.237434
- Gotel & Finkelstein, *An Analysis of the Requirements Traceability Problem*: https://doi.org/10.1109/ICRE.1994.292398
- AGENTS.md: https://agents.md
- Vercel WorkflowAgent: https://vercel.com/kb/guide/what-is-workflowagent
