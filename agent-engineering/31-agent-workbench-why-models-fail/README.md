# 31 · Agent Workbench: Why Capable Models Still Fail

> **Short answer:** A capable model is not a reliable agent. Most failures that look like "the model got it wrong" are really **workbench failures**: the agent did not know what "done" meant, where it could write, which tests counted, or how the next session should continue. The 2026 name for fixing this is **harness engineering** (Agent = Model + Harness). This lesson breaks the harness into seven agent-facing surfaces: instructions, state, scope, feedback, verification, review and handoff. It then grounds each surface in an ordinary distributed-systems primitive. Lessons 32–42 build each surface in turn.

**Type:** Learn + Build · **Languages:** Python (stdlib) · **Time:** ~45 min

---

## 1. The problem

You drop a frontier model into a real repo and ask it to add input validation. It writes plausible code, tidies a README "while it's there", says "all tests pass", and stops. You run the tests and they fail. There is no test for the new behaviour. A release script changed. Nothing records what the agent assumed, what it tried, or what is left.

The model knew Python. What it did not know was the *work*:

- what counts as done;
- which files are in bounds;
- which command is authoritative;
- who checks the result;
- how the next session picks up.

None of that lives in model weights. It lives in the environment around the model, and in this repo that environment was empty.

## 2. The concept

### Seven surfaces

| Surface | Carries | Symptom when missing | Built in |
|---|---|---|---|
| Instructions | Startup rules, forbidden actions, definition of done | Agent guesses what "shipping" means | L32, L33 |
| State | Active task, touched files, blockers, next action | Every session restarts from zero | L34 |
| Scope | Allowed/forbidden paths, acceptance, rollback | Edits leak into unrelated code | L36 |
| Feedback | Real command output fed back into the loop | "Tests pass" without running them | L37 |
| Verification | Tests, lint, smoke run, scope check | "Looks good" reaches main | L38 |
| Review | A second pass by a different role | Builder grades its own homework | L39 |
| Handoff | What changed, why, what is left | Next session rediscovers everything | L40 |

```
 task ─► scope contract ─► repo state ─► agent loop ─► feedback ─► verify ─► review ─► handoff
                              ▲                                                         │
                              └──────────────── the loop closes on files, not chat ─────┘
```

The surfaces do not depend on the model. You can swap the model and keep the surfaces. You cannot drop the surfaces and keep the reliability.

### Translate every harness pattern into primitives

The vocabulary around harnesses changes every quarter. The engineering underneath is the same set of primitives any reliable backend uses:

| Surface or pattern | Underlying primitive |
|---|---|
| Instructions (`AGENTS.md`, rules) | Policy plus function metadata loaded at startup |
| State | Session persistence: a keyed store read on every step |
| Scope | Authorization policy per task (an ACL over paths, hosts, actions) |
| Feedback | Invocation log written to a durable queue |
| Verification | A deterministic function that fails closed |
| Review | A separate worker with read-only access to the builder's output |
| Handoff | A durable record emitted by a session-end trigger |
| Hooks / middleware | Triggers wrapped around the runtime's invocation path |
| Agent Skills (`SKILL.md`, progressive disclosure) | A function registry whose metadata loads just in time |
| Background / cloud agents | Workers on a queue, each in an isolated worktree or sandbox |
| Sandboxes | The compute plane: isolated filesystem, network and lifecycle |
| MCP servers | Workers exposing functions over RPC, with capabilities as authorization |
| "Re-inject the goal when the agent stops early" loops | A trigger that re-enqueues the task with a clean context |

When a new pattern shows up, ask which primitive it is. If you can't name one, it is probably a prompt trick, not infrastructure.

### Prompting vs workbench vs framework

- **Prompting** tells the model what you want *this turn*.
- **A framework** (LangGraph, OpenAI Agents SDK, Google ADK, Microsoft Agent Framework) gives you a runtime.
- **A workbench** gives the agent a place to *work* inside that runtime, across turns and sessions.

You need all three. Most production incidents are workbench gaps that get blamed on the prompt.

## 3. What changed by Oct 2026

- **"Harness engineering" became a named discipline.** Key posts include OpenAI's *Harness engineering: leveraging Codex in an agent-first world* (Feb 2026), Birgitta Böckeler's *Harness engineering for coding agent users* on martinfowler.com (Apr 2026; guides = feedforward, sensors = feedback), and frontier-lab write-ups on long-running harnesses (initializer agent + incremental coder + progress file; planner / generator / evaluator).
- **AGENTS.md is shared infrastructure.** It is stewarded by the Agentic AI Foundation (Linux Foundation) alongside MCP. It is used in 60k+ repos and read by Codex, Cursor, Copilot, Gemini CLI, Jules, VS Code, Devin, Amp, Factory and others.
- **Agent Skills went cross-vendor.** `SKILL.md` folders with progressive disclosure are supported by hosted provider APIs, coding agents, OpenAI's Shell + Skills, Google ADK (skill registry, skill telemetry) and the AI SDK (skills upload). There is now an academic reference architecture (arXiv 2606.20631).
- **Coding agents grew harness hooks.** Lifecycle hooks (session start, pre/post tool use) are standard. Plugin marketplaces now bundle skills, hooks, MCP servers and background **monitors**. **Background agents** run in their own git worktrees and open draft PRs. Dynamic multi-agent workflows and scheduled or event-triggered cloud agents are standard features.
- **Append-only history is a harness rule.** Providers now preserve reasoning across turns and rely on prompt caching, so harnesses that edit or reorder past messages lose both. State goes into files, and the transcript is only appended to (Lesson 34).
- **Harness disclosure is an evaluation norm.** *Stop Comparing LLM Agents Without Disclosing the Harness* (arXiv 2605.23950) makes the point formally: the same model under different harnesses gives very different scores.

