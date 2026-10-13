# 40 · Multi-Session Handoff

> **Short answer:** The session will end; the work will not. A handoff packet is generated (not hand-written) from workbench artifacts at session end. It carries seven fields, the most important being one concrete `next_action`, and comes in two forms: `handoff.md` for humans and `handoff.json` for the next agent. It is only written after a clean-state check passes. In 2026 the packet sits alongside agent-SDK session **resume** and **fork**: resume when the transcript is still healthy, fork from the last good entry when the session hit a dead end, and start fresh from the packet when context is getting heavy.

**Type:** Build · **Languages:** Python (stdlib) · **Time:** ~50 min

---

## 1. The problem

The next session opens and asks "where did we leave off?" The answer was in the last session's context, and that context is gone. So the new agent re-reads the repo, re-runs the same failing command, re-asks the human the same question, and spends thirty minutes recovering the last thirty seconds.

A bad handoff costs you again in every session for the life of the task. Two things fix it:

1. A **packet** that records what changed, what was tried, what failed, what is risky and what to do first.
2. A **clean workbench**, so the packet describes something the next agent can trust.

## 2. The concept

```
 agent_state.json ─┐
 verification.json ┤            clean_state_issues() ── any? ──► refuse, list blockers
 review.json      ─┼──► snapshot ─┘ none
 feedback.jsonl   ─┤                 │
 git status       ─┘                 ▼
                              generate_handoff()
                         ┌───────────┴────────────┐
                    handoff.md                handoff.json   (JSON wins on disagreement)
                         └───────────┬────────────┘
                                     ▼
          next session: resume │ fork at last good entry │ fresh session + packet
```

### The seven fields

| Field | Question it answers |
|---|---|
| `summary` | What was done, in one line, with gate and review status |
| `changed_files` | The diff at a glance |
| `commands_run` | What actually executed |
| `failed_attempts` | What was tried and failed, so nobody retries it blindly |
| `open_risks` | What could bite next, with severity |
| `next_action` | **The first concrete step.** Without it you have a status report, not a handoff |
| `verdict_pointer` | Paths to the verification and review reports |

Production packets add `branch`, `last_known_good_commit`, a `status` (`active` / `superseded` / `archived`) and a `resume` pointer. Only one packet per branch and topic is `active`. Stale handoffs are the most common way multi-agent coordination goes wrong.

### Clean state is a check, not a habit

| Check | Blocks because |
|---|---|
| Uncommitted changes | A half-applied diff looks like intentional work |
| Temp artifacts (`*.tmp`, `*.orig`) | They pollute the diff and the next agent's picture of the repo |
| Red check not named in `open_risks` | A silent red test is a trap |
| Board says `in_progress` but the gate passed | A stale board sends the next session to finished work |
| Wrong branch | The next commit lands in the wrong place |

### Feedback trimming

Keep the last K records plus every non-zero exit, de-duplicated by position. The full log stays on disk. The packet stays small.

### Resume, fork or fresh?

| Situation | Move | Why |
|---|---|---|
| Context healthy, transcript useful | **Resume** the session by id | Cheapest; cache and reasoning stay warm |
| A dead end started at entry *n* | **Fork** at the last good entry (< *n*) | Keeps useful history and drops the poisoned tail. Never edit history in place |
| Context past your wrap-up budget (50–75%) | **Fresh session** seeded with the packet | Compaction quality falls off near the wall. Hand off while the agent can still summarize well |

Compaction *extends* a session. A handoff *closes* one. You need both, and the packet is what makes "close early" cheap.

## 3. What changed by Oct 2026

- **Agent SDKs made resume and fork first-class.** Current agent SDKs expose session stores you can resume by id, resume at an earlier entry (a fork), and drop the last turn on resume. OpenAI Agents SDK has Sessions and a resumable `RunState` with `add_input()`. Google ADK 2.x has persistent session services and added a SQLite memory service. The packet is still what lets you cross vendors or start clean.
- **Transcripts are append-only.** Frontier models now preserve reasoning across turns, and editing earlier history invalidates it (and your prompt cache). To undo, fork. The demo rejects an in-place edit for this reason.
- **Server-side compaction is everywhere**: hosted agent platforms, OpenAI's Responses API, Microsoft Agent Framework. It helps long sessions. It does not replace a clean handoff to a new session.
- **Background and scheduled agents raised the stakes.** Coding-agent CLIs now run background agents in worktrees that open draft PRs, and routines fire agents on schedules or GitHub events. Every one of those runs starts cold, so the packet is its first input.
- **AGENTS.md (now stewarded by the Agentic AI Foundation)** is where you tell any agent to load `handoff.json` first.
- **2026 update, System One:** "should this session wrap up now?" is a stop condition. A Jev or Clef `choice` over `{resume, fork, fresh}` with the context ratio and the recent feedback as `state` can make that call in milliseconds, with thresholds owned by your code (Lessons 55–56).

