# 20 · Benchmarks: WebArena and OSWorld-Verified

> **Short answer:** WebArena measures web agents on self-hosted sites. OSWorld measures computer-use agents on real desktops driven by screenshots, mouse and keyboard. Both decide success by checking the final **state of the environment**, not by trusting what the agent says. In Oct 2026, **OSWorld-Verified** is the desktop number everyone quotes, and its top reported scores (mid-80s) are close to saturation. Use these benchmarks to understand failure modes (grounding, operational knowledge, wasted steps). Use your own task flows to choose a vendor.

**Type:** Learn · **Languages:** Python (stdlib) · **Time:** ~60 min

---

## 1. The problem

Tool-calling evals (Lesson 19) assume clean APIs. Real work happens in GUIs: 20 clicks through a checkout, a settings pane three menus deep, a spreadsheet that has to be reformatted. Driving those GUIs raises three questions an API benchmark never asks:

- Can the agent **find** the right pixel? (grounding)
- Does it **know** where things live in an app? (operational knowledge)
- Does it get there without **wandering**? (trajectory efficiency)

## 2. The concept

### WebArena (Zhou et al., ICLR 2024)

- 812 long-horizon tasks on four **self-hosted** apps (shopping site, forum, GitLab-like dev tool, CMS), plus map, calculator and wiki utilities.
- **Execution-based evaluation.** The checker queries the app's database or API: was the order placed, was the issue closed?
- At release, the best GPT-4 agent scored 14.4% and humans scored 78.2%.
- Self-hosting is what keeps the benchmark reproducible. The apps are pinned, so live-site drift can't break it.

Extensions: **VisualWebArena** (tasks that require reading images), **WebArena Verified** (re-audited tasks and checkers), **TheAgentCompany** (a simulated company with web apps, terminal and coworkers).

### OSWorld (Xie et al., NeurIPS 2024)

- 369 tasks on real Ubuntu, Windows and macOS VMs. The agent sees screenshots and controls raw mouse and keyboard.
- Every task has a **custom state-checking script**: a file's contents, an app's config, a spreadsheet cell.
- At release, the best model scored 12.2% and humans scored 72.4%.
- **OSWorld-Verified** (2025) fixed broken tasks and checkers and moved evaluation to a more reliable cloud VM harness. It is now the canonical leaderboard.
- **OSWorld-G** isolates grounding (564 samples). **OSWorld-Human** adds expert gold trajectories and shows top agents taking far more steps than needed (1.4–2.7x at the time).

### The two classic failure modes

```
  screenshot ──► "click the Mouse button" ──► (x, y) ──► wrong element   = GROUNDING failure
                         │
                         └──► never clicks Checkout / wrong menu         = PLANNING / operational-knowledge failure
```

### State-based vs claim-based evaluation

| Evaluator | Checks | Gameable? |
|---|---|---|
| Final-message match | "Order placed" in the agent's text | Trivially |
| DOM/screenshot heuristic | The page looks right | Somewhat |
| **State check** | The DB row exists with the right items | Hard (unless the agent can write to the checker) |

## 3. What changed by Oct 2026

- **OSWorld-Verified is near saturation.** Aggregators list top system-plus-harness submissions at roughly 85–86% (reported, not independently reproduced). That is above the original 72% human baseline, so the remaining headroom is mostly task noise and long-tail operational knowledge.
- **Scores are system scores.** Top entries combine a model, a planner, a grounding model and retries. Compare harnesses, not just model names.
- **WebArena has no clean 2026 SOTA.** Many groups report WebArena Verified or private subsets. Treat any single "WebArena %" as unverified unless it names the split and harness.
- **The benchmark-gaming study** (UC Berkeley RDI, reported 2026) listed WebArena and OSWorld among eight benchmarks an automated agent could reward-hack through evaluator weaknesses. Read-only, out-of-band state checkers are mandatory.
- **The model landscape moved.** Gemini 3.8 Flash (computer use built in, preview), other frontier models with built-in computer-use toolsets, and the retirement of OpenAI's standalone Operator and Atlas browser all shift which "computer-use" product a benchmark number refers to (Lesson 21).

## 4. Build it

`code/main.py` is a pixel-level shopping app with a WebArena/OSWorld-style evaluator:

- `LAYOUT` holds element bounding boxes. `ShopApp.click(x, y)` resolves the pixel to an element and mutates cart and order state.
- Each `Task` has a gold trajectory, the agent's pixel `Step`s, the agent's final message and a **state check**.
- `run()` records grounding misses (clicked element ≠ intended element), strict state-based success, lenient final-message success, and steps over gold.
- Failures are classified as **grounding** (a miss caused the failure) or **planning** (no misses, wrong plan).

