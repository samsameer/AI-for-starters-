# 08 · Memory Blocks and Sleep-Time Compute

> **Short answer:** Memory blocks are small, typed, size-limited sections of the prompt (persona, human, project, safety) that the agent edits through tools. Sleep-time compute moves the expensive memory work (deduplication, conflict resolution, summarization, precomputing likely answers) to a background agent that runs while the user is idle. Together they give you structured memory that stays current without adding latency to user turns. Use them for any agent that lives longer than a single conversation.

**Type:** Build · **Languages:** Python (stdlib) · **Time:** ~75 min

---

## 1. The problem

MemGPT (Lesson 07) solved the control flow of virtual context. Running it in production exposed three new problems:

1. **Latency.** Pruning, summarizing and reconciling memory inside the turn makes the user wait. Tail latency grows with memory size.
2. **Memory rot.** Notes accumulate. "Lives in Austin" and "moved to Denver" both survive, and the agent cannot tell which is current.
3. **No structure.** A flat store cannot say "the persona is always in the prompt and only a human may change it, while the project notes change every week".

Letta, the platform that grew out of the MemGPT project, answered with two ideas. **Memory blocks** make structure explicit. **Sleep-time compute** (Lin et al., arXiv:2504.13171) moves consolidation off the critical path.

## 2. The concept

### Three tiers, with blocks inside core

| Tier | Visible? | Holds | Written by |
|---|---|---|---|
| Core (blocks) | Always, in the prompt | Persona, human, project, safety | Primary agent tools and the sleep-time agent |
| Recall | On search | Every message | Automatically, every turn |
| Archival | On search | Facts and documents | Agent tools and sleep-time ingestion |

### Anatomy of a block

```
label        "human"
description  "Facts about the user. Edit when they change."   <- tells the model when to write
value        "city=Denver; editor=neovim; timezone=America/Denver"
limit        130 chars                                         <- forces condensing, not appending
read_only    false            (persona and safety: true; edits need review)
versions     [(author, previous value), ...]                   <- diffs for debugging and audit
```

Blocks can be shared. A project block can be attached to several agents, so a lesson learned by one is visible to all of them.

### Sleep-time compute

```
 user turn ──► primary agent (fast model) ──► reply          critical path
                  │ raw notes, transcript
                  ▼
           shared blocks + archival ◄────── sleep-time agent  idle time
                                             (stronger model allowed)
                                             · resolve conflicts (latest wins)
                                             · merge or retire archival notes
                                             · summarize near-limit blocks
                                             · precompute learned context
```

The sleep-time paper frames this as spending compute before the question arrives. The model reasons over the context ahead of time so that later queries need less test-time compute, and the cost is shared across several queries about the same context. Because the background agent is not latency-bound, it can use a slower, stronger model.

### Native reasoning

Letta's later agent loop dropped the old `send_message` and heartbeat pattern and inline "Thought:" text in favour of the provider's native reasoning channel. The loop is still ReAct. Reasoning simply travels as structured output, not as prompt text.

### Where it goes wrong

- **Block bloat:** endless appends hit the limit. Summarize before the write that would overflow.
- **Silent drift:** the background agent rewrites a block and nobody notices. Version every write and surface diffs.
- **Poisoned consolidation:** the sleep-time agent reads attacker-reachable transcripts and could write them into core. Protect persona and safety blocks and require review for edits.

## 3. What changed by Oct 2026

- **Letta's product line widened.** Letta Code, a Conversations API (April 2026) and a TypeScript-first agent SDK (August 2026) carry memory blocks and sleep-time agents into coding and app use.
- **Background work is a platform feature everywhere.** Coding agents run background agents and scheduled routines, LangSmith offers Managed Deep Agents with user-level memory, and hosted agent platforms have scheduled deployments and memory stores. Each one is a place to run a sleep-time pass.
- **Skills are blocks for procedures.** `SKILL.md` folders with progressive disclosure (now a cross-vendor pattern in provider APIs, coding agents, Google ADK and the Vercel AI SDK) are named, versioned instruction blocks loaded on demand. AGENTS.md is a shared, human-reviewed project block.
- **Append-only transcripts.** Models that preserve reasoning across turns, and prompt caches, both reward leaving history untouched. Rewrite blocks between sessions or at compaction boundaries, not in the middle of a cached prefix.
- **Memory poisoning has a name.** OWASP's Top 10 for Agentic Applications 2026 lists Memory and Context Poisoning (ASI06). Background writers are part of that attack surface.
- **2026 update, System One consolidation judge:** the sleep-time agent asks many small typed questions: "does note B contradict note A?" (`noul`), "which block does this fact belong in?" (`choice`), "how stale is this record?" (`score`). A decision model (Jev or Clef, Lessons 55–56) answers them cheaply and consistently, so the stronger LLM is used only for actual rewriting.

## 4. Build it

