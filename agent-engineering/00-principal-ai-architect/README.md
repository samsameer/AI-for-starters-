# 00 · How to Think Like a Principal AI Architect

> **Short answer:** A Principal AI Architect doesn't pick the coolest framework. They turn a business outcome into a **system of decisions, loops and guarantees**, and then prove it works with evals. You get there in five layers: (1) own the agent loop from first principles, (2) know the 2026 stack well enough to choose without hype, (3) design for failure, security and cost, (4) measure everything with evals and traces, (5) lead people to an outcome with clear specs and trade-offs. This tutorial follows that order.

---

## 1. The professor's version, in 60 seconds

An agent is **a loop** (observe → think → act → check) around **a model**, with **tools**, **memory** and **stop conditions**. Everything else is engineering for scale, safety and cost.

The 2026 principal-level insight is that **not every step needs a large language model**:

- **System One** decision models (TypeSafe **Jev**, Cloudflare **Clef**) answer bounded questions in milliseconds with calibrated probabilities. Use them for route, guard, stop and judge.
- **System Two** LLMs (frontier models such as GPT and Gemini, plus open-weight models) do open-ended work: plan, write code, write prose.
- **Code** owns the thresholds and the control flow.

If you can draw that picture for any product and defend every box with a number (latency, cost, error rate, blast radius), you are thinking like a principal.

## 2. The ladder

| Level | You can… | Lessons |
|---|---|---|
| Engineer | Build a working agent loop, call tools, add memory | 01–11 |
| Senior | Choose and use frameworks: LangGraph, Agents SDKs, Mastra… | 12–18 |
| Staff | Evaluate, observe, secure and run agents in production | 19–30 |
| Senior Staff | Build harnesses that make coding agents reliable on real repos | 31–46 |
| **Principal** | Shape *what* to build: outcomes, specs, metrics, rollout, feedback ratchets, and the System One / System Two architecture | 47–57 |

## 3. Five habits of principal AI architects

1. **Start from the outcome, not the model.** "Reduce refund handling time from 2 days to 2 hours with ≤0.5% wrong refunds" is a design input. "Use GPT-6" is not.
2. **Make the decision inventory.** List every choice the system makes. Bounded choices go to System One, open-ended work goes to System Two, and irreversible actions go to a human.
3. **Design the failure modes before the happy path.** Cover prompt injection, cascading tool errors, runaway loops, cost blow-ups and silent quality drift (Lessons 26–27).
4. **Evals are the spec.** No change ships without a number moving on a held-out set (Lessons 30, 52, 54).
5. **Write decisions down.** Use one-page ADRs that state the options, the trade-offs, the chosen option and how you'll know you were wrong.

## 4. Architecture review checklist (use on every design)

- [ ] What is the measurable outcome and the guardrail metric?
- [ ] Where is the loop, and what are its stop conditions and budgets (turns, tokens, $)?
- [ ] Which decisions are System One, which are System Two, and which belong to a human?
- [ ] What is untrusted input, and what can it influence (Lesson 27)?
- [ ] What happens if each dependency is slow, down or wrong (fail-open vs fail-closed)?
- [ ] How is state persisted and resumed (Lesson 29)?
- [ ] What gets traced, at what granularity, and where (Lessons 23–24)?
- [ ] What is the eval set, who owns it and how does it grow (Lesson 54)?
- [ ] What is the cost per task at p50 and p99, and at 100× volume?
- [ ] What is the rollout plan: prototype → pilot → production (Lesson 53)?

## 5. Study plan

- **Weeks 1–2:** Lessons 01–11. Rebuild each loop yourself without looking.
- **Weeks 3–4:** Lessons 12–18. Build the same agent in two frameworks and write an ADR comparing them.
- **Weeks 5–6:** Lessons 19–30. Add tracing, evals and injection defenses to your agent.
- **Weeks 7–8:** Lessons 31–46. Build a workbench for a real repository.
- **Weeks 9–10:** Lessons 47–57. Run the capstone, then present a design review to someone senior.
