# 43 · Frame the Task Before the Agent Writes Code

> **Short answer:** A coding agent implements a vague task exactly as fast as a clear one, so the vague one is far more expensive. Before any edit, write a one-screen **task frame**: an observable goal, repository facts *with receipts* (`path:line`), allowed and forbidden paths, acceptance evidence, and every unknown classified as discoverable, decidable, human or deferred. Investigate what the repo can answer, ask the human only what it cannot, and start coding when the frame validates.

**Type:** Learn + Build · **Languages:** Python (stdlib) · **Time:** ~60 min

---

## 1. The problem

"Add duplicate email protection" sounds specific. It isn't:

- Does uniqueness live in the API, the domain service or the database?
- Is the comparison case-sensitive?
- Which error shape is already public?
- Is a migration allowed?
- Which test proves it?

A capable agent fills every gap with a plausible choice. That is the dangerous case. The result is clean, tested and incompatible with the system: a migration nobody approved, a 400 where the API uses 409, a case-sensitive check next to a `normalize_email()` helper that already existed.

The first unit of agent work is not an edit. It is a frame backed by evidence.

## 2. The concept

```
 request ──► reconnaissance (search for constraints, not the whole repo)
                      │
                      ▼
                 task frame ──► validate ── issues? ──► BLOCKED (fix the frame)
                      │
          ┌───────────┼──────────────┬──────────────┐
   discoverable    human         decidable       deferred
   unknowns left?  unknowns?     (agent chooses)  (→ non-goals)
          │           │
     INVESTIGATE   NEEDS_HUMAN ───────────────► READY ──► plan (Lesson 44)
```

### The frame

| Field | Question | Validation |
|---|---|---|
| Goal | What observable behavior changes? | Not empty. Not "edit `x.py`" |
| Repository facts | What did you verify? | Each has a `path:line` receipt that resolves *and* supports the claim |
| Allowed paths | Where may the change land? | Not empty. No overlap with forbidden, globs included |
| Forbidden paths | What must not change? | Not empty: name the negative space |
| Acceptance | What proves the goal? | Not empty. Not "tests pass" |
| Unknowns | What has not been earned yet? | Each is classified into one of four kinds |

### Four kinds of unknown

| Kind | Meaning | Agent behavior |
|---|---|---|
| **Discoverable** | The repo or running system can answer it | Investigate now, then turn it into a fact with a receipt |
| **Decidable** | The task contract gives the agent authority | Choose, and record the choice |
| **Human** | It changes product behavior, cost, risk or public compatibility | Stop before the choice gets buried in code |
| **Deferred** | Out of this slice | Move it to non-goals |

An unknown is a controlled gap. An assumption is an uncontrolled answer to it.

### Reconnaissance is a search for constraints

Look for: current behavior and its caller, the closest test, the public contract, instruction files (AGENTS.md) that govern the path, the build and verify commands, and one similar past change. **Stop** when every planned decision is backed by evidence, delegated, or listed as an unknown. Reading past that point is usually avoidance.

## 3. What changed by Oct 2026

- **Planning modes and plan approval are standard UX.** Coding-agent CLIs and IDE agents (via the Agent Client Protocol in Zed and JetBrains) offer a plan or "ask" mode before edits. A task frame is what you should approve, not a vague promise to be careful.
- **AGENTS.md is the default place for path rules.** Instruction files are read by most coding agents, so a forbidden path like `migrations/` usually already has a receipt there, as in the demo.
- **Human checkpoints are protocol-level.** MCP `2026-07-28` returns `input_required` through Multi Round-Trip Requests (elicitation now flows through MRTR). Google ADK 2.x has `RequestInput` in workflow nodes, and durable approvals (Vercel `WorkflowAgent`, Temporal) can wait days. A `human` unknown maps directly onto these.
- **Harness engineering made "frame first" explicit.** The planner/generator/evaluator harness pattern and the 2026 harness-engineering write-ups all put a written spec ahead of the generator.
- **2026 update, System One:** classifying an unknown is a typed decision. A Jev or Clef `choice` over `{discoverable, decidable, human, deferred}`, with the question and frame as `state`, gives calibrated probabilities. Route anything with low confidence to `human` in code (Lessons 55–56).

## 4. Build it

`code/main.py` contains:

