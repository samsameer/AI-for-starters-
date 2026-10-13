# 07 · Agent Memory: Virtual Context and Memory Paging

> **Short answer:** A context window is RAM: fast, always visible and finite. MemGPT's idea is to add a disk (searchable external stores) and give the agent tools to page facts in and out, the way an operating system manages virtual memory. Even with million-token windows this still matters, because long contexts cost money, dilute attention and disappear when the session ends. Use virtual context whenever an agent must remember across long sessions or across sessions.

**Type:** Build · **Languages:** Python (stdlib) · **Time:** ~75 min

---

## 1. The problem

Bigger context windows look like the end of the memory problem. They are not. Three failures keep showing up:

1. **Overflow.** Long chats, big documents and tool-heavy traces still outgrow the window or the budget. Whatever falls off the end is gone.
2. **Dilution.** Stuffing the window with mostly irrelevant text makes models worse at using the parts that matter, and every token is billed on every turn.
3. **Persistence.** A new session starts empty. Without external memory the agent cannot say "last week you told me your partner uses a cane".

MemGPT (Packer et al., arXiv:2310.08560) restated the problem as virtual memory. The Mem0 paper (Lesson 09) later reported that retrieval-based memory can match or beat full-context baselines on long conversations at a fraction of the tokens and latency.

## 2. The concept

### The OS analogy

| Operating system | MemGPT | Production in 2026 |
|---|---|---|
| RAM | Main context (the prompt) | The model's context window |
| Disk | External context | Vector, keyword, KV or graph store; files |
| Page fault | Memory tool call | `archival_memory_search`, a memory tool, file reads |
| Kernel | Agent control loop | ReAct loop plus memory tools and compaction |
| Low-memory warning | "Memory pressure" system alert | Context-usage hooks, compaction triggers |

### The tiers

```
┌──────────────────────── main context (token budget) ───────────────────────┐
│ system + tool schemas │ core memory blocks │ recursive summary │ FIFO queue │
└────────────▲───────────────────────▲──────────────────────────────┬────────┘
             │ core_memory_append /  │ archival_memory_search /     │ evict oldest
             │ core_memory_replace   │ conversation_search          ▼
     ┌───────┴──────────┐   ┌────────┴──────────────────┐   ┌─────────────────┐
     │ archival memory  │   │ recall memory (every msg) │◄──│ write-through   │
     │ facts, docs      │   │ searchable history        │   └─────────────────┘
     └──────────────────┘   └───────────────────────────┘
```

- **Core memory:** small, named, always-visible sections ("persona", "human"). They have a hard size limit, so the agent must edit them, not just append.
- **FIFO queue plus recursive summary:** recent messages. When the budget is exceeded, the oldest are evicted and folded into a running summary.
- **Recall memory:** every message, searchable later. Eviction never deletes; it pages out.
- **Archival memory:** facts and documents the agent chooses to save, retrieved by search.

### The interrupt pattern

The agent calls a memory tool mid-turn. The runtime runs it and splices the result into the next step as an observation, exactly like a blocking `read()` syscall. MemGPT also sends a system alert when the context passes about 70% of the budget, which prompts the agent to save important facts before eviction.

### Where it goes wrong

- **Memory rot:** writes outpace reads, so retrieval drowns in stale facts. Consolidate (Lesson 08) and resolve conflicts (Lesson 09).
- **Memory poisoning:** anything stored is re-read in a later session. An injected instruction in a web page becomes a persistent instruction. This is OWASP Agentic ASI06, Memory and Context Poisoning.
- **Citation loss:** "the user wanted X", but from which turn? Store a source with every write.

## 3. What changed by Oct 2026

- **Million-token windows are common, and paging still pays.** Current frontier models from several vendors offer 1M-token contexts, but cost per turn, latency and long-context dilution keep the budget small in practice.
- **Memory became a platform primitive.** Provider APIs ship a client-side memory tool (a file directory the model reads and writes), context editing that clears old tool results and thinking, and server-side compaction that summarizes history when a threshold is crossed. OpenAI's Responses API also offers server-side compaction for long-running agents.
- **Managed memory stores.** Hosted agent platforms added memory stores scoped to an agent or user. Google ADK added a SQLite memory service, AWS Bedrock AgentCore Memory has an `IngestData` API, and LangSmith's Managed Deep Agents offer user-level memory.
- **Letta kept evolving the MemGPT line.** Letta Code, a Conversations API (April 2026) and a TypeScript-first agent SDK (August 2026) build on the core and archival tiers.
- **Append-only history matters.** Models that preserve their reasoning across turns, and prompt caches, both punish rewriting earlier messages. Compaction should add a new boundary or summary message instead of editing old ones in place.
- **2026 update, System One memory gates:** two typed questions sit in the hot path: "is this turn worth saving to archival?" and "does this retrieved memory contain instructions?" (both `noul`). A decision model (Jev or Clef, Lessons 55–56) answers them in tens of milliseconds, which is cheaper and more consistent than asking the main LLM, and the threshold stays in code.

