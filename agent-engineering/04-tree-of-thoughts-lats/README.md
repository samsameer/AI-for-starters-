# 04 · Tree of Thoughts and LATS: Deliberate Search

> **Short answer:** A chain of thought is a single path. If step one is wrong, every later step builds on that mistake. Tree of Thoughts (ToT) turns reasoning into a tree: propose several next steps, score each one and keep or prune them. LATS goes further and runs Monte Carlo Tree Search with the model as policy, value function and reflector. Search buys correctness with many more model calls, so use it only when you have a reliable evaluator and correctness matters more than latency.

**Type:** Build · **Languages:** Python (stdlib) · **Time:** ~75 min

---

## 1. The problem

The Game of 24 gives you four numbers and asks for +, −, ×, ÷ to make 24. It looks trivial, yet in the ToT paper GPT-4 with chain-of-thought solved only 4% of the hard set. The model grabs an attractive first move (say `4 × 6 = 24`), and then has nothing useful to do with the two numbers left over. It cannot step back.

Reasoning that can fail early needs three abilities: propose alternatives, judge which are promising, and backtrack from dead ends. That is search. ToT (Yao et al., arXiv:2305.10601) and LATS (Zhou et al., arXiv:2310.04406) are its two canonical forms for language agents.

## 2. The concept

### Tree of Thoughts

A node is a partial solution ("a thought"). The model proposes K children per node and scores each one. A search strategy (BFS with a beam, or DFS with backtracking) chooses what to expand next.

```
                     [4 6 4 1]
          ┌──────────────┼───────────────┐
      4*6=24          6+1=7           6-1=5
     [4 1 24]        [4 4 7]         [4 4 5]
   "likely 0.9"    "likely 0.6"    "likely 0.6"
         │               │               │
   all children     4*7=28 [4 28]    4*5=20 [4 20]
   "impossible"      "sure"           "sure"
     (pruned)          │                 │
                    28-4=24 ✓         4+20=24 ✓
```

The evaluator is the load-bearing part. The paper used three styles: a `sure / likely / impossible` label, a 1–10 score, and a vote across candidates. Note that the most attractive-looking node above is a dead end. A greedy chain takes it; a beam of width 5 does not.

### LATS: MCTS with language

LATS unifies ReAct, ToT and Reflexion. The model plays three roles:

| Role | Comes from | Job |
|---|---|---|
| Policy | ReAct (Lesson 01) | Propose candidate next actions |
| Value function | ToT | Score a partial trajectory, mixed with real environment feedback |
| Self-reflector | Reflexion (Lesson 03) | Explain failed rollouts and steer later ones away from them |

Each iteration runs the four MCTS phases:

```
Select        walk down by UCT:  Q(s,a) + c · sqrt( ln N(s) / N(s,a) )
Expand        ask the policy for children of the chosen leaf
Evaluate      score the new node (value model, tests, environment reward)
Backpropagate add the reward to every ancestor's visit count and total
```

The first UCT term exploits nodes that have paid off. The second explores nodes that have been tried rarely. The constant `c` is a real tuning knob, as the demo shows.

### The cost reality

Search multiplies calls. The ToT paper reports large token multiples over CoT on Game of 24, and LATS is in the same range. Reserve search for tasks where:

- one trajectory is demonstrably not enough,
- correctness beats latency, and
- you have a **cheap, reliable value function** (unit tests, a checker, an exact target).

With a noisy evaluator, search can make things worse: it efficiently finds a wrong answer that scores well.

## 3. What changed by Oct 2026

- **Search moved inside the model.** Current frontier reasoning models do much of this exploration in hidden thinking, controlled by an effort setting (`low` up to `xhigh`/`max` on several provider APIs). For many puzzles, raising effort on one call beats an external ToT harness. External search still wins when the value function is a real tool: tests, a compiler, a simulator.
- **Parallel sampling plus a verifier is the common production form.** Coding agents generate several candidate patches in sandboxes (Cloudflare Sandboxes, LangSmith Sandboxes, OpenAI Sandbox agents), run the tests, and keep the best. That is a one-level tree with a ground-truth value function.
- **Evolutionary search reached the frontier.** AlphaEvolve (arXiv:2506.13131) and its successors use program search with machine-checked fitness (Lesson 11).
- **Graph engines host the search loop.** LangGraph 1.2 adds per-node timeouts and Google ADK 2.x has a graph workflow engine, so a bounded search can live in a subgraph with its own budget.
- **Model consult tools.** ADK's `ModelConsultTool` and provider "advisor" tools let a cheap model run the search and consult a stronger one only at hard nodes.
- **2026 update, System One value function:** the ToT `sure / likely / impossible` label is a typed `choice` (or `score`) question. A decision model such as Jev or Clef (Lessons 55–56) returns calibrated probabilities for all labels in one fast pass, which makes per-node evaluation affordable. Keep the thresholds in your code.

## 4. Build it

`code/main.py` solves three Game of 24 puzzles with exact `Fraction` arithmetic and counts every proposal and evaluation as one "model call".