```bash
python3 code/main.py
```

What to look for: the lenient evaluator reports 5/5 and the state check reports 3/5. One failure is grounding (a click 30 px off), the other is planning (it never clicked checkout but claimed success). Solved tasks average about 1.6x the gold step count.

## 5. Use it in production

- **Benchmarks for vendor shortlists:** OSWorld-Verified (desktop), WebArena Verified or VisualWebArena (web), Online-Mind2Web (live sites, noisier).
- **Harness infrastructure:** OSWorld's VM harness, BrowserGym/AgentLab for web tasks, Docker or cloud sandboxes (Cloudflare Sandboxes, AWS AgentCore shells) for isolation.
- **Your own GUI eval:** record gold trajectories for your top 20 user flows, pin the app version, write SQL/API state checks, and run weekly. Report success, pass^k, steps-over-gold and $/task.
- **Traces:** every step should emit a span with a screenshot reference (Lesson 23), so a failure at click 180 can be debugged.

## 6. Architect's lens

1. **Separate grounding from planning in your metrics.** They have different fixes: a better grounding model or higher resolution for one, better prompts, skills or operational docs for the other. A single success rate hides which one you need.
2. **Steps are cost and risk.** Every extra click costs latency and tokens and is one more chance to act on an injected instruction (Lesson 27). Trajectory efficiency is a safety metric too.
3. **Pin and re-curate.** Upgrading a self-hosted app changes the benchmark. Version the environment together with the tasks.
4. **Near-saturated benchmarks stop ranking vendors.** Past about 80%, differences come from harness tweaks and noise. Move the decision to your own flows.
5. **2026 update:** a cheap "did the agent finish?" decision model (Jev/Clef `noul` over the final screenshot and state summary, Lessons 55–56) is a good **stop condition** inside the agent. It is **not** a substitute for the out-of-band state check in your evaluator.

## 7. Exercises

1. Add a `noise_px` parameter that jitters every click by ±N px. Plot success against N. At what N does grounding dominate?
2. Add a forum app with three tasks and gold trajectories. Reuse `run()` unchanged.
3. Add a distractor element ("Buy with 1-click") that the gold trajectory never uses. Count how often a scripted agent takes it.
4. Implement OSWorld-Human-style efficiency: report P50 and P95 steps-over-gold across 20 randomized runs.
5. Make the final-message evaluator stricter (require an order id) and show an agent that still fools it. What does that teach you?

## 8. Key terms

| Term | Meaning |
|---|---|
| Execution-based evaluation | Success decided by querying the environment's real state |
| GUI grounding | Mapping an intended UI element to the correct screen coordinates |
| Operational knowledge | Knowing which menu, shortcut or pane holds the setting |
| OSWorld-Verified | Re-audited OSWorld with fixed tasks and checkers. The 2026 leaderboard |
| Gold trajectory | Minimal expert action sequence for a task |
| Steps over gold | Agent steps ÷ gold steps. 1.0x is optimal |
| Saturation | Scores so close to the ceiling that the benchmark no longer separates systems |

## 9. Quick check

<details><summary>1. Why does WebArena self-host its apps?</summary>So tasks and checkers stay reproducible. Live sites change their layout and content, which silently breaks comparisons.</details>
<details><summary>2. An agent reports "Done!" but the order table is empty. Which failure class is it, and which evaluator catches it?</summary>Planning or success hallucination with no grounding misses. Only a state-based evaluator catches it. A final-message checker passes it.</details>
<details><summary>3. Why is an 86% OSWorld-Verified score not enough to choose a vendor?</summary>It is a system-plus-harness score near saturation on generic tasks. It doesn't reflect your apps, your risk profile, pass^k or cost.</details>

## References

- Zhou et al., WebArena: https://arxiv.org/abs/2307.13854
- Koh et al., VisualWebArena: https://arxiv.org/abs/2401.13649
- Xie et al., OSWorld: https://arxiv.org/abs/2404.07972 · OSWorld-Verified: https://os-world.github.io/
- OSWorld-Verified aggregate (reported scores): https://benchlm.ai/benchmarks/osworld-verified
- Xu et al., TheAgentCompany: https://arxiv.org/abs/2412.14161
- "Stop Comparing LLM Agents Without Disclosing the Harness": https://arxiv.org/abs/2605.23950
