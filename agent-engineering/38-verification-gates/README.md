# 38 · Verification Gates

> **Short answer:** A verification gate is a deterministic function over the artifacts an agent has already produced: the feedback log, the scope report, the rule report and the coverage report. It answers one question: is this task actually done? Block findings stop `passed: true`, and only a signed human override can lift them. The agent never marks its own work as complete. Put the gate at the pre-merge or pre-handoff edge of every agent workflow.

**Type:** Build · **Languages:** Python (stdlib) · **Time:** ~55 min

---

## 1. The problem

Agents close tasks too easily. Three failure shapes account for most false "done" claims:

| Claim | What actually happened |
|---|---|
| "Looks good." | The model read its own diff and liked it |
| "Tests pass." | No record shows the acceptance command running |
| "Acceptance met." | The criteria were read loosely enough to fit anything |

The fix is not a better prompt. It is a gate that reads evidence, lives in version control, runs in CI and cannot be talked into a different answer.

## 2. The concept

```
 feedback_record.jsonl (L37) ─┐
 scope_report.json     (L36) ─┤
 rule_report.json      (L33) ─┼──► verify() ──► outputs/verification/<task>.json
 coverage_report.json        ─┤        │
 advisory signals (System One)┘        ├── passed: true  ──► reviewer agent (L39)
                                       └── passed: false ──► refuse "done", surface to human
```

### Checks and severities

| Check | Source | Severity |
|---|---|---|
| Every acceptance command ran | feedback log | block |
| Latest run of each acceptance command exited 0 | feedback log | block |
| No `null` exit codes | feedback log | block |
| No forbidden writes | scope report | block |
| Off-scope writes | scope report | warn |
| Every block-severity rule passed | rule report | block |
| Coverage at or above the floor | coverage report | block |
| Coverage dropped more than 1 point since last merge | coverage report | block |
| Coverage report missing | — | warn |
| Probabilistic signals (System One, LLM) | advisory inputs | advisory, never block |

`warn` annotates the verdict. `block` prevents `passed: true`. `--strict` promotes every warn to block. Turn it on for release branches and post-incident work, not everywhere, or the friction pushes people to work around the gate.

### Three non-negotiables

1. **Deterministic.** The same artifacts always produce the same verdict. No LLM gets a vote on status. LLM judgment belongs to the reviewer (Lesson 39).
2. **One report path.** `outputs/verification/<task_id>.json` is read by CI, the reviewer, the handoff generator and humans. A second path creates a second truth.
3. **Signed overrides only.** An override names the finding code, the reason, the human and the **head commit**. It is HMAC-signed and appended to an audit log. An override for an older commit is void, because the code it approved is gone.

## 3. What changed by Oct 2026

- **Harness engineering made the gate a first-class part of the harness.** OpenAI's "Harness engineering" post (Feb 2026) and Böckeler's martinfowler.com piece (Apr 2026) describe agent workflows as model plus harness. Planner/generator/evaluator harness designs (Mar 2026) separates the evaluator from the generator. The gate is the cheapest, most deterministic evaluator you have.
- **Verification ships as skills and hooks.** Coding agents bundle skills such as `/verify` and `/run`, and custom slash commands are now Skills. Hooks run deterministic checks on tool events. The agent can *call* verification, but the gate's verdict must still come from code it cannot edit.
- **Hosted graders arrived.** Hosted agent platforms add *Outcomes* with a grader rubric, and LangChain Deep Agents 0.7 has `RubricMiddleware`. Both are rubric graders, so they go on the reviewer side. Keep exit codes and scope in your own deterministic gate.
- **Durable approvals make signed overrides practical.** Vercel's `WorkflowAgent` supports approvals that wait hours or days. ADK 2.x adds tool confirmation in workflow nodes (`RequestInput`). MCP `2026-07-28` returns `input_required` through Multi Round-Trip Requests. Each one is a place to collect the human override, which you still sign and log yourself.
- **Benchmarks showed why self-reported success is not evidence.** A UC Berkeley RDI study showed an automated agent reward-hacking 8 major agent benchmarks. The defense is the same one this gate uses: check artifacts, not claims.
- **System One hook:** a Jev or Clef `noul` such as "does this diff address the stated goal?" costs milliseconds. Feed it in as an `advisory` finding that the reviewer reads. Never let a probability flip `passed`.

## 4. Build it

`code/main.py` contains:

- `Finding`, `Artifacts` and `Verdict` dataclasses.
- Four pure check functions: acceptance, scope, rules and coverage. Each one returns findings.
- `verify(art, strict)`: combines the findings, applies strict mode and appends advisory signals as `advisory` severity.
- `make_override()` / `apply_overrides()`: HMAC-signed overrides bound to task id and head commit. Forged, stale-commit and agent-authored entries are rejected.
- Four scenarios: a clean pass, scope creep plus a coverage collapse, a missing acceptance run, and a retry that passed with an off-scope doc edit.

