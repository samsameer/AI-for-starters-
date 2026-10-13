# 37 · Runtime Feedback Loops

> **Short answer:** A feedback runner wraps every shell command the agent runs. It records the exact argv, the exit code, the duration and a redacted, truncated tail of stdout and stderr as one JSONL line. The next turn reads that record instead of the model's memory of what "probably happened". No exit code means no progress: the loop must refuse to claim success. Use it for every agent that executes commands, even when the host tool already captures output.

**Type:** Build · **Languages:** Python (stdlib) · **Time:** ~50 min

---

## 1. The problem

The agent writes "running the tests now", and its next message says "all 42 tests pass". Three things can be true at that point:

1. The command never ran. The model predicted the output.
2. The command ran, but the agent never read the result.
3. The agent read the result, but the failure line was cut off by a naive truncation.

All three look identical in the chat. Each one turns into "done" on a task that is not done. The fix is mechanical: every command goes through one runner, and the runner writes a structured record that the next turn, the verification gate (Lesson 38) and the handoff (Lesson 40) all read.

## 2. The concept

```
 agent turn N ──► runner ──► subprocess ──► exit, stdout, stderr, duration
                    │
                    ├── head+tail truncation   (deterministic)
                    ├── redaction on write     (secrets never hit disk)
                    ├── command_id / parent_command_id
                    ▼
            feedback_record.jsonl  (rotated) ──► agent turn N+1
                                              ├─► verification gate (L38)
                                              └─► handoff packet   (L40)
```

### The record

| Field | Why it matters |
|---|---|
| `command` | Exact argv, so no shell-expansion surprises on replay |
| `exit_code` | The only unambiguous success signal. `null` means "unknown", not "fine" |
| `stdout_tail` / `stderr_tail` | Head and tail of each stream, with a `...truncated N lines...` marker |
| `duration_ms` | Surfaces slow probes and runaway processes |
| `agent_note` | What the agent expected, written before it reads the result |
| `command_id` / `parent_command_id` | Turns retries into a visible chain instead of "independent successes" |
| `redaction_hits` | Proof that the redaction pass ran, for the audit |

### Four rules

1. **Truncate deterministically.** Keep a few head lines and more tail lines. The final error and the test summary live at the tail. The same output must always yield the same record.
2. **Redact at write, not at read.** The file on disk is what an attacker reaches. Read-time redaction protects nobody.
3. **Refuse on `null`.** Timeouts and missing binaries get `exit_code: null` and an `error`. The loop may not advance.
4. **Exit 0 is necessary, not sufficient.** Wrappers swallow failures. If the tail says `FAILED` or contains a traceback, treat it as a contradiction and investigate.

### Feedback vs telemetry

| | Feedback record | Telemetry span |
|---|---|---|
| Reader | The next turn of *this* run | Operators across many runs |
| Shape | Project-owned JSONL | OTel GenAI `execute_tool` spans |
| Retention | Task lifetime, rotated | Platform policy |

They share fields. Keep them in different stores and link them with a trace id.

## 3. What changed by Oct 2026

- **Append-only is now a platform requirement, not a style choice.** With preserved thinking on current frontier models, a harness that edits history invalidates thinking blocks. Feedback records are appended and never rewritten. Corrections become new records with a `parent_command_id`.
- **Context editing removes old tool results from the prompt.** Provider-side tool-result clearing and server-side compaction (on-demand since Sep 2026) drop stale tool output from context. A durable feedback file outside the context window is how the gate still sees the evidence.
- **Telemetry linking got a standard.** MCP `2026-07-28` carries `traceparent` in `_meta`. The OTel GenAI conventions moved to `open-telemetry/semantic-conventions-genai` and are still marked Development. Put the trace id in the record and you can join it to the span.
- **Commands run in sandboxes more often than on laptops.** Cloudflare Sandboxes (GA, zero-trust egress proxy), OpenAI Agents SDK sandbox agents, LangSmith Sandboxes and AgentCore shell sessions all return stdout, stderr and exit codes. The runner's record shape is the same everywhere. Only the executor changes.
- **The Agent SDK reports how a run ended.** A terminal-reason field on the agent SDK's result message is the session-level equivalent of `exit_code`. Log it next to your command records.
- **System One hook:** a Jev or Clef `noul` ("does this output report a failure?") can catch failure text that a regex misses, such as a localized message. Keep it *advisory*: it can block advancement, but it can never turn a `null` exit into success.

## 4. Build it

`code/main.py` contains:

