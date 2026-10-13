# 09 · Hybrid Memory: Vector + KV + Graph (Mem0)

> **Short answer:** No single store answers every memory question. Vector search finds "what did we discuss about slow checkout?". A key-value lookup answers "who is Alice's manager?". A graph answers "who else works at her company?" and, with validity intervals, "where did she live in March?". Hybrid memory writes extracted facts to all three and fuses the results on read with a weighted score of relevance, importance and recency. Mem0 is the best-known open implementation. Use the hybrid design when an agent's memory must serve several question types for many users over months.

**Type:** Build · **Languages:** Python (stdlib) · **Time:** ~75 min

---

## 1. The problem

Each store is wrong for most question types:

| Question | Vector | KV | Graph |
|---|---|---|---|
| "What did we discuss about slow checkout?" (semantic) | Yes | No | No |
| "Who is Alice's manager now?" (exact fact) | Fuzzy, may return the old manager | Yes, O(1) | Yes |
| "Who else works at Alice's company?" (relationship) | Returns sentences, not a list | No | Yes |
| "Where did Alice live on day 4?" (temporal) | No | No, it holds only the latest value | Yes, with validity intervals |

A real assistant asks all four in one session. Mem0 (Chhikara et al., arXiv:2504.19413) put extraction, several stores and one `add` / `search` surface together. The paper reports better LLM-judged accuracy than several memory baselines on the LoCoMo long-conversation benchmark, with far lower latency and token use than stuffing the full history into context.

## 2. The concept

### Write path: extract, then fan out

```
message ──► extractor (LLM) ──► atomic facts
                                 ├─► vector store   embedding of the text
                                 ├─► KV store       (user, subject, relation) -> value
                                 └─► graph store    (subject)-[relation]->(object), valid_from..valid_to
```

Extraction is the expensive and important step. Store **atomic facts** ("Alice is allergic to shellfish"), not whole messages. The demo shows why: a message that mixes a stale fact with a live one keeps resurfacing the stale part.

### Read path: three routes, one ranking

```
score = w_rel · relevance + w_imp · importance + w_rec · recency
recency = 0.5 ^ (age_days / half_life)
```

- **Relevance:** embedding cosine (plus exact KV hits and graph paths returned alongside).
- **Importance:** set at write time. Allergies and policies matter more than lunch orders.
- **Recency:** exponential decay.

The weights are a product decision. Chat assistants lean toward recency, safety and compliance agents toward importance, and retrieval agents toward relevance. Many teams also use reciprocal-rank fusion across routes when the scores are not comparable.

### Time: invalidate, never overwrite

Functional relations (`lives_in`, `manager_is`) have one current value. When a new value arrives, close the old edge by setting `valid_to` instead of deleting it. "Now" queries read live edges; "as of" queries read the edge that was valid then. Graphiti, from the Zep team, is built around this kind of temporal knowledge graph.

### Scopes

