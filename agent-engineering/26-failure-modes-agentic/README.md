# 26 · Failure Modes: Why Agents Break

> **Short answer:** Agent failures are not random. They fall into a small set of recurring patterns: hallucinated tools or arguments, tool misuse, scope creep, lost constraints, loops, cascading errors, and the most dangerous one, **claiming success that never happened**. Research taxonomies (MASFT/MAST, with 14 modes in 3 categories) and the **OWASP Top 10 for Agentic Applications** (where cascading failures are ASI08) give you shared names for them. Name the modes, write a detector for each, check claims against the real world state, and track the rates per release.

**Type:** Learn + Build · **Languages:** Python (stdlib) · **Time:** ~60 min

---

## 1. The problem

Your agent passes 90% of evals. The other 10% is not noise. When you read those traces, the same few stories repeat: it called a tool that doesn't exist, it refunded $120 when the user said "up to $50", it retried the same call four times, or it said "Done!" after three 404s.

Two properties make agent failures worse than ordinary model errors:

1. **They act.** A wrong sentence is embarrassing. A wrong refund, email or `DELETE` is an incident.
2. **They look fine.** Most failed runs end with a confident, well-formatted message and no exception. Monitoring that only counts crashes sees almost nothing.

## 2. The concept

### Research taxonomies

**MASFT** (Cemri et al., "Why Do Multi-Agent LLM Systems Fail?", arXiv 2503.13657; later versions call it MAST) annotated multi-agent traces into 14 modes in 3 categories, with high inter-annotator agreement:

| Category | Modes |
|---|---|
| Specification and system design | Disobey task spec · disobey role spec · step repetition · loss of conversation history · unaware of termination conditions |
| Inter-agent misalignment | Conversation reset · fail to ask for clarification · task derailment · information withholding · ignored other agent's input · reasoning-action mismatch |
| Task verification and termination | Premature termination · no or incomplete verification · incorrect verification |

The central claim: many failures come from **system design**, so a better base model alone won't remove them.

The **Microsoft Taxonomy of Failure Modes in Agentic AI Systems** adds a risk-register view. Existing AI harms (bias, hallucination, data leakage) are amplified by autonomy, and new ones appear: actions at scale, tool misuse, goal drift, memory poisoning. Surveys of agent hallucination (arXiv 2509.18970) split problems into instruction-following deviation and long-range context misuse, with plan-level errors of **omission, redundancy and disorder**.

### The field checklist

| Mode | Signature in a trace | First mitigation |
|---|---|---|
| Hallucinated tool or args | Tool name not in registry; invented IDs | Strict schemas; reject unknown tools |
| Tool misuse | Right tool, wrong argument names or types; 422s | Argument validation (Lesson 06) |
| Scope creep | Tools or targets outside the task's allowlist | Per-task tool scoping (Lesson 36) |
| Context loss | Early constraint violated late ("up to $50" → $120) | Constraint re-check in code before acting |
| Step repetition | Same call, same args, 3+ times | Loop detector plus a step budget |
| Cascading error | First failure followed by steps that consume its output | Fail fast; stop on unrecoverable errors |
| **Success hallucination** | "Done!" while world state is unchanged or wrong | **Verify state after acting**; never trust the claim |

```
 step 1: lookup_sku("X-99") ─► 404      ← root cause (hallucinated SKU)
 step 2: get_order("X-99")  ─► 404      ┐
 step 3: refund("X-99",40)  ─► 404      ├ cascade radius = 3
 step 4: send_email("refund done")      ┘ scope creep + false claim
 final : "Done, refund completed."      ← success hallucination
```

## 3. What changed by Oct 2026

- **OWASP Top 10 for Agentic Applications (2026 edition, published Dec 2025)** gives failure and security modes shared IDs: **ASI08 Cascading Failures**, ASI02 Tool Misuse and Exploitation, ASI06 Memory and Context Poisoning, ASI10 Rogue Agents and others. Use these IDs in incident reports and risk registers.
- **Failures now include the evaluator.** A 2026 UC Berkeley RDI study (secondary coverage) showed an automated agent reward-hacking 8 major agent benchmarks by attacking their graders. "Editing the tests until they pass" belongs on your failure list (Lesson 19).
- **Platforms ship failure analysis.** AWS AgentCore failure insights, LangSmith Trajectories and Engine, Phoenix trace clustering and Braintrust's agent-driven trace queries all cluster failing traces automatically. They still need your domain detectors to say *what* failed.
- **Long-running and background agents** (hours-long runs, scheduled agents) make loop and context-loss failures more expensive. Step budgets, task budgets and checkpoint verification are now standard harness features.
- **"Characterizing Faults in Agentic AI"** (arXiv 2603.06847) places faults in orchestration, internal state evolution and environment interaction, not just in model output.
- **2026 update, System One detectors:** content-level modes such as scope creep, derailment and "does this final message claim success?" are typed classification questions. A Jev or Clef `noul` per mode can tag 100% of traces cheaply, and deterministic state checks confirm the expensive cases (Lessons 55–56).

