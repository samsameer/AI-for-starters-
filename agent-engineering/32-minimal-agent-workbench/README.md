# 32 · The Minimal Agent Workbench

> **Short answer:** The smallest useful workbench is three files: a short **`AGENTS.md` router**, a **state file** (`agent_state.json`), and a **task board** (`task_board.json`). The router says where to look. State says where the last session stopped. The board says what is next. Every later surface (rules, scope, verification, handoff) builds on these three. If a repo cannot carry them, no model will save it. In Oct 2026 `AGENTS.md` is a cross-vendor open format, so write it once and point every coding agent at it.

**Type:** Build · **Languages:** Python (stdlib) · **Time:** ~45 min

---

## 1. The problem

Most teams start their workbench by writing a 3,000-line `AGENTS.md`. The agent loads it, follows the first screen, skims the rest, and fails on the same surfaces as before. Meanwhile there is still no record of where the last session stopped, so each new session re-reads the repo from scratch.

What you need is close to the opposite:

- a **tiny** root file that routes the agent to deeper files only when it needs them;
- **durable state** that the agent reads before acting and writes after;
- a **queue of work** that says what is in flight, blocked or next, with acceptance criteria attached.

## 2. The concept

```
                 ┌──────────────┐
  session N ───► │  AGENTS.md   │  router: where to look, the verify command, hard rules
                 └──────┬───────┘
          ┌─────────────┼─────────────────┐
          ▼             ▼                 ▼
 agent_state.json  task_board.json  docs/agent-rules.md (on demand)
  where I am        what is next     how to behave
          │             │
          └──── read at start, written at end ──► session N+1 starts here
```

### AGENTS.md is a router, not a manual

A good router is roughly 10–80 lines and contains:

- pointers, by path, to the state file, the board and the deeper rules;
- **the verification command**, which comes before anything about style;
- the definition of done;
- three to five hard rules.

Anything longer belongs in topic docs that the agent loads only when the task touches that topic (Lesson 33).

### agent_state.json is the system of record

| Key | Meaning |
|---|---|
| `active_task_id` | The one task in flight (empty string = pick one) |
| `touched_files` | What this task has changed so far |
| `assumptions` | Decisions made without confirmation |
| `blockers` | What stops progress |
| `next_action` | The very next step, written for a reader with no context |

State lives in a file because chat history is unreliable. Sessions end, context gets compacted, and background agents start in fresh worktrees.

### task_board.json is the queue

Each task has an `id`, a `goal`, an `owner` (`builder`, `reviewer` or `human`), its `acceptance` criteria and a `status` (`todo` → `in_progress` → `done` / `blocked`). The `owner` field is a role: the builder agent skips tasks owned by a human instead of improvising. If the board grows past one screen, you have a planning problem, not a board problem.

### Nested routers, nearest wins

In a monorepo you put an `AGENTS.md` in each subcomponent. Coding agents walk from the working file up to the root and combine every file they find. Subdirectory files extend the root file, and the closest file wins on conflict. A single root file can cover agents that look for vendor-specific filenames: symlink those names to `AGENTS.md`, or generate them from it.

## 3. What changed by Oct 2026

- **AGENTS.md is an open, foundation-stewarded format.** It sits under the Agentic AI Foundation (Linux Foundation) alongside MCP. It is used in 60k+ repos and read natively by Codex, Cursor, Copilot, Gemini CLI, Jules, VS Code, Devin, Amp, Factory and others. One file now covers almost every tool.
- **Router plus Skills replaced the giant manual.** The deeper layer is increasingly packaged as **Agent Skills**: `SKILL.md` folders whose name and description are always visible to the agent, while the body loads only when relevant. That is the router idea, applied to procedures.
- **Background and cloud agents made file state mandatory.** Coding agents now run tasks in isolated worktrees, on schedules and from repo events. A run like that starts without your chat, so the state file and board are its *only* context.
- **Hooks enforce the router.** Session-start hooks can inject `agent_state.json` and the board into context automatically, and can refuse to start when they are missing (Lesson 35).
- **The evidence on instruction files grew.** Practitioner measurements report that a good `AGENTS.md` can be worth more than a model-tier upgrade, while a bad one (conflicting, unverifiable, verbose) can do worse than having no file. Conflicting instructions measurably lower resolve rates on ambiguity benchmarks.

## 4. Build it

`code/main.py` works inside a temporary directory:

1. **Seeds** the workbench: a 13-line root `AGENTS.md`, a nested `services/api/AGENTS.md`, `docs/agent-rules.md`, an empty state file, and a three-task board. One task is owned by a human.
2. **Lints the router**: line budget 10–80, a verification command must be named, and every backticked file reference must resolve.
3. **Resolves the instruction chain** for a file deep in `services/api/`, showing nearest-wins nesting.
4. **Runs cold sessions**: each turn reloads state and board *from disk only*, does one step, and saves. The script prints a field-level diff of what each session changed.
5. **Stops at the human task.** The builder goes idle instead of grabbing work it does not own.
6. **Breaks the router on purpose**: it pastes a "manual" into the router and shows the linter catching the bloat and the dead link.