- `REPO`: a tiny in-memory repository used to **check receipts**, not just to require them.
- `TaskFrame`, `RepositoryFact(claim, receipt, expect)` and `Unknown(question, kind, probe)`.
- `validate()`: file-shaped goals, empty or vague acceptance, missing negative space, glob-aware path overlap, receipts that don't resolve or that contradict the claim, and invalid unknown kinds.
- `readiness()`: `BLOCKED` → `INVESTIGATE` → `NEEDS_HUMAN` → `READY`. Discoverable comes before human, so you never ask a person what the repo can tell you.
- `investigate()` turns discoverable unknowns into facts with receipts. `human_decides()` moves a human answer into non-goals.
- Five broken variants, each refused for a different reason, and a rendered `task-frame.md` written to a temp dir.

```bash
python3 code/main.py
```

What to look for:

- The frame goes v1 `INVESTIGATE` → v2 `NEEDS_HUMAN` (case-insensitivity answered by `app/accounts.py:4`, `normalize_email`) → v3 `READY` (the human said "no migration in this slice").
- "receipt contradicts claim" is the important refusal. The receipt exists, but the line says `201`, not `200`. Requiring receipts is not enough; you have to read them.
- The rendered frame is 27 lines. If yours does not fit on one screen, it probably contains several tasks.

## 5. Use it in production

| Step | Practice (Oct 2026) |
|---|---|
| Recon | Let the agent search (grep, code search, LSP) in plan mode with read-only tools |
| Frame | Store `task-frame.md` beside the work, not in chat. Lesson 34's state points at it |
| Receipts | Have a hook re-resolve every `path:line` at approval time; stale receipts block |
| Human unknowns | Surface them through your approval channel: PR comment, MCP `input_required`, ADK `RequestInput`, durable workflow approval |
| Scope | The frame's allowed and forbidden paths become the scope contract from Lesson 36 |

## 6. Architect's lens

1. **Receipts rot.** A `path:line` from yesterday may point at a different line today. Re-resolve at approval time, and prefer receipts that include an expected substring, as the demo does.
2. **The cost curve is front-loaded.** Ten minutes of framing is cheap compared with a merged-then-reverted migration. Track *rework rate* (tasks reopened after "done") before and after you adopt frames.
3. **Watch for over-framing.** Frames longer than one screen, or reconnaissance that never ends, are a smell. Split the task or set a time box for recon.
4. **Human unknowns are a product signal.** If the same kind of question (API shape, migration policy) keeps escalating, write the answer into AGENTS.md so it becomes a fact next time.
5. **Metrics:** share of tasks that reach `READY` without a human, human questions per task, receipt-failure rate at approval, and rework rate.

## 7. Exercises

1. Frame a real bug from one of your repos without proposing a solution. How many facts had receipts on the first draft?
2. Find a claim in your frame that is really an assumption, and replace it with a receipt or an unknown.
3. Add a `human` unknown whose answer would change the public contract, and route it through your team's real approval channel.
4. Extend `overlaps()` to handle `**/*.sql`-style patterns in the allowed list as well as the forbidden list.
5. Replace the unknown classifier with a System One `choice` call and compare it with your own labels on ten unknowns.

## 8. Key terms

| Term | Meaning |
|---|---|
| Task frame | One-screen contract: goal, facts, paths, acceptance, unknowns |
| Receipt | `path:line` (or command output) that a fact can be checked against |
| Negative space | Forbidden paths and non-goals, stated explicitly |
| Discoverable unknown | A gap the repo or system can close; investigate before asking |
| Human unknown | A gap that changes behavior, cost, risk or compatibility; stop and ask |

## 9. Quick check

<details><summary>1. Why is "tests pass" rejected as acceptance?</summary>It names no test and no claim. Acceptance must say which check proves which behavior, for example a focused test command plus a scope check.</details>
<details><summary>2. Why investigate discoverable unknowns before asking the human?</summary>The human's time is the scarcest resource in the loop. Asking what the repo already answers (like the existing <code>normalize_email</code>) wastes it and erodes trust in the agent.</details>
<details><summary>3. A fact has a receipt that resolves. Can it still block?</summary>Yes, if the line does not support the claim. The demo's "signup returns 200" points at a line that returns 201.</details>

## References

- Nuseibeh and Easterbrook, "Requirements Engineering: A Roadmap" (ICSE 2000): https://www.cs.toronto.edu/~sme/papers/2000/ICSE2000.pdf
- Yang et al., "SWE-agent: Agent-Computer Interfaces Enable Automated Software Engineering", arXiv:2405.15793: https://arxiv.org/abs/2405.15793
- AGENTS.md specification: https://agents.md/
- MCP 2026-07-28 changelog (MRTR, `input_required`): https://modelcontextprotocol.io/specification/2026-07-28/changelog
- Böckeler, harness engineering for coding agent users (via the awesome list): https://github.com/ai-boost/awesome-harness-engineering
- Agent Client Protocol: https://www.jetbrains.com/acp/