## 4. Build it

`code/main.py` contains:

- `SessionStore`: append-only transcripts with `resume()` and `fork(at_index)`. `edit()` raises.
- `decide_continuation()`: resume, fork or fresh, driven by context usage and dead-end detection.
- `clean_state_issues()`: the five blocking checks above.
- `generate_handoff()`: refuses on a dirty workbench or an empty `next_action`, and otherwise emits a deterministic payload (sorted fields, no timestamps).
- `HandoffRegistry`: publishing a new packet supersedes the active one for the same branch and topic.

```bash
python3 code/main.py
```

What to look for:

- An attempt to rewrite entry 3 is rejected; the dead-end case forks at entry 2 instead.
- The dirty snapshot is refused with six named blockers.
- The clean snapshot is generated twice with **identical digests**. That proves the packet is idempotent.
- The registry shows `['superseded', 'active']`, so exactly one packet is active.

## 5. Use it in production

| Hook point | Mechanism |
|---|---|
| Session end | Session-end hook in your coding-agent CLI or agent SDK runs `generate_handoff` and fails loudly on blockers |
| Session start | AGENTS.md / agent instruction files say "load `outputs/handoff/<latest>/handoff.json` first" |
| Resume / fork | The SDK's session store: resume by id, fork at an entry, or a fresh session seeded with the packet |
| PR body | `handoff.md` is the PR description; reviewers read one file, not five |
| Cross-agent | Build in one coding agent, continue in another; the JSON packet is the lingua franca |
| Durable runs | Temporal, Vercel Workflows or Cloudflare Agents persist the run; the packet is the human-readable checkpoint |

## 6. Architect's lens

1. **Budget for an early handoff.** Ending at 50–75% of the context window is cheaper than compacting at 95%. Make the wrap-up threshold a config value and measure rework against it.
2. **Determinism is a feature.** Same inputs, same packet, same hash. That lets CI diff packets, detect drift, and cache them. Timestamps belong in the file name, not in the content.
3. **Fork, don't rewrite.** Editing history breaks preserved reasoning and prompt caching, and it destroys the audit trail. A fork keeps lineage (`parent`, `at_index`) so you can explain later why the agent took the path it did.
4. **Metrics:** time-to-first-meaningful-action in the next session, repeated failed commands across sessions (they should be zero), handoff refusal rate, and the share of sessions that end with a non-empty `next_action`.
5. **Failure mode:** packets that grow into transcripts. Cap the feedback tail, link the full log and keep the packet to one screen.

## 7. Exercises

1. Add an `assumptions_to_validate` field: every assumption the builder logged that the reviewer scored below 2.
2. Make trimming asymmetric: keep more context around failures than around passes. Defend the choice.
3. Add "questions for the human". What is the threshold for a question to go into the packet instead of chat?
4. Implement `resume_drops_last_turn`: resume a session but discard a final turn that crashed mid-tool-call.
5. Replace `decide_continuation` with a System One `choice` call and compare its decisions against the rule on twenty logged sessions.

## 8. Key terms

| Term | Meaning |
|---|---|
| Handoff packet | Generated seven-field artifact in Markdown and JSON |
| Next action | The single concrete first step of the next session |
| Clean state | Workbench with no uncommitted, temp, silent-red, stale-board or wrong-branch issues |
| Resume / fork | Continue a session by id / branch a new session from an earlier entry |
| Superseded | A packet replaced by a newer active one on the same branch and topic |

## 9. Quick check

<details><summary>1. What separates a handoff from a status report?</summary>A non-empty, concrete <code>next_action</code>. Without it the next session still has to work out where to start.</details>
<details><summary>2. The last three turns chased a bad idea. Should you edit them out of the transcript?</summary>No. Fork at the last good entry. Editing history invalidates preserved reasoning and the cache, and it erases the audit trail.</details>
<details><summary>3. A test is red at session end. Does the generator refuse?</summary>Only if the red test is not named in the blockers or <code>open_risks</code>. A known, named red is a handoff. A silent red is a trap.</details>

## References

- OpenAI Agents SDK sessions: https://openai.github.io/openai-agents-python/sessions/
- Google ADK sessions and memory: https://google.github.io/adk-docs/sessions/
- Microsoft Agent Framework, compaction: https://learn.microsoft.com/en-us/agent-framework/agents/conversations/compaction
- LangChain, Context engineering for agents: https://www.langchain.com/blog/context-engineering-for-agents
- Hermes agent issue 20372, fresh-session handoff when compression gets risky: https://github.com/NousResearch/hermes-agent/issues/20372
- AGENTS.md specification: https://agents.md/
