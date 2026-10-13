# 34 · Repo Memory and Durable State

> **Short answer:** Chat history is volatile. The repo is durable. Store agent state in versioned files under a **schema**, write them **atomically**, record every change in an **append-only event log**, and refuse any write that breaks the contract. Keep the conversation itself **append-only** too. In 2026, editing past messages throws away prompt-cache hits and preserved reasoning. Repo memory is what lets the next session, the next agent and the reviewer all read the same truth.

**Type:** Build · **Languages:** Python (stdlib) · **Time:** ~60 min

---

## 1. The problem

A session ends and the chat closes. The next session asks where to start, reads stale notes, and redoes finished work. Worse, it rewrites a finished file because nothing said it was finished.

Teams that do keep a state file hit the next set of bugs:

- A crash mid-write leaves half a JSON file, and the next session resumes from garbage with no warning.
- Every agent invents new fields, so `null` shows up where a list was expected.
- A schema change silently breaks files from last month.
- Someone "cleans up" the transcript by editing earlier turns, and cost and latency jump because the cached prefix no longer matches.

## 2. The concept

```
 agent turn ──► event {seq, op, key, value} ──► validate against schema ──► append to state.events.jsonl
                                                   │ refuse on violation          │
                                                   ▼                              ▼
                                         periodic snapshot ──atomic write──► agent_state.json (last_seq = N)
 resume: load snapshot ─► migrate if older version ─► validate ─► replay events with seq > last_seq
```

### What belongs in repo memory

| Repo memory (durable) | Telemetry or nowhere |
|---|---|
| Active task id, touched files | Raw chat transcripts |
| Assumptions, risks, next action | Token-level reasoning traces |
| Paths to artifacts (`artifacts/run-0004.log`) | The artifacts themselves (CSVs, logs, blobs) |
| Schema version, last applied event seq | Sentiment ("the user seemed upset") |
| | Secrets, tokens, PII |

The test is **durability**: would this fact still help a CI rerun three months from now? If yes, put it in the repo. If no, send it to traces.

### Four mechanisms

1. **Schema-first.** A JSON Schema with required keys, enums, patterns, and no `null` where an array is expected. A bad write is refused at the boundary, not discovered later.
2. **Atomic writes.** `mkstemp` in the same directory, write, `fsync`, then `os.replace`. A crash leaves either the old file or the new one, never half of each.
3. **Event log plus snapshot.** Append every mutation to `state.events.jsonl`. Snapshot now and then, storing `last_seq`. To resume, load the snapshot and replay newer events. You get an audit trail and crash recovery from one design (the same idea as a database WAL).
4. **Versioned migrations.** `schema_version` is the contract. Known old versions are migrated on load. Unknown versions, including *newer* ones, are refused.

### Append-only history

Treat the transcript the same way: **append, never edit**. Providers cache the longest unchanged prefix of the request. When you edit message 2, everything after it becomes a cache miss. Current frontier models also preserve reasoning across turns, and editing history invalidates that. To shrink context, use compaction (server-side or your own summary *appended* as a new message), not rewriting.

## 3. What changed by Oct 2026

- **Append-only harnesses are now a requirement, not a style.** Frontier provider APIs preserve reasoning blocks across turns and recommend append-only histories. Editing earlier turns invalidates them. Prompt caching depends on stable prefixes, and MCP's `2026-07-28` revision even makes `tools/list` ordering deterministic so tool definitions cache well.
- **Compaction moved server-side.** Major provider APIs offer server-side compaction (including on-demand compaction) and context-editing strategies that clear old tool results. OpenAI documented "Shell + Skills + Compaction" for long-running agents. All of these work *on top of* an append-only log.
- **Managed memory stores.** Hosted agent platforms now offer memory stores, and a client-side memory tool lets the agent read and write files you control. Google ADK added a SQLite memory service. AWS AgentCore Memory added `IngestData`.
- **Memory libraries matured.** Mem0 OSS 2.2.x (ADD-only extraction since the v2 SDK), Graphiti 0.31 (temporal knowledge graph with validity intervals), Letta's TypeScript-first SDK, and LangSmith managed user-level memory. These are *semantic* memory. Repo state is *operational* memory, and you need both.
- **Checkpoints and resumable runs everywhere.** LangGraph 1.2 checkpointers, OpenAI Agents SDK resumable `RunState` and sessions, and agent SDK session stores that can resume or fork at an earlier entry. Your state schema is what you read by hand when those break.
- **Memory poisoning is an OWASP top-10 risk.** The OWASP Top 10 for Agentic Applications lists ASI06, Memory & Context Poisoning. Schema validation plus "no free-text blobs in state" is the first defence.

## 4. Build it

`code/main.py` works in a temp directory:

1. **Migrates** a legacy v1 file (`blockers`, `active_task_id: null`) to v2 (`risks`, empty string, `last_seq`).
2. **Records** five events to `state.events.jsonl`. Each one is validated *before* it is appended.
3. **Crashes a snapshot** just before the rename. The old file is unchanged and no temp file is left behind.
4. **Recovers** by loading the snapshot (`last_seq=0`) and replaying events 1–5. The result equals the in-memory state.
5. **Refuses four bad writes**: a malformed task id, `null` for an array, a transcript stuffed into state, and an inline CSV instead of an artifact path.
6. **Refuses a future file** (`schema_version: 9`) instead of guessing.
7. **Measures transcript discipline**: append-only reuses 4/4 prefix messages, editing turn 2 reuses 1/4.

