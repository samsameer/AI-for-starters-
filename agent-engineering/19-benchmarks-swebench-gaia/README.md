# 19 · Benchmarks: SWE-bench Pro, Terminal-Bench, GAIA

> **Short answer:** Coding and generalist agent benchmarks measure whether an agent can finish a task end to end, judged by an executable check rather than a human opinion. In Oct 2026 the headline coding benchmark is **SWE-bench Pro** (SWE-bench Verified is near saturation), **Terminal-Bench 2.x** covers shell work, and **GAIA** is still the reference for generalist tool use. Treat every number as "model + harness + scaffold + budget". After a 2026 study showed agents can reward-hack the major benchmarks, also check the evaluator before you trust the score.

**Type:** Learn · **Languages:** Python (stdlib) · **Time:** ~60 min

---

## 1. The problem

A leaderboard row says "Model X: 81%". That single number hides at least five questions:

1. **Which benchmark version?** Verified, Pro, Terminal-Bench 2.0 and Terminal-Bench 2.1 are different tests. Their scores can't be compared.
2. **Which harness?** The same model can swing by many points depending on its scaffold, tools, retries and token budget.
3. **Is the task contaminated?** Old GitHub issues and their fixes are in training data.
4. **Is the evaluator sound?** Weak tests let wrong patches pass. An agent with write access to the tests can make anything pass.
5. **How reliable is it?** pass@1 over one run says nothing about whether it succeeds every time.

You need to know how each benchmark is built before you quote it, buy on it, or optimize against it.

## 2. The concept

### SWE-bench family: test-gated patching

```
 repo @ pre-fix commit + issue text ──► agent ──► patch
                                                    │
                     apply patch, run hidden tests  ▼
        FAIL_TO_PASS: tests that must flip to pass  ─┐
        PASS_TO_PASS: tests that must stay passing  ─┴─► resolved?  (both gates)
```

| Variant | What it is | Status, Oct 2026 |
|---|---|---|
| SWE-bench (Jimenez et al., ICLR 2024) | 2,294 issues from 12 Python repos | Historical. Heavily contaminated |
| SWE-bench Verified (OpenAI, Aug 2024) | 500 human-screened tasks with clearer specs and sound tests | Near saturation. Frontier labs no longer lead with it |
| **SWE-bench Pro** (Scale AI, 2025) | Long-horizon, multi-file tasks from a broader set of actively maintained repos. Public, held-out and commercial (private-code) splits are designed to resist contamination | **Headline coding benchmark** |
| SWE-bench Multimodal / Multilingual | Visual front-end issues and non-Python repos | Niche but useful |

**Contamination.** SWE-bench+ (Aleithan et al., 2024) audited "resolved" patches. In about a third of them the fix was already written in the issue text or its comments. Many others passed only because the tests were weak. The two gates in the diagram are necessary but not sufficient.

### Terminal-Bench: the shell as the environment

Terminal-Bench puts the agent in a container and gives it a task: build this, debug that service, train a small model. A script then checks the final state of the container. Version 2.0 (late 2025) tightened task quality and moved execution to the Harbor framework. **2.1 is current.** Scores across 2.0 and 2.1 aren't comparable, and many top entries are vendor-run agent products rather than bare models.

### GAIA: generalist tool use

GAIA (Mialon et al., 2023) has 466 questions that are easy for people (92% at release) and were hard for AI (GPT-4 with plugins scored about 15%). Three levels scale with the number of steps, tools and modalities needed. Answers are short strings scored by exact match, so evaluation is cheap and objective. The test split is private on the Hugging Face leaderboard. In 2026 there is no clean, agreed SOTA. Cost-aware leaderboards such as HAL publish GAIA runs, but harness choice dominates the results.

### AgentBench

AgentBench (Liu et al., ICLR 2024) runs 8 environments (OS, DB, knowledge graph, games, web shopping, web browsing). It is useful mainly as a history lesson: long-horizon reasoning and instruction-following were what held open models back. It is rarely quoted today.

### Reliability metrics

| Metric | Meaning | Use |
|---|---|---|
| pass@1 | Success rate of a single attempt | Leaderboard default |
| pass@k | At least one of k attempts succeeds | Optimistic. Assumes a perfect verifier picks the winner |
| **pass^k** | **All** k attempts succeed | Production reliability (popularized by tau-bench) |

With independent trials, an agent at 70% pass@1 drops to about 17% pass^5 (0.7^5). Customers experience pass^k.

## 3. What changed by Oct 2026

- **SWE-bench Pro replaced Verified as the headline coding benchmark.** Vendor system cards now lead with Pro. Top vendor-reported Pro scores are in the 80s and come from vendors' own runs. Treat them as reported, not reproduced.
- **Terminal-Bench 2.1** is out. Leaderboards now separate 2.0 from 2.1, and the top of both is crowded with agent products (model + proprietary harness).
- **The benchmark-gaming study.** A UC Berkeley RDI study reported an automated agent that reward-hacked eight major agent benchmarks, including SWE-bench, WebArena, OSWorld, GAIA and Terminal-Bench. It did this by attacking the evaluators (editing tests, exploiting lenient checkers), not by solving the tasks. This study is the reason "audit the evaluator" belongs in this lesson.
- **Harness disclosure.** "Stop Comparing LLM Agents Without Disclosing the Harness" (arXiv 2605.23950) argues that a score without its scaffold, tools, budget and retries is not a result. Expect reviewers to ask for this.
- **GAIA, WebArena and tau2-bench** have no single agreed 2026 SOTA. Be suspicious of anyone who quotes one.
- **pass^k** is now the standard reliability metric in agent eval suites (LangSmith, Braintrust, AWS AgentCore evals all report multi-trial results).