## 4. Build it

`code/main.py` is a failure-mode tagger over seven refund-agent traces:

- `TOOL_REGISTRY` defines the real tools and their exact argument sets.
- Seven detector functions return the step indexes where each mode appears: hallucinated tool, tool misuse, scope creep, context loss (constraint `amount<=50`), step repetition, success hallucination (claim vs `world_after`) and cascading error (with a **cascade radius**).
- Each trace carries ground-truth labels, so the script prints per-detector **precision and recall**.
- `t07` fails honestly ("service unavailable; nothing changed") and is correctly left untagged.

```bash
python3 code/main.py
```

What to look for: `t02` lights up four modes from one hallucinated SKU. Success hallucination is the most common mode. The naive cascade detector produces a false positive on `t04`, where the agent recovered from a 422. That is the first detector you would improve.

## 5. Use it in production

- **Emit the evidence:** tool name, arguments, status code and result reference for every step (OTel `execute_tool` spans, Lesson 23), plus a post-run **state probe** (did the refund record actually change?).
- **Run detectors in three places:** in the harness before acting (block), on traces after the run (tag), and in CI on eval datasets (gate releases on mode rates).
- **Platforms:** Phoenix or LangSmith for clustering, Langfuse for annotation queues, and your own detectors for domain modes no vendor can know.
- **Budgets:** max steps, max identical calls, max spend per task. On a breach, end with an honest failure message, never a guess.

## 6. Architect's lens

1. **An honest failure is a success of the system.** Design the harness so "I couldn't do it" is easy and rewarded, and "Done!" requires evidence. Most success hallucinations happen because the loop has no clean way to give up.
2. **Measure cascade radius, not just failure count.** One root cause that triggers five downstream calls is a different incident class from five independent slips. Fail-fast rules shrink the radius.
3. **Detectors are classifiers too.** Report their precision and recall against labeled traces. A noisy detector trains on-call engineers to ignore it.
4. **Track per-mode rates per release.** A prompt change that cuts tool misuse but doubles scope creep is a regression. Gate deploys on mode budgets (for example, success hallucination < 0.5%).
5. **Fix the system, not the sample.** MAST's lesson is that most modes trace back to specification, role design and missing verification. Add a verifier step or a tighter tool scope before you reach for a bigger model.

## 7. Exercises

1. Fix the cascade false positive: count a downstream step only if it reuses an argument value from the failed step.
2. Add a `premature_termination` detector: the run ends with steps remaining in the plan and no failure message.
3. Add `reasoning_action_mismatch`: the agent's stated next action ("I'll look up the order") differs from the tool it actually calls.
4. Write 10 more traces from a product you know, label them, and report detector precision and recall. Which mode dominates?
5. Map each detector to an OWASP Agentic ID (ASI01–ASI10) where one applies. Which modes are reliability-only and which are security issues?

## 8. Key terms

| Term | Meaning |
|---|---|
| MASFT / MAST | 14-mode, 3-category taxonomy of multi-agent system failures |
| Success hallucination | Agent claims completion while world state shows otherwise |
| Cascading error | One early failure propagates into later steps (OWASP ASI08) |
| Cascade radius | Number of downstream steps affected by a root failure |
| Scope creep | Agent acts beyond the task's tools or targets |
| Context loss | Early constraint forgotten or misapplied later |
| Step repetition | Same action with the same arguments repeated without progress |
| State probe | Independent check of the real system after the agent acts |

## 9. Quick check

<details><summary>1. Why is success hallucination the most dangerous mode?</summary>It hides every other failure. Downstream systems and humans trust the "done" message, so the error surfaces later, often in front of the customer.</details>
<details><summary>2. What is the reliable way to detect it?</summary>Compare the claim with an independent state probe after the run (database row, API read-back, file hash). Don't ask the model whether it succeeded.</details>
<details><summary>3. An agent fails with "the refund service is down; nothing changed." Is that a failure mode?</summary>The task failed, but the agent behaved correctly: it reported truthfully and took no partial action. That is the behavior you want.</details>

## References

- Cemri et al., Why Do Multi-Agent LLM Systems Fail? (MASFT/MAST): https://arxiv.org/abs/2503.13657
- Microsoft, Taxonomy of Failure Mode in Agentic AI Systems: https://www.microsoft.com/en-us/security/blog/2025/04/24/new-whitepaper-outlines-the-taxonomy-of-failure-modes-in-ai-agents/
- Characterizing Faults in Agentic AI: https://arxiv.org/abs/2603.06847
- LLM-based Agents Hallucination Survey: https://arxiv.org/abs/2509.18970
- OWASP Top 10 for Agentic Applications 2026 (summary): https://www.giskard.ai/knowledge/owasp-top-10-for-agentic-application-2026
- AWS AgentCore release notes (failure insights): https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/release-notes.html