```bash
python3 code/main.py
```

## 5. Use it in production

| Need | Oct 2026 options |
|---|---|
| Graph or run checkpoints | LangGraph checkpointers (SQLite / Postgres), OpenAI Agents SDK sessions and `RunState`, Microsoft Agent Framework checkpoints |
| Durable step journal | Temporal, Vercel Workflow, Restate (Lesson 29) |
| Semantic long-term memory | Mem0, Graphiti / Zep, Letta, ADK memory services, hosted memory stores |
| Repo-level operational state | `agent_state.json` + `state.events.jsonl` under schema, in git |
| Context size control | Server-side compaction, context editing, appended summaries |
| Schema validation | `jsonschema` / Pydantic in production; the stdlib subset here for learning |

## 6. Architect's lens

1. **Separate the three memories.** *Operational* (where am I in this task) goes in repo files. *Semantic* (what do I know about this user or codebase) goes in a memory store. *Episodic* (what exactly happened) goes in traces and the event log. Mixing them creates state files that are too big, too slow and too risky.
2. **Atomic rename is necessary, not sufficient.** It prevents torn files, but two agents writing the same state still race. Use a lock, compare-and-swap on `last_seq`, or a single writer per task. Background agents in separate worktrees avoid most of this by design.
3. **Idempotency keys for side effects.** If an agent crashes after a tool call but before it records the result, recovery will retry the call. Log the call id first (`pending_calls.jsonl`) and skip it on replay if the result exists. Reads are safe to retry. Emails, charges and uploads are not.
4. **Cost of editing history.** Treat a cache-hit-rate drop as an incident signal. It often means some middleware is rewriting earlier messages. Track **cached input tokens / total input tokens** per session. **2026 update:** before persisting a candidate fact, a System One `choice` call (Jev or Clef, Lessons 55–56) with `durable` / `telemetry` / `discard` can route it cheaply. The schema stays the final gate, and state is still treated as untrusted input.
5. **Snapshot cadence is a trade-off.** Frequent snapshots mean fast resume and more writes. Rare snapshots mean long replays. Snapshot on task boundaries, and every N events within long tasks.

## 7. Exercises

1. Add a `last_human_touch` timestamp and refuse agent writes within five seconds of a human edit.
2. Implement compare-and-swap: `record()` takes `expected_seq` and refuses if the log has moved on. Simulate two writers.
3. Add `pending_calls.jsonl` with idempotency keys and show that a replay after a crash does not send a duplicate "email".
4. Swap the file backend for SQLite while keeping the `StateStore` API identical.
5. Write a `compact()` that summarizes old transcript turns into one *appended* message, and confirm the prefix up to the summary still caches.

## 8. Key terms

| Term | Meaning |
|---|---|
| Repo memory | Operational state stored in tracked files under a schema |
| Atomic write | Temp file + fsync + rename, so a crash cannot tear the file |
| Event log | Append-only record of every state mutation |
| Snapshot + replay | Fast resume: load the last snapshot, apply newer events |
| Migration | Code that upgrades vN state to vN+1; unknown versions are refused |
| Append-only history | Never edit past messages; add new ones (summaries, corrections) |
| Prefix cache | Provider-side reuse of an unchanged request prefix |

## 9. Quick check

<details><summary>1. After the simulated crash, why was the state file unchanged?</summary>The new content went to a temp file in the same directory. The crash happened before <code>os.replace</code>, so the original file was never touched, and the cleanup removed the temp file.</details>
<details><summary>2. Why refuse a file with <code>schema_version: 9</code> instead of loading what you can?</summary>A newer writer may have changed the meaning of fields. Guessing risks silently corrupting the source of truth. Failing loudly sends a human to the migration.</details>
<details><summary>3. Why does editing an earlier message raise cost?</summary>Prompt caches match the longest unchanged prefix. Editing message 2 turns every later message into a cache miss. It also invalidates preserved reasoning on current frontier models.</details>

## References

- JSON Schema specification: https://json-schema.org/specification
- LangGraph persistence: https://docs.langchain.com/oss/python/langgraph/overview
- OpenAI Agents SDK release notes: https://raw.githubusercontent.com/openai/openai-agents-python/main/docs/release.md
- MCP 2026-07-28 changelog: https://modelcontextprotocol.io/specification/2026-07-28/changelog
- Microsoft Agent Framework, compaction: https://learn.microsoft.com/en-us/agent-framework/agents/conversations/compaction
- Hive issue: non-atomic state writes: https://github.com/aden-hive/hive/issues/6263
- OWASP Top 10 for Agentic Applications 2026 summary: https://www.giskard.ai/knowledge/owasp-top-10-for-agentic-application-2026
- Graphiti: https://github.com/getzep/graphiti