```bash
python3 code/main.py
```

Look for: session 5 picks up T-002 without being told, purely from the files. The final board leaves T-003 for a human. The lint lists two problems after the bloat.

## 5. Use it in production

| Concern | Oct 2026 practice |
|---|---|
| Root router | `AGENTS.md` at the repo root, short, commands first |
| Per-package rules | Nested `AGENTS.md` files; avoid tool-specific override files when several tools share the repo |
| Tool-specific filenames | Symlink or generate from `AGENTS.md` so there is one source of truth |
| Deeper procedures | Agent Skills folders (`SKILL.md` + scripts), loaded on demand |
| State and board | JSON (or JSON Lines) in the repo, reviewed like code |
| Auto-loading | Session-start hooks or init scripts that inject state into context |

Example root router body:

```text
Read first: agent_state.json, then task_board.json.
Rules on demand: docs/agent-rules.md
Verify: python3 -m pytest -x
Done = active task is "done" on the board AND verify exited 0.
Never edit scripts/. Ask before adding a dependency. One task at a time.
```

## 6. Architect's lens

1. **The router is a context budget.** Every line is paid for in every session, by every agent. Treat router growth like bundle-size growth: lint it in CI and ask for a justification when it grows.
2. **The board is your coordination protocol.** Once there are several agents (background agents, reviewers, humans), `owner` and `status` act as a lightweight lock. Enforce "one `in_progress` per builder" mechanically, or you will see two agents on one task.
3. **State must be readable by someone with no context.** Write `next_action` for a cold reader. The test: could a new hire, or a fresh background agent, act on it without asking?
4. **Which file hurts most to lose?** State. You can recreate the router and the board from the repo and the issue tracker, but a lost `next_action` and `assumptions` means re-discovering the work. Back it with version control (Lesson 34). **2026 update:** "which todo task should I pull next?" and "is this task one I'm allowed to own?" are typed choices. A System One decision model (Jev or Clef, Lessons 55–56) can rank candidate tasks as a `choice`. The board stays the source of truth, and code enforces the owner rule.
5. **Measure the workbench.** Track tokens spent before the first edit, the share of sessions that resume correctly from state, and router line count over time.

## 7. Exercises

1. Add a `last_run` timestamp to the state file. Refuse to run if it is older than 24 hours unless an operator confirms.
2. Add `priority` to tasks and change the puller to pick the highest-priority `todo` task that the builder owns.
3. Convert `task_board.json` to JSON Lines so each task change is a one-line diff.
4. Extend `lint_router` to flag style rules that have no matching lint command (unverifiable rules).
5. Add a second builder. Make the puller claim a task atomically so two cold sessions never pull the same one.

## 8. Key terms

| Term | Meaning |
|---|---|
| Router | Short root instruction file that points to deeper files |
| State file | Machine-readable record of where the agent is, written every turn |
| Task board | Queue of work with status, owner and acceptance |
| Nearest-wins | Nested instruction files; the one closest to the working file has priority |
| Cold session | A session that starts with no chat history, only the files |
| Agent Skill | A `SKILL.md` folder whose body loads only when it is relevant |

## 9. Quick check

<details><summary>1. Why should the verification command appear before style rules in AGENTS.md?</summary>Agents act on what they read first and remember. The verification command is how they prove done. If it is buried under prose, agents skip it and declare success early.</details>
<details><summary>2. Session 8 found T-003 still <code>todo</code>. Why didn't the builder take it?</summary>Its <code>owner</code> is <code>human</code>. Owners are roles, and the builder only pulls tasks it owns, so it goes idle and says so in <code>next_action</code>.</details>
<details><summary>3. What does the linter check besides line count?</summary>That a verification command is named, and that every file the router mentions actually exists. A dead pointer is worse than no pointer.</details>

## References

- AGENTS.md open format: https://agents.md/
- AAIF formation (MCP, AGENTS.md, goose): https://blog.modelcontextprotocol.io/posts/2025-12-09-mcp-joins-agentic-ai-foundation/
- Augment Code, How to write good AGENTS.md files: https://www.augmentcode.com/blog/how-to-write-good-agents-dot-md-files
- Datadog, Steering AI agents in monorepos with AGENTS.md: https://dev.to/datadog-frontend-dev/steering-ai-agents-in-monorepos-with-agentsmd-13g0
- Nx, Teach your AI agent how to work in a monorepo: https://nx.dev/blog/nx-ai-agent-skills
- Agent Skills reference architecture: https://arxiv.org/abs/2606.20631