- `propose`: the policy. Combines any two numbers with any operator, deduplicating equivalent states.
- `judge`: the value function. Returns `sure` or `impossible` when two numbers remain (an exact check), otherwise a `likely` score from a simple heuristic.
- `greedy_chain`: chain-of-thought with no backtracking. Always takes the top-scored child.
- `tot_beam`: ToT breadth-first search with a beam width and `impossible` pruning.
- `lats`: MCTS with UCT selection, backpropagation and a reflection set that remembers dead ends so they are never expanded again.

```bash
python3 code/main.py
```

What to look for:

- The chain fails all three puzzles. On `[4, 6, 4, 1]` it grabs `4*6=24` first, which is exactly the trap.
- Beam width 1 fails, beam width 5 solves the first two at roughly 2–3x the calls.
- `[3, 3, 8, 8]` (the answer is `8 / (3 − 8/3)`) defeats the beam because the heuristic dislikes the fractional intermediate. MCTS solves it because exploration keeps revisiting low-scored branches.
- The exploration knob: with `c = 0.1` MCTS gets stuck, while larger `c` finds the answer faster on this instance.

## 5. Use it in production

- **Best-of-N with a verifier:** run N candidates in parallel sandboxes and pick by tests. This is the simplest search that pays.
- **LangGraph 1.2:** a search subgraph with a node budget, per-node timeouts and checkpointing. The LangChain LATS tutorial remains the reference implementation.
- **Google ADK 2.x:** a graph workflow with a loop node and an evaluator node. `ModelConsultTool` escalates hard nodes to a stronger model.
- **Reasoning effort:** before building search, try one call at a higher effort setting and compare quality, latency and cost on your eval set.
- **Gate it:** wrap search behind `if hard_task and has_reliable_checker` so easy traffic never pays the multiplier.

## 6. Architect's lens

1. **The value function is the product.** A tree search is only as good as its scoring. Invest in ground-truth evaluators (tests, schema checks, simulators) before you tune the search.
2. **Budget in calls, tokens and wall-clock.** Put hard caps on depth, width, iterations and spend. Report "calls per solved task" next to accuracy, or the metric will hide the cost.
3. **Heuristics have blind spots.** The demo's beam fails on `[3, 3, 8, 8]` because the scorer penalizes the intermediate state that leads to the answer. Keep some exploration (sampling, UCT, diversity) so the evaluator's bias cannot prune the only path.
4. **Parallelism changes the latency math.** Beam and best-of-N parallelize well. MCTS is sequential by nature. Choose the form that fits your latency budget.
5. **Search amplifies reward hacking.** Optimizing hard against a leaky checker finds the leak. Hold out a second evaluator for final acceptance.

## 7. Exercises

1. Run LATS with five different seeds at each `c`. Plot iterations to solve. Is `c = 3.0` reliably better, or did one seed get lucky?
2. Add random noise to `judge` scores. At what noise level does beam width 5 stop solving `[4, 6, 4, 1]`?
3. Implement DFS with backtracking and an `impossible` prune. Compare its call count to the beam on all three puzzles.
4. Replace the heuristic with a stand-in decision model that returns a probability for each of `sure`, `likely` and `impossible`, and expand only nodes where `P(impossible) < 0.7`.
5. Write a one-paragraph routing rule: given task shape, evaluator quality and latency budget, choose between a single call at higher effort, best-of-N, beam ToT and MCTS.

## 8. Key terms

| Term | Meaning |
|---|---|
| Tree of Thoughts | Reasoning as a tree of partial solutions with self-evaluation and search |
| LATS | Language Agent Tree Search: MCTS with the model as policy, value and reflector |
| Beam search | Keep only the top-k nodes at each depth |
| UCT | Selection rule that balances exploitation (Q) and exploration (visit counts) |
| Value function | Scores how promising a node is: a model judgment, a test result or a reward |
| Backpropagation | Pushing a leaf's reward up to all of its ancestors |
| Best-of-N | Sample N full candidates and select one with a verifier |

## 9. Quick check

<details><summary>1. Why does the greedy chain fail on [4, 6, 4, 1]?</summary>Its first move, 4*6=24, scores highest but leaves 4 and 1, which cannot be combined into a neutral 1 with 24 already used. Without backtracking the chain cannot recover.</details>
<details><summary>2. Why can a beam search miss a solution that MCTS finds?</summary>The beam discards every node outside the top-k forever. If the heuristic underrates the only correct path, it is pruned. MCTS keeps exploring low-visit branches, so it can come back to it.</details>
<details><summary>3. When should you not use tree search?</summary>When one trajectory already works, when latency is tight, or when there is no reliable evaluator. A noisy scorer turns search into an efficient way of finding confident wrong answers.</details>

## References

- Yao et al., Tree of Thoughts (arXiv:2305.10601): https://arxiv.org/abs/2305.10601
- Zhou et al., Language Agent Tree Search (arXiv:2310.04406): https://arxiv.org/abs/2310.04406
- Kocsis and Szepesvári, Bandit based Monte-Carlo Planning (UCT, ECML 2006): https://doi.org/10.1007/11871842_29
- Novikov et al., AlphaEvolve (arXiv:2506.13131): https://arxiv.org/abs/2506.13131
- LangGraph docs: https://docs.langchain.com/oss/python/langgraph/overview
- Google ADK: https://google.github.io/adk-docs/