## 4. Build it

`code/main.py` runs one deterministic stub model on one tiny task: add password validation to `/signup` and a passing test. The repo is a dictionary. The tests really execute.

1. **Prompt-only run.** The model writes an off-by-one check, "tidies" two unrelated files, never runs tests, and declares success.
2. **Workbench run.** The same model runs with the seven surfaces. The definition of done forces a test, scope blocks the stray writes, feedback exposes the off-by-one, the model fixes it, verification passes, review checks the diff, and a handoff note is written.
3. **`failure_modes.json`.** Every missed surface, its observed symptom and its underlying primitive. It is written to a temp dir and printed.
4. **Leave-one-out ablation.** Remove one surface at a time from the full workbench and record the outcome.

```bash
python3 code/main.py
```

What to look for:

- The side-by-side log: the prompt-only run ends with **FALSE DONE**.
- In the ablation, removing *feedback* still ends **blocked by gate**, and removing *verification* still ships correct code. Surfaces overlap, and that redundancy is defence in depth.
- Removing *state*, *review* or *handoff* still "ships" today. The damage arrives in the *next* session, which is why demos never catch it.

## 5. Use it in production

| Surface | Where it shows up today |
|---|---|
| Instructions | `AGENTS.md` (nested, nearest wins), agent instruction files, Agent Skills |
| State | Progress files in the repo; LangGraph checkpointers; OpenAI Agents SDK sessions / `RunState` |
| Scope | Coding-agent permission rules (allow / ask / deny), sandbox egress allowlists, OpenCode permission globs |
| Feedback | Tool-result capture in the loop; OTel GenAI `execute_tool` spans |
| Verification | CI, pre-commit hooks, post-tool-use hooks running lint/tests |
| Review | A reviewer subagent, CODEOWNERS, PR review bots |
| Handoff | PR description templates, handoff files, background-agent draft PRs |

## 6. Architect's lens

1. **Capability and reliability are different axes.** A model upgrade raises capability. Only the workbench raises reliability per task. If your incident review says "the model hallucinated", rewrite it as "which surface failed to catch it?"
2. **Overlap surfaces on purpose.** The ablation shows that feedback and verification back each other up. Design so that any single surface can fail without a bad change shipping. Report "surfaces that caught it" per incident to see which ones carry the load.
3. **Next-session failures are invisible in demos.** State, review and handoff gaps cost nothing today and a great deal tomorrow. Measure **re-discovery tokens per session**, meaning tokens spent before the first useful edit, as a workbench KPI.
4. **The harness is the security boundary.** Scope and verification are authorization and policy. Run them outside the model's control, in hooks, the runtime or CI, never only as prose the model may ignore. **2026 update:** "is this tool call in scope?" and "did the builder actually finish?" are bounded questions. A System One decision model (Jev or Clef, Lessons 55–56) can answer them in milliseconds as a `noul` probability before each action, with the threshold kept in your code.
5. **Remove harness parts as models absorb them.** Harness tricks can become dead weight as models improve. Re-run the ablation every model upgrade and delete surfaces or rules that no longer change outcomes.

## 7. Exercises

1. Score a repo where you already run an agent from 0 (missing) to 2 (healthy) on each surface. Cite a file or process for every score.
2. Add an eighth surface your product needs, such as a cost budget or data-residency rules. Argue why it does not collapse into scope or verification.
3. Change `StubModel` so it also invents a new dependency. Which surface should catch it? Add the check.
4. Extend the ablation to remove *pairs* of surfaces. Which pair is the most dangerous to lose together?
5. Take three harness patterns from a recent blog post and translate each into the primitive table above.

## 8. Key terms

| Term | Meaning |
|---|---|
| Harness / workbench | Everything around the model that turns generation into reliable work |
| Surface | A named, machine-readable input the agent reads or writes every turn |
| System of record | The file the workbench treats as truth when the chat history is gone |
| Definition of done | An objective, file-backed checklist the agent cannot fake |
| False done | A success claim that the acceptance checks contradict |
| Leave-one-out ablation | Removing one surface at a time to measure what it actually catches |

## 9. Quick check

<details><summary>1. Why did removing <em>feedback</em> not produce a false success claim?</summary>The verification gate ran the tests independently, saw the failure and refused to mark the task done. The work was unfinished, but nothing false shipped. The two surfaces overlap.</details>
<details><summary>2. Which surfaces fail silently in a single-session demo?</summary>State, review and handoff. The run "ships", but the next session starts from zero, nobody independent checked the diff, and the reasons for the change are lost.</details>
<details><summary>3. What primitive is an Agent Skill?</summary>A function registry whose metadata (name and description) is always in context, while the body loads just in time when the skill is selected. That is progressive disclosure over a registry.</details>

## References

- OpenAI, Harness engineering: leveraging Codex in an agent-first world: https://openai.com/index/harness-engineering/
- Böckeler, Harness engineering for coding agent users: https://martinfowler.com/articles/harness-engineering.html
- The State of AI Harness Engineering 2026: https://marmelab.com/blog/2026/09/24/the-state-of-ai-harness-engineering-2026.html
- LangChain, The Anatomy of an Agent Harness: https://blog.langchain.com/the-anatomy-of-an-agent-harness/
- AGENTS.md open format: https://agents.md/
- Stop Comparing LLM Agents Without Disclosing the Harness: https://arxiv.org/abs/2605.23950
- Agent Skills reference architecture: https://arxiv.org/abs/2606.20631
- awesome-harness-engineering: https://github.com/ai-boost/awesome-harness-engineering