## 4. Build it

`code/main.py` runs a MemGPT-shaped runtime over two sessions of a travel-planning chat:

- `BM25Store`: real BM25 scoring, used for both archival and recall memory, with a trust flag on every record.
- `MainContext`: a 110-token budget holding core memory (120-character limit per section), a recursive summary and a FIFO queue.
- `MemGPTRuntime.push`: write-through to recall, a memory-pressure alert at 70%, and eviction into the summary when over budget.
- The tool surface: `core_memory_append`, `core_memory_replace`, `archival_memory_insert`, `archival_memory_search` and `conversation_search`, all returning citations.
- A poisoning case: one user message quotes an injected instruction. It is flagged on write, omitted from the summary and quarantined on read.

```bash
python3 code/main.py
```

What to look for: the pressure alert fires early, and four turns are evicted. An append to core memory is refused for size, so the agent switches to `replace`. In session 2 a fresh window recovers the budget from archival and the flight from recall, each with a `session#turn` citation, while the injected record is withheld. The no-memory baseline knows nothing.

## 5. Use it in production

- **Provider memory tool plus context editing:** the simplest virtual-context setup. The model manages a memory directory, and the platform clears stale tool output.
- **Letta:** core and archival memory as a service, with agent-editable memory blocks (Lesson 08).
- **Mem0 / Zep-Graphiti:** extraction-based semantic memory and temporal knowledge graphs (Lesson 09).
- **LangGraph 1.2 / LangMem:** a long-term store keyed by namespace, with background extraction of facts and rules.
- **Google ADK 2.x:** memory services (in-memory, SQLite, or managed) attached to the runner.
- **AWS Bedrock AgentCore Memory:** managed short- and long-term memory with ingestion APIs.

## 6. Architect's lens

1. **Budget the window like RAM.** Assign fixed shares to system prompt, tool schemas, core memory, summary and recent turns. Alert on pressure before you hit the limit, not after.
2. **Writes need policy.** Decide what is worth saving, who may save it and with what provenance. An agent that saves everything has bad recall. One that saves blindly can be poisoned.
3. **Provenance on every record.** Session, turn, source and trust level. Without them you cannot cite, expire or delete for privacy requests.
4. **Measure recall, not storage.** Build a small eval of "facts from N sessions ago" questions and track recall@k and answer accuracy as you change chunking, scoring and compaction.
5. **Isolate tenants.** Memory scoped by user and agent, encrypted at rest, with deletion that actually deletes. Memory leaking across users is a breach.

## 7. Exercises

1. Lower the budget to 70 tokens. Which fact is lost first, and what alert threshold would have saved it?
2. Replace the truncating summary with a two-level summary (recent turns in detail, older ones condensed). Compare the token use.
3. Add a `ttl_days` field to archival records and an `expire()` sweep. Which facts should never expire?
4. Write a stand-in `worth_saving(turn) -> probability` gate and only call `archival_memory_insert` above 0.6. Count writes saved and facts lost.
5. Add a `forget(user)` operation that removes a user's data from core, archival and recall, and prove it with a search.

## 8. Key terms

| Term | Meaning |
|---|---|
| Virtual context | Main context plus external stores, with tools to page between them |
| Main context | The prompt: fixed-size and always visible |
| Core memory | Named, size-limited sections pinned inside the prompt |
| Recall memory | Searchable store of every past message |
| Archival memory | Searchable store of facts and documents the agent chose to save |
| Recursive summary | Running summary that absorbs evicted messages |
| Memory pressure | Alert that the context is close to its budget |
| Memory poisoning | Malicious text stored as memory and re-read later |

## 9. Quick check

<details><summary>1. Why is a 1M-token window not a replacement for virtual context?</summary>It still costs tokens and latency on every turn, dilutes attention over irrelevant text, and vanishes when the session ends. Paging keeps the window small and makes memory persistent.</details>
<details><summary>2. What is the difference between recall and archival memory?</summary>Recall stores every message automatically as searchable history. Archival stores only what the agent deliberately saves, such as facts and documents.</details>
<details><summary>3. Why give core memory a hard size limit?</summary>It forces the agent to edit and condense instead of appending forever, which protects the token budget and keeps the always-visible facts current.</details>

## References

- Packer et al., MemGPT: Towards LLMs as Operating Systems (arXiv:2310.08560): https://arxiv.org/abs/2310.08560
- Chhikara et al., Mem0 (arXiv:2504.19413): https://arxiv.org/abs/2504.19413
- Letta docs: https://docs.letta.com/
- Robertson and Zaragoza, The Probabilistic Relevance Framework: BM25 and Beyond: https://doi.org/10.1561/1500000019
- LangMem: https://github.com/langchain-ai/langmem
- Google ADK, memory: https://google.github.io/adk-docs/sessions/memory/
- OWASP Top 10 for Agentic Applications 2026: https://genai.owasp.org/
