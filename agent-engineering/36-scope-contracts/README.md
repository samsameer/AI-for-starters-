# 36 · Scope Contracts and Task Boundaries

> **Short answer:** The model doesn't know where the work ends. A **scope contract** is a per-task file listing allowed and forbidden path globs, acceptance commands, a rollback plan, approval boundaries, and time and network budgets. Enforce it twice: a **pre-action guard** turns each tool call into allow / ask / deny, and a **post-run diff check** compares what actually changed against the promise. A **feature list** bounds scope at the project level: one feature in progress at a time. Contracts merge by least privilege. That turns "stay in scope" from a wish into a check.

**Type:** Build · **Languages:** Python (stdlib) · **Time:** ~50 min

---

## 1. The problem

The task is "import a PDF". The diff touches:

- the importer and its test;
- the router "to wire it up";
- a new settings page "since we'll need one";
- the README;
- the release script;
- a migration.

It also fetched from a paste site and added a dependency without asking. Each step had a plausible reason at the time. Together they make a different change from the one that was approved.

Scope creep is the least-monitored agent failure because the agent narrates every step in good faith. A stricter prompt does not fix it. A **contract on disk** and a **check against it** do.

## 2. The concept

```
 feature_list.json ──(one in_progress)──► scope_contract.json ◄── project contract
                                                 │  merged by least privilege
             ┌───────────────────────────────────┼─────────────────────────────┐
             ▼                                   ▼                             ▼
 pre-action guard (each tool call)        agent loop                 post-run diff check
   allow / ask / deny                                                 findings + verdict
                                                                     archive scope/closed/<task>.json
```

### Contract fields

| Field | Purpose |
|---|---|
| `task_id`, `goal` | Links to the active feature; one verifiable sentence |
| `allowed_files` | Globs the agent may write |
| `forbidden_files` | Globs it must never touch. The negative space is half the contract |
| `hard_paths` / `soft_paths` | Severity by path family: `scripts/**` blocks, `docs/**` is informational |
| `acceptance_criteria` | Commands that must have run (and passed) |
| `rollback_plan` | Concrete operator steps, never "see runbook" |
| `approvals_required` | Enumerated actions that need a human (`add_dependency`, `prod_write`) |
| `time_budget_minutes`, `network_egress` | Wall-clock and host allowlist: `None` = not enforced, `[]` = deny all |
| `violation_budget` | How many `warn` findings are tolerated before the gate refuses |

Use **globs, not raw paths**, so a refactor between sessions doesn't invalidate the contract.

### Least-privilege merge

When a project contract and a task contract both apply:

| Field | Merge rule |
|---|---|
| `allowed_files` | Intersect: both must allow the path |
| `forbidden_files`, `hard_paths` | Union: either can forbid |
| `approvals_required`, `acceptance_criteria` | Accumulate |
| `time_budget_minutes`, `violation_budget` | Minimum |
| `network_egress` | `None` defers to the other side; two lists intersect; `[]` stays deny-all |

### Two altitudes of scope

A task contract bounds **files** for one task. A `feature_list.json` bounds **work** for the project. The agent picks exactly one `todo` feature, marks it `in_progress`, and may not start a second one in the same session. "At most one in progress" is a startup check (Lesson 35). The contract's `task_id` must equal the active feature.

## 3. What changed by Oct 2026

- **Permission policies are allow / ask / deny everywhere.** Coding agents expose per-tool, per-path permission rules. Hosted agent platforms expose policies such as always-allow, always-ask and an "auto" mode in which a classifier decides when to ask. OpenCode uses permission globs. The pre-action guard in this lesson emits exactly those three verdicts, so a contract can compile into any of them.
- **Sandboxes made egress scope real.** Cloudflare Sandboxes route traffic through a zero-trust egress proxy. OpenAI Agents SDK sandbox agents, LangSmith Sandboxes and AWS AgentCore shells all isolate filesystem and network. `network_egress` is now enforceable at the platform level, not just checked afterwards.
- **Background agents need contracts most.** Agents running in their own worktrees, on schedules or from repo events, open draft PRs that nobody watched being written. Put the contract in the PR and run the diff check in CI against the merge diff.
- **Approvals moved into runtimes.** OpenAI Agents SDK tool approval with resumable `RunState`, Google ADK 2.x tool confirmation in workflow nodes, LangGraph interrupts, and durable approvals that can wait hours or days in Vercel Workflow and Temporal (Lesson 29).
- **Scope is a security control.** The OWASP Top 10 for Agentic Applications lists ASI02 Tool Misuse and ASI03 Identity & Privilege Abuse. A March 2026 burst of 30+ MCP-server CVEs, mostly command injection, showed what happens when tools run with ambient authority.

## 4. Build it

`code/main.py`:

1. **Merges** a project contract with the task contract. `deploy/**` is dropped because the project never allowed it. The time budget becomes 30 min, egress becomes `['pypi.org']`, and `migrations/**` joins the forbidden set.
2. **Checks the feature list**: exactly one `in_progress` feature, and it matches the contract.
3. **Runs the pre-action guard** on eight proposed actions. In-scope writes → `allow`; docs and unlisted app files → `ask`; `scripts/**` and `config/prod/**` → `deny`; an unknown host → `deny`; a new dependency → `ask`.
4. **Diff-checks two finished runs.** The clean run passes with one `info` (a docs page). The creeping run is **BLOCKED** with forbidden, hard off-scope, off-scope, acceptance-not-run, time, egress and approval findings.
5. **Archives** both verdicts with the rollback plan under `scope/closed/` (in a temp dir).

It includes a small glob engine with real `**` semantics (`app/**` matches nested paths; `*` stops at `/`).

```bash
python3 code/main.py
```

## 5. Use it in production

| Layer | How the contract shows up |
|---|---|
| Coding agent | Contract compiled into permission rules (allow / ask / deny) plus a pre-tool-use hook (Lesson 33) |
| Sandbox | Mount only allowed paths writable; egress proxy allowlist from `network_egress` |
| Runtime | Agents SDK tool approvals, ADK `RequestInput`, LangGraph interrupts for `ask` verdicts |
| CI | Diff check on the merge diff; block on `block`, comment on `warn` |
| PR | Contract JSON in the PR body or checked in; archived under `scope/closed/` on merge |
| Project | `feature_list.json` with a one-in-progress invariant enforced at init |

## 6. Architect's lens

1. **Violation budgets keep the gate switched on.** A gate that blocks on every docs typo gets disabled within a week. Make `info` and `warn` cheap, keep `block` rare and meaningful, and track *blocks per task* and *budget overruns* as health metrics.
2. **Severity lives in the contract, not the runtime.** Whether `docs/**` is soft or hard depends on the project and the task. Putting it in the contract makes the decision reviewable and lets it vary per task.
3. **Prevent first, then detect.** The pre-action guard stops the forbidden write. The diff check catches what the guard couldn't see, such as a generated file or a command that wrote elsewhere. Run both. **2026 update:** "is this action within the stated goal?" is a judgement the globs can't make, for example a write to `app/router.py`. A System One decision model (Jev or Clef, Lessons 55–56) can turn that `ask` into a calibrated `noul` in tens of milliseconds. Auto-allow above a high threshold, deny below a low one, and send only the middle band to a human. The globs still decide `deny`.
4. **Rollback is part of scope.** If you can't write the rollback plan, the task is too big or too risky to approve. Archived contracts plus rollback plans are what an incident review reads first.
5. **Least privilege compounds.** Every merge can only narrow. If a task needs more than the project allows, change the project contract in its own reviewed PR. Never widen it silently inside a task.

## 7. Exercises

1. Add `max_files_changed` and `max_lines_changed` budgets and report them as `warn` / `block` tiers.
2. Make the guard return `ask` with a structured reason (`rule`, `path`, `suggested_contract_change`) that a human can approve with one click.
3. Derive `allowed_files` from the `goal` with a static rule table (no LLM). Find the first case where it fails.
4. Compile the effective contract into a permission-rules file for a coding agent you use, plus a sandbox egress allowlist.
5. Add a third contract (a security baseline) and confirm the three-way merge is associative.

## 8. Key terms

| Term | Meaning |
|---|---|
| Scope contract | Per-task file of allowed/forbidden globs, acceptance, rollback, approvals, budgets |
| Scope creep | Changes outside the contract made during the task |
| Pre-action guard | Check before each tool call returning allow / ask / deny |
| Diff check | Post-run comparison of touched files, commands and hosts against the contract |
| Least-privilege merge | Combining contracts so the result is never broader than either input |
| Violation budget | Tolerated count of `warn` findings before the gate refuses |
| Feature list | Project backlog file with at most one feature `in_progress` |

## 9. Quick check

<details><summary>1. Why was <code>deploy/**</code> missing from the effective contract?</summary><code>allowed_files</code> merge by intersection. The project contract never allowed <code>deploy/**</code>, so the task contract cannot grant it.</details>
<details><summary>2. <code>app/router.py</code> got <code>ask</code> before the run but only a <code>warn</code> afterwards. Why the difference?</summary>Before the action, the guard can pause and ask a human cheaply. After the fact, an unlisted app file is a warning that counts against the violation budget. Hard paths and forbidden paths block in both places.</details>
<details><summary>3. Why keep <code>network_egress: None</code> different from <code>[]</code>?</summary><code>None</code> means "not enforced by this contract" and defers to the other contract in a merge. <code>[]</code> means deny all hosts and stays deny-all under merge.</details>

## References

- OpenCode agents and permission globs: https://opencode.ai/docs/agents/
- OpenAI Agents SDK docs (guardrails, approvals): https://openai.github.io/openai-agents-python/
- LangGraph human-in-the-loop: https://docs.langchain.com/oss/python/langgraph/overview
- agent-guardrails (violation budgets, merge gates): https://github.com/logi-cmd/agent-guardrails
- OWASP Top 10 for Agentic Applications 2026 summary: https://www.giskard.ai/knowledge/owasp-top-10-for-agentic-application-2026
- MCP breach timeline: https://authzed.com/blog/timeline-mcp-breaches
- Cloudflare Agents Week recap (Sandboxes, egress): https://blog.cloudflare.com/agents-week-in-review/
