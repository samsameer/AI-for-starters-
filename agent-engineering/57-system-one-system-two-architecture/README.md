# 57 · Capstone: System One + System Two Agent Architecture

> **Short answer:** Split every agent into two kinds of model calls. **System One** is a decision model (Jev or Clef) that makes every *bounded* choice: route, guard, stop, judge. **System Two** is an LLM that does only the *open-ended* work: plan, write, generate tool arguments. Thresholds and control flow live in code. On the toy workload in this lesson, the split cut latency 2–4× and cost 3–4×. It also added a per-step safety gate that the LLM-only design skipped.

**Type:** Capstone · **Languages:** Python (stdlib) · **Time:** ~2 h · **Builds on:** Lessons 01, 12, 26–30, 55, 56

---

## 1. The architecture

```
                    ┌──────────────────────────── code owns control flow ─────────────────────────────┐
 task ─► S1 route ──┤ conf < τ_route ─► human                                                         │
                    └─► S2 plan ─► for each step: S1 guard ─► (risky? ─► human approval) ─► tool        │
                                                     └─► S1 done? ── yes ─► S2 write ─► S1 quality ──► │
                                                                                     score < τ_q ─► S2 revise
```

| Decision point | Model | Primitive | Typical τ |
|---|---|---|---|
| Which specialist or sub-agent? | S1 | `choice` | confidence ≥ 0.45–0.9 (tune on evals) |
| Is this tool call risky? | S1 | `noul` + `score` (blast radius) | P(risky) ≥ 0.7 → approval |
| Is the task done? | S1 | `noul` | ≥ 0.75 → stop |
| Is the answer good enough? | S1 | `score` 0–3 | < 1 → revise |
| Plan the steps, write the answer | S2 | generation | n/a |

## 2. Build it

`code/main.py` runs the same three tasks through two agents:

- `hybrid_agent` uses System One for route, guard, stop and quality, and System Two for plan and write.
- `llm_only_agent` is the 2024-style agent: the LLM routes via JSON and acts as judge at every step.

A `Ledger` records each call's latency and cost. The constants use realistic 2026 orders of magnitude: about 1.8 s per LLM call vs about 40 ms for Clef-flash.

```bash
python3 code/main.py
```

What to look for:

- The hybrid agent **holds `restart(prod)`** for human approval. The LLM-only agent runs it.
- The `done` check stops the loop as soon as the evidence is in.
- The quality score triggers **one** revision, not a debate loop.
- In the summary table, hybrid comes out about 3–4× cheaper and about 2–4× faster.

## 3. Production blueprint (Oct 2026)

| Layer | Recommended default | Alternatives |
|---|---|---|
| Edge / ingress | Cloudflare Worker + Clef-flash gate | Vercel/Netlify function + Jev |
| Durable agent state | Cloudflare Agents SDK (Durable Objects) or LangGraph checkpoints | Temporal, Restate, Inngest |
| System Two LLM | Frontier LLM via an agent SDK (OpenAI Agents SDK, Google ADK, Pydantic AI) | Workers AI open models |
| Tools | MCP servers behind a gateway with per-tool scopes | Native function calling |
| Guard | Clef/Jev step guard + allow-list + human approval for irreversible actions | Dual-LLM / CaMeL pattern |
| Observability | OpenTelemetry GenAI spans, with **decision probabilities as span attributes** | Langfuse, LangSmith, Phoenix |
| Evals | Labeled decision set per S1 question + trajectory evals for S2 | Benchmarks only for model choice |

## 4. Architect's lens

1. **Draw the decision inventory first.** List every place the agent chooses between a finite set of options. Each one is a System One candidate. In most production agents, 60–80% of model calls end up there.
2. **Every S1 question gets its own eval set and owner.** Thresholds are reviewed like feature flags.
3. **Abstain paths are first-class.** Escalation volume is a KPI. If it rises, either your data drifted or your thresholds are wrong.
4. **Fail-closed on side effects, fail-open on read-only work.**
5. **Don't let S1 creep into generation.** If you keep adding labels to approximate free text, that step belongs in S2.

## 5. Exercises

1. Replace `SystemOne.ask` with real calls to Clef (Lesson 56) or Jev (Lesson 55) and rerun the table.
2. Add OpenTelemetry-style spans (Lesson 23) and attach `gen_ai.decision.probability` attributes.
3. Write 30 labeled tool calls and pick τ for `risky` that minimizes `10·FN + 1·FP`.
4. Add a sub-agent handoff (Lesson 28) where S1 decides **whether** to fan out and S2 does the fanned-out work.