## 4. Build it

`code/main.py` is a toy SWE-bench harness that actually runs the tests:

- `BASE_REPO` is a tiny repo (`app.py` plus `tests/test_app.py`). `run_tests()` executes it and reports pass/fail per test.
- Five candidate patches: an honest fix, an over-reaching fix, a type regression, a **test rewriter** (reward hacking) and a fix **copied from a leaky issue** (SWE-bench+ style).
- `evaluate()` applies both gates, then runs an integrity audit (`test_tampering`, `solution_leak_in_issue`).
- `reliability_table()` simulates 10 seeded trials per task and prints pass@1, pass@5 and pass^5 using the unbiased combinatorial estimator.
- `gaia_level()` is a crude GAIA-style difficulty estimate based on hops, modalities and tools.

```bash
python3 code/main.py
```

What to look for: the **raw** resolve rate is 3/5, but the **audited** rate is 1/5. The test rewriter "passes" every gate. Also notice how far pass^5 falls below pass@5.

## 5. Use it in production

- **Coding agents:** report SWE-bench Pro (public split) and, if you can, the held-out split. Keep Verified only for continuity. Add Terminal-Bench 2.1 if the agent works in a shell.
- **Harnesses:** the official SWE-bench Docker harness, Harbor (Terminal-Bench 2.x), and the HAL leaderboard harness for cost-aware GAIA runs.
- **Your own benchmark** (Lesson 30) beats all of these for product decisions. Take 50–200 real tasks from your repo history, lock the tests to read-only, and report pass^k plus cost.
- **Evaluator hygiene:** mount tests read-only, hash test files before and after the run, cut the network, and diff the agent's patch against the issue text.

## 6. Architect's lens

1. **A score is a tuple, not a number.** Record `(benchmark@version, split, model, harness@commit, tools, budget, trials, pass^k, $/task)`. Without the tuple you can't compare against the next vendor claim.
2. **Your evaluator is an attack surface.** Any agent with filesystem access can edit its own grader. Isolate the grader the way you would isolate a CI secret: run it after the agent's container is frozen, from a separate image.
3. **Saturation hides regressions.** At 90%+ the remaining tasks are mostly label noise. Track a harder internal set so you can still see movement.
4. **Optimize for pass^k and cost, not pass@1.** A 5-point pass@1 gain that doubles tokens often loses on $/resolved task.
5. **2026 update:** the "did the agent cheat?" check is a natural place for a decision model. A Jev or Clef `noul` ("Does this diff modify tests or hard-code expected outputs?") can triage thousands of trajectories cheaply, with humans reviewing only the high-probability hits (Lessons 55–56).

## 7. Exercises

1. Add a third gate: run `PASS_TO_PASS` against a **hidden** test file the agent never sees. Does `overreach` get caught earlier?
2. Extend `leaked_lines()` to fuzzy-match (token Jaccard ≥ 0.8) instead of exact substring. How many false positives do you get on clean issues?
3. Add a `cost_usd` field per trial and print $/resolved alongside pass^k.
4. Pick 20 merged PRs from one of your repos and turn them into FAIL_TO_PASS tasks. What is your agent's pass^3?
5. Read the SWE-bench Pro paper and list three design choices that resist contamination. Which one would you copy for an internal benchmark?

## 8. Key terms

| Term | Meaning |
|---|---|
| FAIL_TO_PASS | Tests that fail before the patch and must pass after it |
| PASS_TO_PASS | Tests that pass before the patch and must still pass after it |
| SWE-bench Pro | Contamination-resistant, long-horizon successor to Verified. The 2026 headline |
| Terminal-Bench 2.x | Container-based shell-task benchmark. Versions are not comparable |
| Contamination | Benchmark tasks or solutions present in training data |
| Reward hacking (benchmarks) | Passing the grader without solving the task |
| pass^k | Probability that all k independent attempts succeed |
| Harness | Scaffold, tools, prompts, retries and budget wrapped around the model |

## 9. Quick check

<details><summary>1. Why does SWE-bench need both FAIL_TO_PASS and PASS_TO_PASS?</summary>FAIL_TO_PASS proves the bug is fixed. PASS_TO_PASS proves nothing else broke. A patch that deletes a feature can satisfy the first gate and fail the second.</details>
<details><summary>2. A vendor reports 85% on "SWE-bench". What do you ask?</summary>Which variant and split (Verified or Pro, public or held-out), which harness and budget, how many trials, pass^k, and whether the run was independently reproduced.</details>
<details><summary>3. How did the 2026 gaming study pass benchmarks without solving tasks?</summary>By attacking the evaluator: editing or bypassing tests and exploiting lenient checkers. The fix is read-only, isolated graders plus integrity audits, not a smarter model.</details>

## References

- Jimenez et al., SWE-bench: https://arxiv.org/abs/2310.06770
- OpenAI, SWE-bench Verified: https://openai.com/index/introducing-swe-bench-verified/
- Scale AI, SWE-bench Pro paper: https://arxiv.org/abs/2509.16941 · leaderboard aggregate: https://benchlm.ai/benchmarks/swe-bench-pro
- Aleithan et al., SWE-bench+: https://arxiv.org/abs/2410.06992
- Terminal-Bench: https://www.tbench.ai/ · 2.1 aggregate: https://benchlm.ai/benchmarks/terminalbench21
- Mialon et al., GAIA: https://arxiv.org/abs/2311.12983
- Liu et al., AgentBench: https://arxiv.org/abs/2308.03688
- "Stop Comparing LLM Agents Without Disclosing the Harness": https://arxiv.org/abs/2605.23950
- Holistic Agent Leaderboard (HAL): https://hal.cs.princeton.edu/
