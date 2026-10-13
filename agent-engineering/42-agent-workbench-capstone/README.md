# 42 · Capstone: Ship a Reusable Agent Workbench Pack

> **Short answer:** The capstone compresses Lessons 31–41 into one versioned directory you can drop into any repo: `AGENTS.md` as the router, docs for rules and rubric, JSON schemas for state, board and scope, and scripts for the feedback runner, gate and handoff. It comes with an installer that is idempotent, refuses to clobber, and never owns your state files. A manifest of hashes makes drift visible, and a bump rule makes versions mean something. Then you prove it on one real change, including a deliberate wrong result that your acceptance check must catch.

**Type:** Capstone · **Languages:** Python (stdlib) · **Time:** ~75 min (plus one working session for the real-repo practice)

---

## 1. The problem

A workbench that lives in a doc, a chat history and three half-remembered scripts gets rebuilt every quarter, slightly differently each time. Teams then argue about which version of "the rules" an agent saw. The fix is the same one software has always used: a **versioned package with an installer**.

Packaging has its own failure modes, though:

- An installer that overwrites the team's existing `AGENTS.md`.
- An uninstaller that deletes `task_board.json` and three months of history.
- A pack edited by hand in one repo, which silently drifts from every other copy.
- A "1.2" that changed a schema and broke every state file.

## 2. The concept

```
 agent-workbench-pack/                     target repo
 ├── AGENTS.md            (router) ───────► AGENTS.md  + aliases for other tools
 ├── docs/                (rules, rubric)─► docs/
 ├── schemas/             (contract) ─────► schemas/
 ├── scripts/             (runtime) ──────► scripts/
 ├── VERSION  ┐                             .workbench-version (lock)
 └── MANIFEST.json (sha256 per file)        agent_state.json, task_board.json
                                            (seeded once, owned by the repo forever)
```

### What stays in, what stays out

| In | Why | Out | Why |
|---|---|---|---|
| Schemas | They are the contract | Project tasks | Tasks belong on the repo's board |
| Scripts | They are the runtime | Vendor SDK calls | The pack must work with any coding agent |
| Rules, policy, handoff protocol, rubric | They are the judgment | Onboarding prose | It lives with the team's docs |

### Installer contract

1. **Dry run first.** Print the plan and write nothing.
2. **Refuse to clobber.** A foreign `AGENTS.md` needs `--force`.
3. **Idempotent.** A second install at the same version does nothing.
4. **Seed state once.** Create `agent_state.json` and `task_board.json` only if they are missing. Never overwrite them.
5. **One source, many readers.** Write alias files for tools that look elsewhere, all pointing at `AGENTS.md`.
6. **Lock the version** in `.workbench-version`.

### Version rule

| Changed | Bump | Reason |
|---|---|---|
| `schemas/` | major | Existing state files may no longer validate, so a migration is required |
| `scripts/` | minor | Behaviour changes, so re-run the checks |
| `docs/`, `AGENTS.md`, `README.md` | patch | Wording only |

## 3. What changed by Oct 2026

- **AGENTS.md won.** It is stewarded by the Agentic AI Foundation (Linux Foundation) alongside MCP, and has been adopted by 60k+ repos and most coding agents (Codex, Cursor, Copilot, Gemini CLI, Jules, VS Code, Devin, Amp, Factory and others). Make it the single source and alias everything else to it.
- **Agent Skills are a cross-vendor packaging unit.** `SKILL.md` folders with progressive disclosure are supported across provider APIs, coding-agent CLIs, OpenAI's Shell + Skills, Google ADK's skill registry and the Vercel AI SDK's skill uploads. The pack's procedures (run gate, write handoff) can ship as skills as well as scripts.
- **Plugins and marketplaces** in coding-agent CLIs can bundle skills, hooks and MCP servers. A pack can be distributed that way, but keep the plain-directory form as the source of truth.
- **MCP 2026-07-28 is stateless** (no `initialize` handshake, no sessions). If your pack ships an MCP server for the board or state, target the new spec and pass state through server-minted handles.
- **Hosted harnesses exist now.** Managed agent platforms, LangSmith Managed Deep Agents and AWS AgentCore can run the loop for you. The pack still matters, because the rules, schemas, gate and rubric are yours, not the platform's.
- **2026 update, System One:** the rubric doc in the pack is written as anchored levels, so it doubles as the `criteria` of a Jev or Clef `score` question. The reviewer's first pass (Lesson 39) reads the same file the humans do.

## 4. Build it

`code/main.py` contains:

- `pack_files()`: the whole pack as in-memory text (router, four docs, three schemas, four small scripts, README, VERSION).
- `assemble()` writes the pack plus `MANIFEST.json`. The second run writes 0 files.
- `lint()` recomputes hashes and reports drift and VERSION/MANIFEST disagreement.
- `required_bump()` applies the version rule to two manifests.
- `install(force, dry_run)` and `uninstall()` implement the contract above.
- `acceptance_weak` / `acceptance_strong` are run against a correct implementation and a deliberate **mutant**.

```bash
python3 code/main.py
```

What to look for:

- `assemble: 15 files written; re-run: 0 written`.
- Dry run plans 18 actions and writes nothing. The second install says "nothing to do". A repo with its own `AGENTS.md` is refused.
- Uninstall refuses when `task_board.json` has real history, and keeps state files otherwise.
- A hand edit to a doc shows up as drift and needs a **patch** bump. A schema type change needs a **major** bump.
- The weak acceptance check stays green on the mutant, so it is too weak. The strong one catches it.

