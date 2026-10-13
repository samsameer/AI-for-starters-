# 45 · Delegate Agent Work with Isolation and Merge Contracts

> **Short answer:** Parallel agents save wall time only when the work is actually independent. Otherwise they turn one clear task into a coordination problem that fails faster. Delegate a unit only when it has an exclusive set of paths, one proof, frozen shared interfaces, and isolation on three layers: filesystem (a git worktree or a sandbox container), ownership (contracts) and state (separate output dirs). An integrator merges in dependency order, rejects hidden scope expansion, and cancels anything downstream of a rejection. In 2026, worktrees are the local default, and hosted sandboxes such as Cloudflare Sandboxes run coding agents in containers for the cloud case.

**Type:** Learn + Build · **Languages:** Python (stdlib) · **Time:** ~70 min

---

## 1. The problem

More agents are always available, and that is the trap. Typical failures:

- Two workers "own" `app/` and `app/api/`, and the merge picks a winner at random.
- API and docs workers each invent their own error envelope, because nobody froze it first.
- Two workers share one checkout, and one's `git stash` eats the other's work.
- Both write `out/report.json`, and one worker's evidence overwrites the other's.
- A docs worker "helpfully" fixes a bug in `app/api/accounts.py`, and nobody notices until review.

## 2. The concept

### The parallelism test

Delegate only when at least one of these holds:

- Two investigations answer **different** unknowns.
- Two implementations own **disjoint** files and interfaces.
- A reviewer inspects a finished artifact **without changing it**.
- A slow external check runs while local work continues.

Keep work serial when units need the same files, the same unresolved decision or the same mutable environment.

### A work unit is a contract

| Field | Meaning |
|---|---|
| `id`, `owner` | One accountable worker |
| `paths` | Exclusive write ownership (a directory owns everything below it) |
| `depends_on` | Units that must merge first |
| `proof` | Exact evidence handed back to the integrator |
| `interfaces` | Shared contracts it relies on; **must be frozen** before parallel work starts |
| `isolation` | `worktree`, `sandbox` or `shared` (read-only units only) |
| `output_dir` | Where its logs and receipts go; never shared within a wave |

### Three isolation layers

```
 filesystem  ── git worktree per unit (local)  │ sandbox container per unit (cloud)
 ownership   ── disjoint path contracts + frozen interfaces
 state       ── separate output dirs, logs and receipts
```