```bash
python3 code/main.py
python3 code/main.py --strict
VERIFY_OVERRIDE_SECRET=... python3 code/main.py
```

What to look for:

- T-001 passes with a minor-drop warning.
- T-002 has five findings, four of them blocking.
- T-003 never ran the acceptance command, so it blocks even though lint passed.
- T-004 passes normally but fails in strict mode. Only the correctly signed override for commit `d4e5f6a` restores it.
- Reports go to a temp `outputs/verification/` directory. Without the env var, a clearly labelled demo secret is used.

## 5. Use it in production

| Layer | Mechanism (Oct 2026) | Role |
|---|---|---|
| Pre-commit | git hook | Cheap and non-bypassable by the model |
| In-loop | Coding agent hooks, Agent SDK `can_use_tool`, OpenAI Agents SDK guardrails | Stop bad actions before they land |
| Pre-handoff | Gate call in the session-end hook | No green verdict, no handoff (Lesson 40) |
| Pre-merge | CI status check reading `outputs/verification/<task>.json` | Merge protection requires `passed: true` |
| Background agents | Coding agent background agents open draft PRs; Routines run on schedules or GitHub events | The same CI gate decides whether the draft becomes ready |

Defense in depth works because every layer is deterministic. A failure in one layer is caught by the next.

## 6. Architect's lens

1. **Separate "did it work" from "was it good".** Verifiable signals (exit codes, schemas, coverage) feed the gate. Rubric judgments feed the reviewer. Mixing them makes both signals noisy, and a flaky LLM vote turns the gate into a coin flip.
2. **Bind everything to the commit.** Verdicts, overrides and coverage baselines all carry `head_commit`. A verdict for a commit that no longer exists means nothing.
3. **Watch for gaming.** Agents under pressure delete failing tests, which makes coverage drop and turns the run green. The regression check is there for this case. Also flag edits to test files that are not in the task's allowed paths.
4. **Metrics:** gate pass rate, override rate per finding code, and *escape rate* (gated-green tasks later reverted). A rising override rate means the rule is wrong or the scope is too tight. Fix the rule; don't normalize the override.
5. **Cost:** the gate is pure Python over JSON and costs nothing compared with an LLM call. Run it on every attempt, not only at the end.

## 7. Exercises

1. Add a `tests.edited_outside_scope` block finding when a test file changes but is not in `allowed_files`.
2. Emit a Markdown summary next to the JSON. Decide which three fields a reviewer must see first.
3. Store overrides in an append-only `overrides.jsonl` and verify the whole file at gate time. What happens when one line has been edited?
4. Wire a real Jev or Clef `noul` (Lessons 55–56) as the advisory signal. Log it, and after a month check whether low P(yes) predicts reviewer hard-fails.
5. Run the gate on ten real agent PRs. Count true findings versus noise and tune severities.

## 8. Key terms

| Term | Meaning |
|---|---|
| Verification gate | Deterministic function from workbench artifacts to a pass/fail verdict |
| Block / warn / advisory | Stops `passed` / annotates / informs the reviewer only |
| Strict mode | Promotes every warn to block for high-stakes branches |
| Signed override | HMAC-signed human waiver bound to finding, task and head commit |
| Escape rate | Share of gated-green work later reverted or hot-fixed |

## 9. Quick check

<details><summary>1. Why can't an LLM judge decide <code>passed</code>?</summary>It is not deterministic and it can be persuaded. Status needs the same answer for the same evidence every time. Put LLM judgment in the reviewer, where nuance is the goal.</details>
<details><summary>2. An override was signed for commit A. The agent pushes commit B. Is the finding still waived?</summary>No. The override is bound to commit A's code. B needs a new verdict and, if needed, a new signed override.</details>
<details><summary>3. The acceptance command failed once, then passed on retry. Does the gate block?</summary>Not in this design: the latest run for that command decides. The failed attempt stays in the feedback log and shows up as a failed attempt in the handoff.</details>

## References

- OpenAI, "Harness engineering: leveraging Codex in an agent-first world" (Feb 2026), and Böckeler, "Harness engineering for coding agent users" (martinfowler.com, Apr 2026). Index: https://github.com/ai-boost/awesome-harness-engineering
- The State of AI Harness Engineering 2026: https://marmelab.com/blog/2026/09/24/the-state-of-ai-harness-engineering-2026.html
- OpenAI Agents SDK guardrails: https://openai.github.io/openai-agents-python/guardrails/
- MCP 2026-07-28 changelog (MRTR / `input_required`): https://modelcontextprotocol.io/specification/2026-07-28/changelog