- `FeedbackRunner.run()`: wraps `subprocess.run`, handles timeout and missing binary, truncates, redacts, then appends one JSONL line.
- Size-based rotation to `.1`, `.2`, `.3`. `load_all()` reads across rotated files so retry chains survive rotation.
- `retry_chain()`: walks `parent_command_id` back to the first attempt.
- `can_advance()`: the gatekeeper for the next turn. It refuses on `null`, non-zero, or "exit 0 but the tail says FAILED".
- Deterministic `command_id`s (a hash of a counter), so runs are reproducible.

```bash
python3 code/main.py
```

What to look for:

- `noisy` exits 0, but `advance=False`, because the tail kept the `FAILED` line that a head-only cut would have dropped.
- `leak` shows `Bearer [REDACTED]` and `api_key=[REDACTED]` in the stored tail.
- `slow` and `missing` have `exit=None` and are refused.
- The retry chain links `fail` to `retry`. Rotation creates `.1` and `.2`, and every record is still readable.

All files go to a temp directory, so the lesson folder stays clean.

## 5. Use it in production

| Host | What it already captures | What you add |
|---|---|---|
| Coding agent Bash tool / Agent SDK | stdout, stderr, exit, duration | Durable JSONL, redaction on write, lineage. A `PostToolUse` hook is a natural place to append |
| OpenAI Agents SDK sandbox agents | Container command results | Same record shape, written to a mounted volume |
| Cloudflare Sandboxes / `ContainerHarness` | Process output from coding agents such as Codex running in a container | Write records to R2 or Durable Object storage outside the container |
| LangGraph 1.2 nodes | Node state | Persist records outside graph state, so they survive checkpoints and per-node timeouts |
| CI | Job logs | Upload the JSONL as an artifact. Reviewers replay without rerunning |

The runner is a thin layer you own. It survives framework migrations because the record shape belongs to you, not the framework.

## 6. Architect's lens

1. **Bound the cost of evidence.** An untruncated 50 MB log can blow the context budget in one turn. Head+tail with a fixed budget keeps the token cost per command predictable. Measure tokens per record and alert on outliers.
2. **Redaction is a security control, so test it like one.** Keep fixture strings for every secret format your runtime has leaked (bearer tokens, cloud keys, `sk-ant-` style keys). Run them as regression tests, and audit the patterns every quarter.
3. **Lineage is what makes failure history honest.** Without `parent_command_id`, three failed attempts and one success look like "it passed". The reviewer (Lesson 39) and the handoff's `failed_attempts` (Lesson 40) both depend on the chain.
4. **Metric to watch:** the *claim-without-record rate*, meaning how often the agent asserts a result for which no record exists. It should be zero. Any non-zero value is a harness bug, not a model quirk.
5. **Failure mode:** sandbox timeouts that kill the process tree but still return partial output. Keep the partial tail *and* the `null` exit. The partial tail is often the best clue.

## 7. Exercises

1. Add `cwd` and a `trace_id` field. Join one record to an OTel `execute_tool` span by trace id.
2. Add a fixture-driven test for every redaction pattern, including a multi-line private key block.
3. Change the budget to be token-based instead of line-based. Where do very long single lines break the line-based version?
4. Build a "latest non-zero exit" view that the agent loads at the start of every turn. What is the minimum it must show?
5. Replace the `FAILURE_TEXT` regex with a System One `noul` call (Lesson 55 client). Measure disagreements on 50 real CI logs.

## 8. Key terms

| Term | Meaning |
|---|---|
| Feedback record | One JSONL line per command: argv, exit, duration, redacted tails, lineage |
| Head+tail truncation | Deterministic cut that keeps the start and the end of a stream |
| Refuse-on-null | The loop cannot advance when the exit code is unknown |
| Redact-on-write | Secrets are stripped before the record reaches disk |
| Retry chain | Records linked by `parent_command_id`, from the first attempt to the latest |

## 9. Quick check

<details><summary>1. A command times out after printing half its output. What does the record contain, and can the loop advance?</summary>It contains the partial tail, `exit_code: null` and an `error` such as "timeout after 30s". The loop cannot advance, because an unknown exit code is not success.</details>
<details><summary>2. Why keep the tail instead of the head when truncating?</summary>Test runners, compilers and stack traces put the verdict at the end. A head-only cut drops exactly the line the agent needs.</details>
<details><summary>3. Why is the feedback file still needed when the host tool already shows output in context?</summary>Context gets compacted or cleared, and the gate and the next session need the evidence after that. The durable record outlives the context window.</details>

## References

- MCP 2026-07-28 changelog (trace context in `_meta`): https://modelcontextprotocol.io/specification/2026-07-28/changelog
- OTel GenAI semantic conventions: https://opentelemetry.io/docs/specs/semconv/gen-ai/
- Cloudflare Agents Week recap (Sandboxes GA): https://blog.cloudflare.com/agents-week-in-review/