Filesystem isolation does **not** solve ownership. Two perfectly isolated worktrees can still produce conflicting designs. Freeze the interface first (Lesson 44's "contract first").

### The integrator

```
 wave 1:  research (read-only) │ api (worktree) │ docs (sandbox)
                     │               │               │
                     └──── proofs + handoffs ─────────┘
                                     ▼
            integrator, in dependency order, for each unit:
              changed ⊆ owned paths?   no ──► reject (hidden scope expansion)
              proof exit 0?            no ──► reject
              read-only but changed?   yes ─► reject
              else merge; record new decisions
                                     ▼
            dependents of rejected units ──► cancel
                                     ▼
              final changed set vs union of contracts ──► full gate (Lesson 38)
```

If integration means rewriting most of a worker's output, the decomposition was wrong. Fix the plan, not the merge.

## 3. What changed by Oct 2026

- **Worktrees are the default local isolation.** Coding-agent CLIs run background agents in their own git worktrees and open draft PRs, and several IDE agents do the same. `git worktree add` is the one command to know.
- **Sandboxes went GA for the cloud case.** Cloudflare Sandboxes (GA at Agents Week, Apr 2026) give each agent a persistent, isolated Linux environment behind a zero-trust egress proxy. The `agents` package adds an experimental `ContainerHarness` that runs third-party coding agents (for example Codex) inside Containers. OpenAI Agents SDK sandbox agents (container-backed, with mounts), LangSmith Sandboxes and AWS AgentCore shell sessions cover the same need elsewhere.
- **Dynamic multi-agent workflows** in coding-agent CLIs and hosted agent platforms fan out subagents at run time, and background subagents can now run concurrently. That makes a pre-flight ownership check essential, because fan-out has become cheap.
- **Egress control is part of isolation.** The OWASP Top 10 for Agentic Applications 2026 lists insecure inter-agent communication (ASI07) and cascading failures (ASI08). Per-unit egress allowlists and per-unit credentials limit the blast radius of one compromised worker.
- **2026 update, System One:** the parallelism test is a router. A Jev or Clef `choice` over `{parallel, serial, ask_human}`, with the two unit contracts as `state`, gives a fast first opinion. The deterministic overlap and interface checks still have the final say (Lessons 55–56).

## 4. Build it

`code/main.py` contains:

- `WorkUnit` and `WorkerResult` dataclasses, plus `owns()` / `overlap()` with parent/child path semantics.
- `check()`: duplicate ids, missing proofs and writer path overlap, then per-wave checks for unfrozen shared interfaces, parallel writers without isolation, and shared output dirs.
- `provision()`: the isolation command per unit (a git worktree command, a sandbox description, or a shared read-only checkout). The commands are printed, not executed.
- `integrate()`: dependency-ordered merge with the rejection rules above, cancellation of dependents, and a final changed-set check.

```bash
python3 code/main.py
```

What to look for:

- The bad plan gets four findings: an unfrozen interface, one for each of the two writers sharing a checkout, and a shared output dir.
- Giving the docs unit `app/` blocks on ownership: `app/api / app`.
- The good plan has waves `[['api', 'docs', 'research'], ['integration']]`, with a worktree for `api` and a sandbox for `docs`.
- In run 2 the docs worker edits `app/api/accounts.py`. It is rejected for hidden scope expansion and `integration` is cancelled. Nothing outside the contracts lands.
- The api worker reports a new decision (`409 body uses error.type`). Decisions are recorded, never silently merged into other units.

## 5. Use it in production

| Layer | Oct 2026 options |
|---|---|
| Local filesystem | `git worktree add ../wt-<unit> -b agent/<unit>`; background agents in coding-agent CLIs |
| Cloud filesystem | Cloudflare Sandboxes (with `ContainerHarness` for coding agents), OpenAI Agents SDK sandbox agents, LangSmith Sandboxes, AgentCore shells |
| Ownership | Scope contracts (Lesson 36) generated from `paths`; pre-commit hook rejects writes outside them |
| Interfaces | Contract test merged first (Lesson 44), then frozen by hash |
| Integration | CI job runs `integrate()`-style checks over each branch, then the full gate (Lesson 38) and reviewer (Lesson 39) |
| Orchestration | OpenAI Agents SDK handoffs, ADK 2.x graph workflows, Microsoft Agent Framework workflows, LangGraph |

## 6. Architect's lens

1. **Independence is a property of the contracts, not the infrastructure.** Containers make conflicts invisible until merge. Ownership and frozen interfaces make them impossible.
2. **Parallelism has a coordination tax.** Each extra worker adds a handoff, a proof to read and a merge. If the critical path (Lesson 44) does not get shorter, the extra agent only costs money.
3. **Calibrated autonomy.** Give freedom where evidence and rollback are strong (a docs unit in a sandbox) and require checkpoints where consequences are high (public interfaces, data, permissions). Humans keep the decisions that change behavior, risk or irreversible cost.
4. **Metrics:** rejection rate per unit type, hidden-scope-expansion incidents, integration rework (lines rewritten by the integrator), and wall-time saved vs serial.
5. **Cancellation is a feature.** When a dependency fails, stop the dependents early. Finishing work built on a rejected contract is the most expensive kind of waste.

## 7. Exercises

1. Decompose a real change into two independent units and one integrator. Write down which interface you froze and how.
2. Find a proposed parallel split that only *looks* independent, and name the shared decision.
3. Add a read-only research unit whose output is a fact table with receipts (Lesson 43). How does the integrator check that it changed nothing?
4. Add per-unit egress allowlists to `check()` and block any unit that requests network access its proof does not need.
5. Define a cancellation rule for a worker whose dependency becomes invalid *while it is running*. What does it hand back?

## 8. Key terms

| Term | Meaning |
|---|---|
| Work unit | Delegated contract: owner, exclusive paths, dependencies, proof, interfaces |
| Frozen interface | Shared contract fixed before parallel work begins |
| Worktree | Extra git checkout of the same repo on its own branch |
| Sandbox | Isolated container per agent, typically with controlled egress |
| Hidden scope expansion | A worker changing files outside its contract |
| Merge contract | The integrator's rules for accepting, rejecting and cancelling units |

## 9. Quick check

<details><summary>1. Both workers run in separate worktrees. Can they still conflict?</summary>Yes. Filesystem isolation prevents accidental shared edits, not conflicting designs. Ownership contracts and frozen interfaces prevent those.</details>
<details><summary>2. A docs worker fixes a real bug in an API file. Merge it?</summary>No. Reject it as hidden scope expansion and record the bug as a new decision or task for the owning unit. Otherwise ownership means nothing.</details>
<details><summary>3. Why cancel <code>integration</code> when <code>docs</code> is rejected?</summary>It depends on a unit that did not merge, so any work it does is built on an unaccepted state. Cancelling early saves cost and avoids a misleading green run.</details>

## References

- Git worktree documentation: https://git-scm.com/docs/git-worktree
- Cloudflare Agents Week in review (Sandboxes GA, Code Mode): https://blog.cloudflare.com/agents-week-in-review/
- Cloudflare Sandbox SDK docs: https://developers.cloudflare.com/sandbox/
- Cloudflare `agents` changelog (`ContainerHarness`): https://raw.githubusercontent.com/cloudflare/agents/main/packages/agents/CHANGELOG.md
- OpenAI Agents SDK release notes (sandbox agents): https://raw.githubusercontent.com/openai/openai-agents-python/main/docs/release.md
- Smith, "The Contract Net Protocol" (IEEE ToC 1980): https://doi.org/10.1109/TC.1980.1675516
- Horvitz, "Principles of Mixed-Initiative User Interfaces" (CHI 1999): https://dl.acm.org/doi/10.1145/302979.303030
- OWASP Top 10 for Agentic Applications 2026 (summary): https://www.giskard.ai/knowledge/owasp-top-10-for-agentic-application-2026