## 5. Use it in production

| Channel | How |
|---|---|
| Plain directory | Copy the pack, then run `install` against the repo root; commit `.workbench-version` |
| Template repo | "Use this template", with `VERSION` and the manifest controlling drift |
| Skills / plugins | Publish the procedures as `SKILL.md` folders or a coding-agent plugin; the directory stays canonical |
| CI | Run `lint` on the pack repo and `verify_agent.py` on every agent PR; fail the build on drift |
| Cloud agents | Background agents, routines and sandboxed runs (Cloudflare Sandboxes, OpenAI sandbox agents) install the pack at session start |

### Prove it on one real change (career practice)

Packaging proves the assembler runs. It does not prove an agent can finish a real task. Take one bounded task in a repo you own and keep an evidence file:

1. **Frame and choose autonomy.** Use the task frame (Lesson 43) and evidence plan (Lesson 44). Record the starting revision, goal, non-goals, allowed paths, a wall-time and cost budget, and a stop rule with a named decision owner.
2. **Smallest useful environment.** Load only the relevant code, caller, test and instructions. For each extension (skill, MCP tool, hook, plugin), say why it is needed, and record one you rejected.
3. **Baseline, then implement.** Run the closest check *before* editing and keep the receipt. Log every intervention and why you made it.
4. **Challenge the evidence.** In a disposable copy, introduce one specific wrong behavior. The same acceptance check must fail *for that reason*. A syntax error does not count. If it stays green, strengthen the check (the demo's weak vs strong). Then restore the code and re-run.
5. **Rehearse operation and recovery.** Label every observation `local`, `staging` or `live`. Trigger one failure signal safely and rehearse rollback, including any data changes.
6. **Improve and hand off.** Promote one correction into a test, hook or permission boundary (Lesson 46), then leave a clean handoff (Lesson 40).

A reviewer marks each dimension `demonstrated`, `needs revision` or `unverified`, with an evidence pointer. One task shows what happened on that task, not that the agent is generally reliable. Keep the claim that narrow.

## 6. Architect's lens

1. **State belongs to the repo, rules belong to the pack.** Every uninstall or upgrade bug comes from blurring that line. Code it as a refusal, not a convention.
2. **Hashes beat discipline.** Teams will hand-edit installed docs. A manifest turns "someone changed the rules" from a mystery into a lint error, and makes upstreaming the change a deliberate act.
3. **Semver on schemas is a migration promise.** A major bump ships with a migration script and a state-file validator. A schema change disguised as a minor bump is the most expensive bug a pack can have.
4. **Metrics across repos:** pack version spread (how many repos are behind), drift findings per month, gate pass rate and escape rate by pack version. A new version that raises escapes gets rolled back.
5. **Mutation-test your acceptance checks.** A check that cannot fail on a known-wrong result proves nothing. Make the "deliberate wrong result" step part of every new task template.

## 7. Exercises

1. Add `migrations/1_to_2.py` and make `install` refuse a major upgrade unless the migration ran and state validates against the new schema.
2. Promote one optional doc (for example `security-policy.md`) into the pack. Defend the cut using the in/out table.
3. Ship the gate and handoff procedures as `SKILL.md` folders alongside the scripts. What belongs in the skill text and what stays in code?
4. Make `lint` part of CI and introduce a drift. How does the failure message point the author at the right fix?
5. Complete the career-practice evidence file for one real task and have a peer reproduce your weakest check.

## 8. Key terms

| Term | Meaning |
|---|---|
| Workbench pack | Versioned directory with router, docs, schemas and scripts |
| Manifest | Per-file hashes plus version; the basis for drift detection |
| Lock file | `.workbench-version` in the target repo |
| Alias file | Pointer for tools that read a different filename, so there is one source of truth |
| Mutant | A deliberately wrong implementation used to prove an acceptance check can fail |

## 9. Quick check

<details><summary>1. Why does uninstall refuse when <code>task_board.json</code> has entries?</summary>State is the repo's history, not part of the pack. Deleting it destroys work the pack never owned.</details>
<details><summary>2. A teammate edits <code>docs/agent-rules.md</code> in one repo. What happens?</summary><code>lint</code> reports drift against the manifest. Either upstream the change with a patch bump, or revert it locally.</details>
<details><summary>3. Your acceptance check passes on both the correct code and the mutant. What does that tell you?</summary>The check does not observe the behavior you changed. Strengthen the assertion before trusting any green run.</details>

## References

- AGENTS.md specification: https://agents.md/
- Agentic AI Foundation announcement (MCP and AGENTS.md): https://blog.modelcontextprotocol.io/posts/2025-12-09-mcp-joins-agentic-ai-foundation/
- Semantic Versioning 2.0.0: https://semver.org/
- MCP 2026-07-28 changelog: https://modelcontextprotocol.io/specification/2026-07-28/changelog
- Nx, Teach your AI agent how to work in a monorepo: https://nx.dev/blog/nx-ai-agent-skills
- Agent Skills reference architecture, arXiv:2606.20631: https://arxiv.org/abs/2606.20631
- The State of AI Harness Engineering 2026: https://marmelab.com/blog/2026/09/24/the-state-of-ai-harness-engineering-2026.html
