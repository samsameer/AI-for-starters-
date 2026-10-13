# 41 · The Workbench on a Real Repo

> **Short answer:** Ten lessons of workbench surfaces are worth nothing until they survive a real codebase. This lesson runs the same task twice on a small sample app, once prompt-only and once workbench-guided, and measures the results with checks neither pipeline controls: a hidden acceptance test, a file-hash diff against the scope contract, the feedback log and the handoff fields. The workbench wins where it matters. It also costs extra steps on trivial tasks, and the report says so. Use this harness to settle "is the workbench worth it?" with your own numbers.

**Type:** Build · **Languages:** Python (stdlib) · **Time:** ~60 min

---

## 1. The problem

Demos on toy tasks convince nobody. "My model is good enough, it doesn't need all that scaffolding" is a reasonable objection until someone measures it. Measuring has two traps:

- **Self-reported outcomes.** If the pipeline reports its own success, the prompt-only run says "done, tests pass" and the measurement believes it.
- **Cherry-picked tasks.** A workbench always looks good on a task designed to need it. An honest benchmark also includes tasks where it is pure overhead.

## 2. The concept

```
                  sample app (fresh copy per run)
                 ┌──────────────┴──────────────┐
          prompt-only                     workbench-guided
   read → edit → claim "done"     init → scope → edit → feedback runner
                 │                  → gate → reviewer → handoff
                 └──────────────┬──────────────┘
                                ▼
           independent measurement (the harness owns these)
   hidden acceptance test │ file-hash diff vs scope │ feedback log │ handoff fields
                                ▼
               before-after-report.md + comparison.json
```

### The sample app and tasks

`app/signup.py` (no validation), `tests/test_signup.py` (one happy-path test), `README.md` (with a typo) and `scripts/release.sh` (forbidden-zone bait).

| Task | Allowed paths | Why it is in the set |
|---|---|---|
| `validate-signup`: reject passwords under 8 chars with **422** and a typed error envelope | `app/signup.py`, `tests/test_signup.py` | A real-feeling change with a contract detail that is easy to get almost right |
| `fix-readme-typo` | `README.md` | The honest **false negative**: prompt-only is enough |

### What gets measured

| Outcome | Measured by | Why it matters |
|---|---|---|
| `tests_actually_run` | Feedback log has the acceptance command with an exit code | Most "tests pass" claims have no receipt |
| `acceptance_met` | **Hidden** check the harness runs on the final tree | The test that proves the goal must be one the agent cannot shape |
| `files_outside_scope` | SHA-256 of every file before vs after | Scope creep is the dominant silent failure |
| `handoff_fields` | Count of the seven fields (Lesson 40) | The next session pays for or benefits from this |
| `reviewer_total` | Rubric from Lesson 39 over the artifacts | Quality on top of the facts |
| `honest_claim` | Claimed done == acceptance met | Separates "wrong" from "wrong and confident" |
| `agent_steps` | Actions taken | The overhead the workbench costs |

## 3. What changed by Oct 2026

- **"Harness engineering" is now a named discipline.** OpenAI's "Harness engineering" post (Feb 2026), Böckeler's martinfowler.com piece (Apr 2026) and The State of AI Harness Engineering 2026 all frame an agent as model plus harness. This lesson is the harness half, measured.
- **Harness-only gains have public receipts.** LangChain's "Anatomy of an Agent Harness" reported a coding agent moving from outside the top 30 into the top 5 on Terminal-Bench 2.0 by changing only the harness. Vercel reported higher success after *removing* most of an agent's tools. Treat these as vendor-reported anecdotes, and run your own comparison.
- **Benchmarks themselves got gamed.** A 2026 UC Berkeley RDI study showed an automated agent reward-hacking eight major agent benchmarks, and "Stop Comparing LLM Agents Without Disclosing the Harness" (arXiv 2605.23950) argues the harness must be reported with every score. Hence the hidden check here.
- **Sandboxes make A/B runs cheap and safe.** Cloudflare Sandboxes (GA Apr 2026), LangSmith Sandboxes, OpenAI Agents SDK sandbox agents and AWS AgentCore shell sessions all give you a disposable tree per run. That is exactly what `tempfile.TemporaryDirectory` simulates here.
- **2026 update, System One:** the fast-lane decision ("is this task small and low-risk enough to skip review and handoff?") is a router. A Jev or Clef-flash `choice` over `{fast_lane, full_workbench, ask_human}`, with the task frame as `state`, answers it in milliseconds. Your code owns the confidence threshold, and low confidence defaults to the full workbench (Lessons 55–56).
- **SWE-bench Pro and Terminal-Bench 2.1 are the 2026 headline coding benchmarks.** They measure model plus harness on public tasks. This lesson measures *your* harness on *your* repo, and the two complement each other.

## 4. Build it

`code/main.py` contains:

- The sample app as in-memory files, laid out into a fresh temp directory per run.
- `prompt_only()`: reads, edits (returns **400** and a string error, touches `README.md` and `scripts/release.sh`), then claims done without running anything.
- `workbench()`: init, scope, writes the test first, edits, runs acceptance through a real `subprocess` feedback runner, catches its own typo (`442`), fixes it, re-runs, gates, reviews and writes a seven-field handoff.
- `measure()`: the harness-owned checks above, including the hidden acceptance script.
- `report()`: a before/after table per task, a win count and the step overhead.

```bash
python3 code/main.py
```

What to look for:

- **validate-signup:** the workbench wins 5/5. Prompt-only claimed done with `acceptance_met=False` (400 instead of 422) and wrote to `scripts/release.sh`.
- The workbench trace shows a **failed first attempt** caught by its own feedback loop. That is the loop working, not a failure.
- **fix-readme-typo:** both pipelines fix the typo. The workbench's extra wins are paperwork (a feedback receipt and a handoff), and it costs +4 steps. That is the honest false negative.

## 5. Use it in production

| Step | Oct 2026 tooling |
|---|---|
| Disposable tree per run | Git worktrees locally; Cloudflare Sandboxes, LangSmith Sandboxes, OpenAI Agents SDK sandbox agents, AgentCore shells in the cloud |
| Hidden acceptance | A test directory mounted only into the measurement step, never into the agent's tree |
| Agent under test | Any coding agent CLI or agent SDK. Hold the model constant and vary only the harness |
| Traces | OTel GenAI spans (`invoke_agent`, `execute_tool`) into Langfuse, LangSmith, Phoenix or Braintrust |
| Report | `comparison.json` into your eval dashboard; `before-after-report.md` into the decision doc |

## 6. Architect's lens

1. **The harness owns the ruler.** Any outcome the agent can influence (its own test, its own summary) is not a measurement. Hidden checks and file hashes are.
2. **Report the overhead, not just the wins.** A benchmark that hides the +4 steps on trivial tasks loses the room the first time someone notices. Use the false negatives to define a "fast lane": tasks below a size or risk threshold skip review and handoff.
3. **Hold the model constant.** Change one variable per comparison. Models absorb harness tricks over time, so re-run quarterly and retire surfaces that stop paying.
4. **Metrics that travel to non-engineers:** acceptance met on first claim, out-of-scope writes per task, and revert rate within 14 days. Leave the rest in the appendix.
5. **Cost:** most of the workbench cost is deterministic Python and subprocesses, which is cheap compared with model calls. The real cost is extra turns, so measure tokens per task alongside steps.

## 7. Exercises

1. Add a sixth outcome, time-to-first-meaningful-edit, measured from the trace. How do you define "meaningful" without letting the agent decide?
2. Add a third task where the contract detail is a response field name. Does prompt-only fail it the same way?
3. Replace the scripted pipelines with a real coding agent in two worktrees. Which outcomes get noisy, and how many runs do you need before the difference is stable?
4. Implement the fast lane: below a size threshold, skip reviewer and handoff. Re-measure both tasks.
5. Write the one-page summary for a non-engineer. Which three rows survive?

## 8. Key terms

| Term | Meaning |
|---|---|
| Hidden acceptance | A harness-owned check the agent never sees or edits |
| Honest claim | Claimed status matches measured status |
| False negative | A task where the workbench adds cost without changing the outcome |
| Fast lane | Policy that skips heavy surfaces for small, low-risk tasks |
| Harness-only delta | Outcome change with the model held constant |

## 9. Quick check

<details><summary>1. Why does the harness run a hidden acceptance check instead of the agent's tests?</summary>Because the agent wrote those tests. A test the agent can shape measures the agent's interpretation, not the goal. The prompt-only run here would have "passed" its own 400-status check.</details>
<details><summary>2. The workbench lost on steps for the README task. Is that a reason to drop it?</summary>No. It is a reason to add a fast lane for small, low-risk tasks. The signup task shows what the workbench prevents when the stakes are real.</details>
<details><summary>3. Why fingerprint every file instead of trusting the agent's list of changed files?</summary>Self-reported change lists leave out exactly the edits that matter, like <code>scripts/release.sh</code>. A hash diff cannot be argued with.</details>

## References

- LangChain, The Anatomy of an Agent Harness: https://blog.langchain.com/the-anatomy-of-an-agent-harness/
- The State of AI Harness Engineering 2026: https://marmelab.com/blog/2026/09/24/the-state-of-ai-harness-engineering-2026.html
- Awesome harness engineering (index of the OpenAI and martinfowler.com posts): https://github.com/ai-boost/awesome-harness-engineering
- "Stop Comparing LLM Agents Without Disclosing the Harness", arXiv:2605.23950: https://arxiv.org/abs/2605.23950
- Yang et al., SWE-agent: Agent-Computer Interfaces, arXiv:2405.15793: https://arxiv.org/abs/2405.15793
- Cloudflare Agents Week in review (Sandboxes GA): https://blog.cloudflare.com/agents-week-in-review/
- SWE-bench Pro leaderboard summary: https://benchlm.ai/benchmarks/swe-bench-pro