Every write belongs to a scope: **user** (across sessions), **session** (one thread) or **agent** (one agent's own state). Retrieval filters by scope before scoring. Mixing scopes carelessly is how "the assistant told Bob about Alice's medical details" happens.

### Where it goes wrong

- **Extractor noise:** one chatty extractor adds dozens of edges per message. Cap writes per `add` and drop low-confidence facts.
- **Schema creep:** every team invents relation names. Keep a reviewed relation vocabulary.
- **Embedding drift:** changing embedding models silently degrades recall. Version embeddings and re-embed in the background.
- **Poisoning:** extracted "facts" can come from injected text. Keep provenance (`source` memory id) on every edge.

## 3. What changed by Oct 2026

- **Mem0 moved to an ADD-only extraction algorithm.** The Mem0 Python SDK v2.0.0 (April 2026) introduced a new extraction algorithm that only adds facts instead of updating or deleting them in place. Conflicts are handled with history and ranking, as in the demo. The open-source package is on the 2.x line, and Mem0 self-reports strong LongMemEval results. Treat vendor-run numbers as claims to verify on your own data.
- **Temporal graphs went mainstream.** Graphiti (0.31 line) is the reference open temporal knowledge graph with validity intervals. Zep's Community Edition was discontinued in 2025; the hosted product and Graphiti continue.
- **Platforms ship managed memory.** Hosted agent platforms offer memory stores, Google ADK has memory services (including SQLite), AWS Bedrock AgentCore Memory has an `IngestData` API, and LangSmith Managed Deep Agents have user-level memory. The hybrid design is often behind these products.
- **Letta stays tier-first.** Letta (Lessons 07–08) remains the main block-and-tier alternative, with a TypeScript agent SDK released in August 2026.
- **Memory poisoning is an OWASP category.** OWASP's Top 10 for Agentic Applications 2026 lists Memory and Context Poisoning (ASI06), so provenance and scoped retrieval are baseline requirements.
- **2026 update, System One write and read gates:** the extractor's small decisions are typed questions: "does this message contain a durable fact?" (`noul`), "which relation is this?" (`choice`), "how important is it?" (`score`). A decision model (Jev or Clef, Lessons 55–56) answers them quickly with calibrated probabilities, and those probabilities can feed the importance weight directly. Use the LLM only for free-form extraction.

## 4. Build it

`code/main.py` runs a small multi-user memory over 22 simulated days:

- `embed`: a hashed bag of words and character trigrams, a stdlib stand-in for a real embedding model, with cosine similarity.
- `HybridMemory.add`: a rule-based extractor (an LLM stand-in) that writes to vector, KV and a temporal graph, and closes superseded functional edges.
- `vector_search`, `kv_lookup`, `graph_neighbors(as_of=...)` and `coworkers`: the three read routes, plus a two-hop graph query.
- `fused`: the weighted fusion score with a 14-day half-life, run under a recency-heavy "chat" profile and an importance-heavy "safety" profile.
- Scope isolation checks between Alice and Bob, and between user and session scope.

```bash
python3 code/main.py
```

What to look for: the write path closes `alice lives_in berlin` on day 6 and `manager_is omar` on day 20 without deleting either. Each query class is answered by a different store, and the vector-only answer to the relationship query is just sentences. Under the chat profile the shellfish allergy drops out of the top three for a lunch-booking question; under the safety profile it ranks first. Bob's view contains nothing about Alice.

## 5. Use it in production

- **Mem0 (Apache-2.0, self-hosted or managed):** `add` / `search` with user, session and agent scopes, vector backends such as Qdrant or pgvector, and an optional graph backend.
- **Graphiti / Zep:** temporal knowledge graphs when "what was true when" matters.
- **Letta:** block-and-tier memory (Lessons 07–08), with your own vector or graph backend for archival memory.
- **LangGraph 1.2 / LangMem:** namespaced long-term stores with background extraction.
- **Managed options:** provider memory stores, Google ADK memory services and AWS AgentCore Memory, when you would rather not run three databases.
- **Postgres-only:** `pgvector` plus relational tables plus recursive CTEs covers all three routes for many teams at moderate scale.

## 6. Architect's lens

1. **Extraction quality caps everything.** Atomic, deduplicated facts with provenance beat any clever fusion over raw messages. Evaluate the extractor on its own: precision of facts, relation accuracy, confidence calibration.
2. **Route before you fuse.** Classify the query (semantic, lookup, relationship, temporal) and hit the store that answers it. Fusion is for open questions, not for "what is the user's phone number".
3. **Make weights explicit and per use case.** Store fusion profiles in config, test them on golden queries, and never let a safety-critical fact depend on a recency-heavy profile.
4. **Time is a first-class column.** `valid_from` and `valid_to` on every functional fact. Deletion is a privacy operation, not a way to update data.
5. **Scope and tenancy are security controls.** Filter by tenant and user before scoring, encrypt at rest, and make "forget me" remove data from all three stores and from embeddings.

## 7. Exercises

1. Split each message into atomic facts before writing to the vector store. Re-run the fusion: does m02's stale manager line stop surfacing?
2. Add a query router (start with keywords, then a stand-in decision model returning `semantic`, `lookup`, `relation` or `temporal`) and dispatch to a single store.
3. Implement reciprocal-rank fusion across the vector, KV and graph routes and compare its top 3 with the weighted sum.
4. Add an `allergic_to` relation that accumulates instead of replacing, and a "forget(alice)" that clears all three stores. Prove it with searches.
5. Add 200 synthetic memories and measure recall@3 for ten golden questions as the corpus grows. When does the toy embedding start failing?

## 8. Key terms

| Term | Meaning |
|---|---|
| Hybrid memory | Facts written to several stores and fused on read |
| Fact extraction | Turning messages into atomic (subject, relation, object) facts |
| Fusion scoring | Weighted sum of relevance, importance and recency |
| Functional relation | A relation with one current value, such as `lives_in` |
| Validity interval | `valid_from`..`valid_to` on a fact, for "as of" queries |
| ADD-only memory | New facts are appended; history is kept, not overwritten |
| Scope | User, session or agent namespace that controls visibility |

## 9. Quick check

<details><summary>1. Why not answer "who is Alice's manager?" from the vector store?</summary>Similarity search may return the old manager's sentence as readily as the new one. A KV entry or a live graph edge gives the single current value directly.</details>
<details><summary>2. Why close an edge instead of deleting it?</summary>History stays queryable ("where did she live on day 4?"), changes stay auditable, and a mistaken update can be reversed.</details>
<details><summary>3. Why did the safety profile rank the allergy first?</summary>It weights importance highest, and the allergy was written with the maximum importance score. The recency-heavy chat profile favoured newer but less important notes instead.</details>

## References

- Chhikara et al., Mem0: Building Production-Ready AI Agents with Scalable Long-Term Memory (arXiv:2504.19413): https://arxiv.org/abs/2504.19413
- Mem0 docs: https://docs.mem0.ai/
- Rasmussen et al., Zep: A Temporal Knowledge Graph Architecture for Agent Memory (arXiv:2501.13956): https://arxiv.org/abs/2501.13956
- Graphiti: https://github.com/getzep/graphiti
- Maharana et al., LoCoMo (arXiv:2402.17753): https://arxiv.org/abs/2402.17753
- Wu et al., LongMemEval (arXiv:2410.10813): https://arxiv.org/abs/2410.10813
- Cormack et al., Reciprocal Rank Fusion (SIGIR 2009): https://doi.org/10.1145/1571941.1572114
