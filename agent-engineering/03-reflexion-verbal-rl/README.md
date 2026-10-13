# 03 · Reflexion: Verbal Reinforcement Learning

> **Short answer:** Reflexion lets an agent learn from a failed attempt without touching its weights. After each failure it writes a short, specific note about what went wrong, stores that note in episodic memory, and reads it before the next try. The reflection plays the role a gradient plays in classic RL. Use it when you have a clear failure signal and the same kind of task comes back. Skip it when failures are external (outages, flaky tools) or the agent already succeeds first time.

**Type:** Build · **Languages:** Python (stdlib) · **Time:** ~60 min

---

## 1. The problem

An agent fails. Classic reinforcement learning would fix that with thousands of trials, a reward signal and a weight update. Almost nobody running an agent in production has that budget for every failure mode, and many failures are specific to one repo, one customer or one API.

Reflexion (Shinn et al., NeurIPS 2023, arXiv:2303.11366) asks a cheaper question: what if the agent simply explains its own failure in plain language and keeps that explanation in its prompt next time? No gradients, no fine-tuning. The paper reported clear gains over ReAct on ALFWorld and HotpotQA and strong results on HumanEval-style code generation, all from text carried between trials.

## 2. The concept

### Three roles and one buffer

```
Actor          : runs a trajectory (usually a ReAct-style loop)
Evaluator      : scores the trajectory (pass/fail, heuristic, or self-judged)
Self-Reflector : turns a failure into one actionable sentence
Episodic memory: bounded list of reflections, prepended to the next trial
```

```
 ┌────────┐  trajectory  ┌───────────┐  fail  ┌────────────────┐
 │ Actor  │ ───────────► │ Evaluator │ ─────► │ Self-Reflector │
 └────────┘              └───────────┘        └───────┬────────┘
     ▲                         │ pass                 │ reflection
     │                         ▼                      ▼
     │                       done            ┌──────────────────┐
     └───────────── reads before next trial ─┤ Episodic memory  │
                                             └──────────────────┘
```

### Three kinds of evaluator

| Evaluator | Signal | Example | Strength |
|---|---|---|---|
| Scalar / ground truth | External pass/fail or number | Tests pass, task env reports success | Strongest. Use whenever you can |
| Heuristic | Known failure signatures | Same action twice, more than N steps | Cheap safety rail |
| Self-evaluated | Model judges its own trace | No ground truth available | Weakest. Pair with tool-grounded checks (Lesson 05) |

A sensible default: ground truth when it exists, heuristics always on, self-evaluation only as a fallback.

### What makes a good reflection

A good reflection names the cause and the next move: "sum was 6, 14 short; raise the values." A bad one is generic ("be more careful") or superstitious ("the network was down, avoid that tool"). Generic notes waste tokens. Superstitious notes actively hurt future runs.

### When it works, when it does not

Works when the failure signal is clear, the task class repeats and there is enough action budget left to use the lesson. It does not help when the agent already succeeds, when the cause is outside the agent's control, or when one flaky run gets promoted to a permanent rule.

### Memory rot

Reflections pile up. Some become stale, some contradict each other and every one costs prompt tokens. You need capacity limits, TTLs, deduplication and periodic consolidation. Lesson 08 moves that consolidation off the hot path.

## 3. What changed by Oct 2026

- **Reflection became a harness feature, not a paper trick.** Agent instruction files (AGENTS.md, now stewarded by the Agentic AI Foundation and read by Codex, Cursor, Copilot, Gemini CLI and others) are where coding agents write durable lessons. "Learnings" files and skill folders (`SKILL.md`) are reflections that survive across sessions.
- **Hosted memory stores exist.** Provider agent platforms now ship managed memory stores and a client-side memory tool, so the episodic buffer can live outside the prompt and be loaded on demand.
- **Append-only transcripts matter.** Current frontier models preserve their reasoning across turns, and editing history invalidates it and breaks prompt caching. Add reflections as new messages or as a memory file. Do not rewrite earlier turns.
- **Graders are first-class.** Hosted agent platforms let you attach an outcome rubric and grader to a run, LangChain Deep Agents 0.7 ships a `RubricMiddleware`, and Google ADK 2.x has graph nodes for checks. That is the Evaluator role packaged for you.
- **Sleep-time reflection.** Letta popularized running the Self-Reflector asynchronously (Lesson 08). The same idea now appears as background agents and scheduled routines on several platforms.
- **2026 update, System One evaluator gate:** "Is this failure caused by the agent or by the environment?" is a typed `choice` question. A decision model (Jev or Clef, Lessons 55–56) can answer it in tens of milliseconds, so only agent-caused failures reach the expensive Self-Reflector and the memory.

## 4. Build it

`code/main.py` solves a toy puzzle: choose three integers in 1..9 that sum to 20.

