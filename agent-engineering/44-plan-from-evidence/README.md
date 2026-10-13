# 44 · Build an Evidence-Backed Execution Plan

> **Short answer:** A plan is not a nicer to-do list. It is a dependency graph in which every work item has a receipt (why this change, here), one proof (what closes it), and explicit dependencies. Validate the graph before anyone edits: no missing evidence, no double proofs, no unknown dependencies, no cycles, and no irreversible step before the uncertainty it depends on is resolved. From there you get execution waves, a critical path, and a resume point that survives a crashed session. Turn the task frame from Lesson 43 into this graph and approve the graph, not the prose.

**Type:** Learn + Build · **Languages:** Python (stdlib) · **Time:** ~65 min

---

## 1. The problem

Weak agent plans restate the request in the future tense:

1. Update the API.
2. Add tests.
3. Update documentation.

Nothing in that list says what was found, why those files, what has to be true first, what can run in parallel, or what proves each step. An agent can follow it faithfully and still produce rework. A worse plan does an irreversible thing (a data backfill, a published API change) before anyone has decided the question it depends on.

## 2. The concept

```
              contract (failing test first) ─┬──► implementation ──► backfill* ──► integration
                                             └──► docs ─────────────────────────────┘
   merge-policy (human decision) ───────────────────────────────► backfill*
                                              * irreversible: needs "duplicate winner policy" resolved upstream
```

### Five commitments per work item

| Field | Purpose |
|---|---|
| `id` | Stable reference for dependencies, receipts and handoff |
| `change` | The smallest behavior or contract change |
| `evidence` | Receipts (`path:line`) that justify *this* change |
| `depends_on` | What must be true first |
| `proof` | Exactly one check that closes the item |

Plus two risk fields: `irreversible` with `needs_resolved` (which unknowns must be settled upstream), and `resolves` on the items that settle them.

### Validation rules

| Rule | Mechanical? |
|---|---|
| Unique ids | yes |
| Every item has evidence | yes |
| Exactly one proof per item (split `a && b`) | yes |
| Dependencies exist | yes |
| No cycles (the report names the cycle) | yes |
| Irreversible items come after the item that resolves their uncertainty | yes, once you declare `needs_resolved` / `resolves`. Declaring them is the judgment part |

### Contract first

When several surfaces share a behavior, fix the behavior first (here: a failing test that pins 409 plus a typed envelope). Implementation and docs can then run in parallel against one contract instead of inventing two.

### Evidence must be able to change the plan

If a receipt could never change the plan, it is decoration. In the demo, finding `normalize_email()` already in the repo **removes** a work item, rewires its dependents and shortens the critical path from 6.0h to 4.5h.

### Design for interruption

Store the plan next to the work. An item is done only when its proof receipt shows exit 0, not when a box is ticked in chat. Any session can then compute the next safe items.

## 3. What changed by Oct 2026

- **Graph-based workflow engines went mainstream.** Google ADK 2.0 (GA May 2026) ships a unified graph workflow engine that mixes deterministic and model-led steps. LangGraph 1.2 adds per-node timeouts. Vercel `WorkflowAgent` and Temporal make each step durable. A validated plan maps directly onto any of them.
- **Dynamic multi-agent workflows** in coding-agent CLIs and hosted agent platforms fan out work from a plan at run time. That makes a validated dependency graph a *safety* requirement, not a nicety: waves are what you are allowed to parallelize (Lesson 45).
- **Task budgets and effort controls** on frontier model APIs let you give each item a token or effort budget. The `hours` field here stands in for whichever budget you track.
- **Durable approvals make human items real nodes.** `merge-policy` is a human decision node, collected through MCP `input_required`, ADK `RequestInput` or a durable workflow approval, and the irreversible step waits on it.
- **2026 update, System One:** "is this item irreversible?" and "does this receipt support this change?" are typed questions. A Jev or Clef `noul` per item flags likely-irreversible steps that nobody marked, and your code turns a high P(yes) into a required `needs_resolved` (Lessons 55–56).

## 4. Build it

`code/main.py` contains:

- `WorkItem`, a frozen dataclass with the fields above.
- `validate()`: all six rules. `find_cycle()` returns the actual cycle path, and `ancestors()` drives the irreversibility check.
- `waves()` (Kahn's algorithm) and `critical_path()` (CPM-style longest path over hours).
- `apply_evidence()`: drop an item that new evidence makes unnecessary, rewire dependents and append the receipt.
- `next_safe()`: resume from proof receipts, where only exit 0 counts as done.
- Five broken plans, each refused for a different reason, and the plan document written to a temp `outputs/evidence-plan.json`.

```bash
python3 code/main.py
```

What to look for:

- Each broken plan fails with exactly one targeted message. In the cycle message, `a -> b` means "a depends on b".
- v1 has 5 waves and a 6.0h critical path. After the `normalize_email` evidence, v2 has 4 waves and 4.5h.
- `backfill` never appears before `merge-policy` has resolved "duplicate winner policy".
- Resume: `implementation` has a receipt with exit 1, so it is **not** done. The next safe items are `docs` and a retry of `implementation`.

## 5. Use it in production

| Need | Oct 2026 options |
|---|---|
| Plan format | JSON next to the work (source of truth), rendered to Markdown for review |
| Execution | LangGraph 1.2, ADK 2.x graph workflows, Microsoft Agent Framework workflows, Vercel `WorkflowAgent`, Temporal |
| Human nodes | MCP `input_required` (MRTR), ADK `RequestInput`, durable approvals |
| Receipts | Feedback runner records (Lesson 37) keyed by item id |
| Review | Approve the plan in plan mode or the PR before any edit lands |

## 6. Architect's lens

1. **Order by risk, not by habit.** Boehm's spiral model said it in 1986: resolve the riskiest uncertainty first. In agent plans the riskiest items are usually contract decisions and irreversible operations.
2. **The critical path is your schedule.** Parallelism off the critical path saves nothing. Spend extra agents, or a stronger model, on critical-path items first.
3. **One proof per item keeps receipts unambiguous.** "Tests and lint passed" as one receipt hides which one failed on the retry.
4. **Metrics:** plan validation failures caught before edit, items dropped or added by evidence (a healthy plan changes), replans per task, and critical-path estimate vs actual.
5. **Failure mode: plans that never change.** If evidence never removes or adds an item, the agent is not reading the repo; it is decorating a plan it had already decided on.

## 7. Exercises

1. Add a migration item that requires explicit human approval, and make the validator refuse it without an upstream approval node.
2. Create a cycle in a real plan and name the hidden product disagreement behind it.
3. Split an item that has two proofs, and check whether the waves change.
4. Add slack time to `critical_path()` (latest start minus earliest start) and print which items can slip without delaying the end.
5. Render the plan as Markdown while keeping JSON as the only source of truth. Add a test that fails if they disagree.

## 8. Key terms

| Term | Meaning |
|---|---|
| Work item | Smallest change with evidence, dependencies and exactly one proof |
| Execution wave | Set of items whose dependencies are all complete; safe to run together |
| Critical path | Longest dependency chain by estimated effort; sets the minimum duration |
| Irreversible item | A step that cannot be cleanly undone; must follow its uncertainty's resolution |
| Proof receipt | Recorded exit code of an item's proof; only exit 0 means done |

## 9. Quick check

<details><summary>1. Why must a validator check irreversibility using dependencies rather than list order?</summary>Agents and workflow engines execute by dependency, not by the order items were written. If the resolving item is not an ancestor, the irreversible step can legally run first.</details>
<details><summary>2. New evidence shows a planned helper already exists. What should happen to the plan?</summary>Drop the item, rewire its dependents onto its own dependencies, attach the receipt, and recompute waves and the critical path. Evidence that cannot change the plan is not evidence.</details>
<details><summary>3. The session crashed after <code>implementation</code> ran with exit 1. Is it done?</summary>No. Only a proof receipt with exit 0 completes an item, so it comes back as a next safe item alongside the other unblocked work.</details>

## References

- Nuseibeh and Easterbrook, "Requirements Engineering: A Roadmap" (ICSE 2000): https://www.cs.toronto.edu/~sme/papers/2000/ICSE2000.pdf
- Boehm, "A Spiral Model of Software Development and Enhancement" (1986/1988): https://dl.acm.org/doi/10.1145/12944.12948
- Kelley and Walker, "Critical-Path Planning and Scheduling" (1959): https://dl.acm.org/doi/10.1145/1460299.1460318
- Kahn, "Topological sorting of large networks" (CACM 1962): https://dl.acm.org/doi/10.1145/368996.369025
- Google ADK changelog (2.x graph workflows): https://raw.githubusercontent.com/google/adk-python/main/CHANGELOG.md
- Vercel, What is WorkflowAgent: https://vercel.com/kb/guide/what-is-workflowagent
