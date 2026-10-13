# 25 · Multi-Agent Debate and Collaboration

> **Short answer:** In multi-agent debate, several model instances answer the same question on their own, read each other's answers, revise over a few rounds, and then converge or vote. It can improve factuality and reasoning, but **only when the agents make different mistakes** and correct reasoning tends to win the argument. It costs N × R times more tokens and latency. In Oct 2026, treat debate as one option to measure against a **same-budget voting baseline**, use diverse models or prompts, prefer sparse topologies, and let a cheap judge decide when to stop.

**Type:** Learn + Build · **Languages:** Python (stdlib) · **Time:** ~60 min

---

## 1. The problem

Single-model self-critique (Self-Refine, Lesson 05) often confirms its own mistakes. Tool-grounded critique (CRITIC) needs a tool that can check the answer, and many questions have none. Debate offers a third route: let independent reasoners challenge each other, so one agent's blind spot gets caught by another.

The catch is that "independent" carries the whole argument. Five copies of the same model with the same prompt tend to share the same misconception, and then debate just makes them confidently wrong together.

## 2. The concept

### The protocol (Du et al., "Society of Minds", ICML 2024)

```
round 0   A0   B0   C0        each agent answers alone
            \  |  /
round 1   A1   B1   C1        each reads peers' answers + reasoning, revises
            \  |  /
round R   AR   BR   CR  ──►  aggregate (majority / judge)  ──► answer
                 ▲
       stop early when answers agree
```

The original experiments used 3 agents and 2 rounds because of cost, and reported gains on arithmetic, GSM8K, MMLU, chess-move validity and biographies. Mixing different models helped more than repeating one.

### Topology: who reads whom

| Topology | Peer reads per agent per round (N=5) | Notes |
|---|---|---|
| Full mesh | 4 | Most information, most tokens. Fastest convergence, including convergence on wrong answers |
| Ring | 2 | Sparse. Li et al. (arXiv 2406.11776) showed sparse topologies can match full mesh at lower cost |
| Star (hub) | Hub 4, spokes 1 | Cheap, but a bad hub can steer everyone |
| None | 0 | Independent voting: the baseline every debate must beat |

### Variants worth knowing

- **Adversarial / judge debate:** two agents argue opposing positions and a judge decides (Irving et al., 2018; Khan et al., 2024). The research shows debate helps weaker judges reach truthful answers.
- **Divergent-thinking debate (MAD):** an "angel" and a "devil" agent are forced to disagree, to avoid early agreement (Liang et al., 2023).
- **Orchestrator-workers with a synthesizer** (Lesson 12): workers answer in parallel and one synthesizer reconciles them. This is debate with a single round and a judge.

### When it helps and when it doesn't

| Helps | Hurts |
|---|---|
| Errors are diverse and uncorrelated across agents | All agents share a misconception |
| Correct answers are checkable or persuasive (math, rules, code) | Persuasive but wrong arguments win (rhetoric beats truth) |
| Latency budget of seconds to minutes | Real-time UX |
| High cost of a wrong answer | Simple lookups (one retrieval is cheaper) |

Smit et al. ("Should we be going MAD?", 2023) found that debate methods do **not** reliably beat simpler ensembling such as self-consistency, and are sensitive to hyperparameters. Measure before you adopt.

## 3. What changed by Oct 2026