- `Actor`: a scripted policy that changes its attempt only when it holds a relevant lesson.
- `evaluate`: ground-truth sum check plus two heuristics (`repeat`, `out_of_range`) and a simulated `tool_outage`.
- `reflect`: turns a verdict into a specific sentence and a lesson tag.
- `EpisodicMemory`: capacity, TTL, deduplication by lesson tag, and a filter that refuses to store external failures.
- `run`: a baseline with memory off and a Reflexion run with memory on and a checker outage on trial 2.

```bash
python3 code/main.py
```

What to look for: the baseline repeats `[1, 2, 3]` six times. The Reflexion run raises the values after trial 1, ignores the outage on trial 2 instead of learning from it, overshoots on trial 3, then fixes the last value and passes on trial 4. The final block shows exactly what would be prepended to the next prompt.

## 5. Use it in production

- **LangGraph 1.2:** a reflection node that scores the output and routes back to the actor, with checkpoints so retries are resumable.
- **LangChain Deep Agents 0.7:** `RubricMiddleware` as the Evaluator and a file system for the reflection buffer.
- **OpenAI Agents SDK:** no built-in Reflexion. Use an output guardrail to reject a result, a session to carry reflections, and `RunState` to resume.
- **Google ADK 2.x:** a graph workflow with an evaluator node and a memory service (the SQLite memory service is fine for local work).
- **Coding agents:** AGENTS.md or a dedicated learnings file as the long-term buffer, reviewed by a human before it is merged.
- **Letta:** sleep-time agents that reflect on finished conversations and edit memory blocks.

## 6. Architect's lens

1. **The evaluator is the whole game.** A Reflexion loop is only as good as its failure signal. Spend your effort on ground-truth checks (tests, schemas, assertions) before you spend it on reflection prompts.
2. **Gate what enters memory.** Every stored reflection is a permanent prompt tax and a possible poisoning vector (OWASP Agentic ASI06, Memory & Context Poisoning). Require a cause tag, deduplicate, reject external failures, and give each entry a TTL and a source trial.
3. **Bound the retry budget.** Set a maximum trial count and a cost ceiling per task. Log "trials to success" as a metric; if it climbs, the reflections are not helping.
4. **Separate session lessons from global lessons.** A note about one customer's data should not leak into every run. Scope memory by task class and tenant.
5. **Measure the lift.** Run with and without the buffer on a fixed eval set. If success rate does not move, delete the feature; it is costing tokens for nothing.

## 7. Exercises

1. Replace pass/fail with a distance score (`abs(delta)`) and let the actor take proportional steps. Does it converge in fewer trials?
2. Set `ttl_trials` to 1. Which lesson expires too early, and what does the actor do without it?
3. Write an adversarial actor that ignores reflections unless they contain an exact phrase. What does that teach you about reflection formatting?
4. Add a stand-in decision gate that classifies each failure as `agent` or `environment` before reflection, and count how many reflector calls it saves.
5. Persist the memory to a JSON file between two runs of the script and show that the second run starts smarter.

## 8. Key terms

| Term | Meaning |
|---|---|
| Reflexion | Actor, Evaluator and Self-Reflector plus episodic memory (Shinn et al., 2023) |
| Verbal reinforcement | A natural-language lesson in the next prompt instead of a weight update |
| Episodic memory | Bounded buffer of reflections for one task class |
| Heuristic evaluator | Rule that detects a known failure shape, such as a repeated action |
| Superstition | A stored "lesson" drawn from an external or one-off failure |
| Memory rot | Stale or conflicting reflections that slow and mislead later runs |
| Sleep-time reflection | Running the reflector asynchronously, off the user's critical path |

## 9. Quick check

<details><summary>1. Why should a tool outage not produce a stored reflection?</summary>The cause is outside the agent's control. Storing it teaches the agent to avoid a tool that is usually fine, which is superstition, and it wastes prompt space.</details>
<details><summary>2. What replaces the gradient in Reflexion?</summary>A specific natural-language reflection prepended to the next trial. It changes behaviour through the prompt, not through the weights.</details>
<details><summary>3. Which evaluator should you prefer, and why?</summary>Ground truth (tests, environment success) whenever it exists, because self-evaluation by the same model is a weak and biased signal.</details>

## References

- Shinn et al., Reflexion: Language Agents with Verbal Reinforcement Learning (arXiv:2303.11366): https://arxiv.org/abs/2303.11366
- Yao et al., ReAct (arXiv:2210.03629): https://arxiv.org/abs/2210.03629
- Letta, Sleep-time Compute: https://www.letta.com/blog/sleep-time-compute
- AGENTS.md: https://agents.md/
- LangGraph docs: https://docs.langchain.com/oss/python/langgraph/overview
- OWASP Top 10 for Agentic Applications 2026: https://genai.owasp.org/