`code/main.py` runs a seven-turn chat with a coding assistant in three modes: no consolidation, inline consolidation and sleep-time consolidation.

- `Block`: label, description, limit, read-only flag and version history with `difflib` diffs.
- `Memory.guarded_write`: refuses writes to protected blocks without review.
- `PrimaryAgent.turn`: appends raw `[tN] key: value` notes to the human block and overflows to archival. It needs two lookup calls to answer "how do I run the tests?" unless the project block already knows.
- `SleepTimeAgent.run`: resolves conflicts (latest turn wins), retires merged or superseded archival notes, writes learned project context, flags near-limit blocks, and tries an injected persona edit, which is blocked.
- `simulate`: user-facing latency per turn, using simulated milliseconds (not real measurements).

```bash
python3 code/main.py
```

What to look for: with no consolidation, the human block holds both Austin and Denver, other notes are stranded in archival, and every test question costs two lookups. Inline consolidation fixes memory but adds about 2.6 s to two turns. Sleep-time does the same work with no added user latency, answers the later test questions from the project block, resolves both conflicts, and refuses the "always share API keys" persona edit.

## 5. Use it in production

- **Letta:** blocks, shared blocks and sleep-time agents as a hosted or self-hosted service.
- **Provider memory tools and memory stores:** keep blocks as files or store entries. Run consolidation as a scheduled or background job.
- **LangGraph 1.2 / LangMem:** a background memory manager that extracts and consolidates into a namespaced store after each conversation.
- **Google ADK 2.x:** memory services plus a scheduled workflow that consolidates sessions.
- **Coding agents:** AGENTS.md as the reviewed project block, skills as procedural blocks, and a background agent that proposes edits as pull requests for human review.

## 6. Architect's lens

1. **Write permissions per block.** Persona and safety are read-only to agents. Human and project are agent-writable with versioning. Treat every writer, including your own background agent, as untrusted.
2. **Design for the critical path.** Primary turns should only append raw notes. Anything that compares, merges or summarizes belongs in a sleep pass, triggered by idle time, turn count or block pressure.
3. **Conflict policy is a product decision.** "Latest wins" is right for addresses and wrong for allergies, which should accumulate. Encode the policy per key and log every resolution.
4. **Spend idle compute where it pays.** Precompute answers to likely questions only when the context will be queried several times. Track the hit rate of learned context and drop what is never used.
5. **Observe memory like code.** Version, diff and roll back blocks. "Why did the agent forget X?" should be a single `git log`-style query.

## 7. Exercises

1. Make `allergy` an accumulate-only key: new values append and never replace. Add a turn with a second allergy and check the result.
2. Implement block summarization when `near_limit()` fires (for example, drop the least-used keys into archival) and confirm the human block stays under its limit.
3. Trigger the sleep pass by block pressure instead of fixed turns. How many passes run, and what happens to latency?
4. Add a stand-in contradiction judge that returns `P(contradiction)` for a pair of notes, and only resolve conflicts above 0.7. What happens for "editor=vim" and "editor=neovim (for Rust only)"?
5. Route the persona edit to a review queue and approve it with `reviewed=True`. Log who approved it and show the diff.

## 8. Key terms

| Term | Meaning |
|---|---|
| Memory block | A typed, size-limited, editable section of core memory |
| Human / persona block | Facts about the user / the agent's identity and constraints |
| Shared block | One block attached to several agents |
| Sleep-time compute | Memory and reasoning work done while the user is idle |
| Learned context | Facts the background agent precomputes for later turns |
| Block limit | Character cap that forces condensing |
| Native reasoning | Reasoning on the provider's structured channel instead of in prompt text |

## 9. Quick check

<details><summary>1. Why can the sleep-time agent use a stronger, slower model?</summary>It runs while the user is idle, off the critical path, so its latency is never felt in a reply. Only cost limits it.</details>
<details><summary>2. Why give blocks a character limit?</summary>The limit forces the agent to condense and edit rather than append forever, protecting the prompt budget and keeping always-visible facts current.</details>
<details><summary>3. Why is the persona block read-only even for the trusted background agent?</summary>The background agent reads transcripts that may contain injected text. If it could edit the persona, an attacker could change the agent's identity and rules for every future session.</details>

## References

- Lin et al., Sleep-time Compute: Beyond Inference Scaling at Test-time (arXiv:2504.13171): https://arxiv.org/abs/2504.13171
- Packer et al., MemGPT (arXiv:2310.08560): https://arxiv.org/abs/2310.08560
- Letta, Memory Blocks: https://www.letta.com/blog/memory-blocks
- Letta, Sleep-time Compute: https://www.letta.com/blog/sleep-time-compute
- Letta docs: https://docs.letta.com/
- LangMem: https://github.com/langchain-ai/langmem
- OWASP Top 10 for Agentic Applications 2026: https://genai.owasp.org/