- **Multi-agent is a platform feature now.** Hosted agent platforms ship dynamic multi-agent workflows and rosters. LangGraph 1.2, Microsoft Agent Framework 1.x (group-chat and concurrent orchestrations) and Google ADK 2.x (graph workflows) all make a debate graph a few dozen lines. The question has moved from "can we build it?" to "does it beat voting at the same cost?".
- **Model diversity is cheap.** With GPT-6 Luna, Gemini 3.8 Flash, open-weight models and several frontier tiers available behind one gateway, cross-model debate costs the same engineering effort as a single-model setup. Use that, because diversity is where the gains come from.
- **Advisor / consult tools** (for example ADK's `ModelConsultTool` and provider advisor tools) give you a lightweight form of the pattern: one agent asks a second model for a critique under a budget, instead of running full rounds.
- **2026 update, System One judge and stop condition:** two parts of debate are classification problems. "Have the agents converged?" is a `noul`, and "Which candidate answer is best supported?" is a `choice` with probabilities. A Jev or Clef call answers either in tens of milliseconds, so trusted code can stop early once P(converged) is high, saving whole rounds (Lessons 55–57).

## 4. Build it

`code/main.py` simulates debate across 2,000 seeded questions:

- `Debater` has a `family` (the underlying model), a skill level, a tendency toward a shared misconception, and stubbornness.
- `draw_traps()` marks some questions as "traps" **per model family**, so agents from the same family fail together. This models correlated errors.
- `topology()` builds full mesh, ring, star or no-communication graphs. `update()` revises an answer from what an agent sees. **Assumption:** a correct peer answer persuades 45% of the time, which is the optimistic premise debate depends on.
- `debate()` stops early on agreement and counts tokens. `self_consistency()` is the voting baseline from a single model.

```bash
python3 code/main.py
```

What to look for:

- Same-budget self-consistency gains little over k=15 because the samples share the model's traps.
- Diverse debate beats it at the same budget.
- The ring keeps most of the accuracy at about 70% of the tokens.
- Five clones lose accuracy because they share every trap.

Change the 0.45 persuasion rate to 0.1 and watch most of debate's advantage disappear.

## 5. Use it in production

- **Run the baseline first:** single agent, self-consistency at k samples, and independent cross-model voting, all at the same token budget. Adopt debate only if it wins on your eval set (Lesson 30).
- **Diversify deliberately:** different model families first, different prompts and roles second, temperature last.
- **Bound the cost:** N ≤ 3–5, R ≤ 2–3, sparse topology, early stop on convergence, and per-question token budgets.
- **Framework fit:** LangGraph or ADK graphs for stateful multi-round debate with checkpoints. Microsoft Agent Framework group chat for role-based debate. A plain `asyncio.gather` plus a judge is often enough.
- **Log it:** every round's answers as child spans of one `invoke_agent` (Lesson 23), so you can see where convergence went wrong.

## 6. Architect's lens

1. **Correlation is the hidden variable.** Debate's value is roughly the diversity of its participants' errors. Measure pairwise error correlation on your eval set before you choose the roster.
2. **Debate is a latency multiplier.** R sequential rounds of an LLM call each. Use it for offline, asynchronous or high-stakes decisions, not for chat UX.
3. **Persuasion is not truth.** Stronger rhetoric can carry a wrong answer. Where you can, ground the final step in a verifier: tests, a calculator, retrieval, or a checker. Then a debate's output is a candidate, not a verdict.
4. **Watch the hub.** In star topologies and synthesizer patterns, the hub's model quality caps the system's quality. Rotate hubs or use the strongest model there.
5. **Cheap judges change the economics.** A decision-model stop condition, plus a final `choice` over candidates, can cut rounds in half compared with fixed-R debate. Track rounds per question as a cost KPI.

## 7. Exercises

1. Lower the persuasion rate in `update()` from 0.45 to 0.1. At what value does debate stop beating independent voting?
2. Add a "forced disagreement" first round (MAD-style) where at least two agents must give different answers. Does accuracy for the clone team recover?
3. Replace majority aggregation with a judge that picks the answer given by the most distinct model families. Compare accuracy.
4. Add a convergence stop driven by a simulated P(converged), and report rounds saved versus accuracy lost at thresholds 0.7, 0.8 and 0.9.
5. Compute pairwise error correlation between the five debaters across the 2,000 questions. Which single swap would most improve the team?

## 8. Key terms

| Term | Meaning |
|---|---|
| Multi-agent debate | N agents answer, read peers, revise over R rounds, then aggregate |
| Self-consistency | Sample one model k times and take the majority. The baseline for debate |
| Topology | Graph of which agents read which peers |
| Sparse topology | Each agent reads only some peers (ring, star) to cut cost |
| Convergence collapse | Agents agree early on a wrong answer |
| Correlated errors | Agents fail on the same inputs, often because they share a model or prompt |
| Judge debate | Opposing debaters with a separate judge deciding |
| Stop condition | Rule or classifier that ends rounds once agents agree |

## 9. Quick check

<details><summary>1. Why do five copies of one model debate poorly?</summary>They share training data, priors and misconceptions, so their errors are correlated. Reading each other's answers reinforces the shared mistake instead of correcting it.</details>
<details><summary>2. What baseline must debate beat before you ship it?</summary>Self-consistency or independent cross-model voting at the same token budget, on your own eval set.</details>
<details><summary>3. Why does a ring topology often cost less for similar accuracy?</summary>Each agent reads 2 peers instead of N-1, so tokens per round drop sharply, while information still spreads around the ring over a couple of rounds.</details>

## References

- Du et al., Improving Factuality and Reasoning through Multiagent Debate: https://arxiv.org/abs/2305.14325
- Li et al., Improving Multi-Agent Debate with Sparse Communication Topology: https://arxiv.org/abs/2406.11776
- Liang et al., Encouraging Divergent Thinking through Multi-Agent Debate: https://arxiv.org/abs/2305.19118
- Smit et al., Should we be going MAD?: https://arxiv.org/abs/2311.17371
- Khan et al., Debating with More Persuasive LLMs Leads to More Truthful Answers: https://arxiv.org/abs/2402.06782
- Irving et al., AI Safety via Debate: https://arxiv.org/abs/1805.00899
- Wang et al., Self-Consistency: https://arxiv.org/abs/2203.11171
