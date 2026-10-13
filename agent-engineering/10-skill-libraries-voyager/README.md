# 10 · Skill Libraries and Lifelong Learning (Voyager to Agent Skills)

> **Short answer:** A skill library stores reusable capabilities as named, versioned units of code plus instructions. The agent can retrieve them, compose them and improve them from feedback. Voyager (2023) proved the idea in Minecraft. By October 2026 the same idea ships across vendors as **Agent Skills**: `SKILL.md` folders loaded with progressive disclosure. Reach for a skill library when your agents keep re-deriving the same procedure, or when a fix learned in one session should help the next one.

**Type:** Build · **Languages:** Python (stdlib) · **Time:** ~75 min

## 1. The problem

An agent that rebuilds every capability from scratch in every session fails in three ways:

1. **It wastes tokens.** Each task re-derives the same reasoning ("how do we cut a release here?").
2. **It forgets corrections.** A fix found in session A never reaches session B.
3. **It can't compose.** Long tasks need a hierarchy of capabilities, and a single prompt can't hold one.

Voyager's answer was to treat each capability as a program. Programs get names, get stored, get found by description, call each other, and get rewritten when the environment says they failed.

## 2. The concept

Voyager (Wang et al., arXiv:2305.16291, TMLR 2024) has three parts:

| Part | Job | Production analogue (2026) |
|---|---|---|
| Automatic curriculum | Proposes the next task just above current ability | A "what's missing?" review of your skill catalog |
| Skill library | Stores working code, keyed by description | `SKILL.md` folders, a skills registry |
| Iterative prompting | Feeds errors and self-checks back into a rewrite | Self-Refine / CRITIC loops (Lesson 05) with real execution |

**The action space is code.** Voyager writes functions, not primitive key presses. `craftIronPickaxe()` calls `mineIron()` and `placeCraftingTable()`. That is why skills compose: a skill is a program, and programs call programs.

The loop:

```
 task ──► retrieve top-k skills ──► compose / write new skill ──► execute
   ▲                                                                │
   │            success: store as vN (dedup, pin deps)              │
   └──────── failure: error + env state + self-check ◄──────────────┘
```

**Progressive disclosure** is the 2026 addition that makes libraries scale. The agent always sees a cheap catalog (name plus one-line description). It loads a skill's full body, scripts and reference files only when it picks that skill. A catalog of hundreds of skills costs a few thousand tokens. Loading every body would cost far more.

```
 always in context:   name + description   (tens of tokens per skill)
 on selection:        SKILL.md body        (hundreds to thousands)
 on demand:           scripts/, references/ (only the file needed)
```

Where libraries go wrong:

- **Rot.** The same skill gets added ten times under different names. Dedup on write.
- **Silent upgrades.** A parent built on `mine-ore@1` breaks when `mine-ore@2` changes behavior. Pin dependency versions.
- **Retrieval decay.** Similarity search over descriptions degrades past a few hundred skills. Add tags, namespaces and hard filters.
- **Cycles.** Skill A calls B, which calls A. Detect it at compose time, not at 3 a.m.

## 3. What changed by Oct 2026

- **Agent Skills became a cross-vendor pattern.** The `SKILL.md`-folder format with progressive disclosure is used by provider Skills APIs, coding agents, OpenAI's Shell + Skills guidance for long-running agents, Google ADK (GCP skill registry and skill telemetry), and the Vercel AI SDK v7 (provider skills upload).
- **Coding agents merged custom slash commands into Skills.** Built-in commands can be invoked through the Skill tool, and plugins bundle skills with marketplaces.
- **Agent SDKs** take skills directly as a configuration option, with name validation (Lesson 17).
- **AGENTS.md** (stewarded by the Agentic AI Foundation) is the sibling convention for repo-level instructions. Skills hold procedures; AGENTS.md holds house rules.
- An academic reference architecture for agent skills now exists (arXiv 2606.20631), so "skills" is a named research topic, not just a product feature.
- Skill registries brought supply-chain risk with them. Treat third-party skills like third-party packages (OWASP Agentic Top 10, ASI04 Agentic Supply Chain).

## 4. Build it

`code/main.py` is a stdlib skill library with the full Voyager loop:

- `Skill`: name, description, body, callable, version, tags, dependencies, history.
- `SkillLibrary.register()`: validates names (lowercase, hyphenated, like `SKILL.md` names), dedups by description and bumps versions. It also **pins** each dependency to the version that exists at registration time.
- `catalog()` and `search()`: the progressive-disclosure split. The catalog is always cheap, and bodies are counted only when selected.
- `plan()`: topological order with **cycle detection** and pinned versions.
- `execute()`: runs the plan and returns the first error as a feedback signal.

```bash
python3 code/main.py
```

What to look for in the output:

1. `mine-iron` collapses into `mine-ore` (dedup).
2. `craft-iron-pickaxe@1` fails with `need ore>=3 stick>=2`, which is the environment's feedback.
3. v2 adds `gather-sticks` and succeeds.
4. `mine-ore` is refined to v2, but the pickaxe plan still runs `mine-ore@1`, because it is pinned.
5. The `skill-a -> skill-b -> skill-a` cycle is rejected.

## 5. Use it in production

- **Agent SDKs and coding agents:** a provider Skills API for uploaded skills, a skills option in the agent SDK, and project or plugin skills in the coding agent.
- **OpenAI:** skills mounted alongside the Shell tool in the Responses API and in Agents SDK sandbox agents (Lesson 16).
- **Google ADK 2.x:** skills with the GCP skill registry and skill telemetry.
- **Vercel AI SDK v7:** provider skills upload.
- **Your own registry:** a Git repo of `SKILL.md` folders with CODEOWNERS, CI evals per skill and semantic versioning. That is often all you need.

A minimal skill folder looks like this:

```
release-notes/
  SKILL.md          name, description, then the procedure
  scripts/collect.py
  references/style.md
```

## 6. Architect's lens

1. **The description is the router.** Retrieval quality depends on one-line descriptions, so review them like API names. A vague description makes a skill invisible, and an over-broad one makes it fire everywhere.
2. **Skills are code, so ship them like code.** Version them, pin dependencies, run per-skill evals in CI and keep an owner per skill. Unowned skills rot fastest.
3. **Measure hit rate, not library size.** Track how often a selected skill is used to completion without being rewritten. A big library with a 20% hit rate costs context and buys little.
4. **Third-party skills are a supply chain.** A skill can carry scripts, so scan it, sandbox it and pin it the way you would a dependency.
5. **2026 update, System One gate.** Skill selection is a typed decision: "which of these N skills applies?" is a `choice`, and "is this skill relevant?" is a `noul` per candidate. A decision model such as Jev or Clef (Lessons 55–56) can rerank catalog hits in tens of milliseconds, and the LLM loads only the winner's body.

## 7. Exercises

1. Replace token-overlap search with a stdlib BM25. Measure recall@3 on a 40-skill toy catalog.
2. Add semantic-version ranges to pins (`mine-ore@^1`) and decide what a breaking change means for a skill.
3. Write a curriculum function: given the catalog and a domain description, list three missing skills.
4. Export the library as `SKILL.md` folders (front matter plus body) and reload it.
5. Add a relevance gate: score each search hit with a yes/no question and drop hits below 0.6.

## 8. Key terms

| Term | Meaning |
|---|---|
| Skill | A named, versioned unit of procedure (code plus instructions) the agent can load |
| Skill library | A persistent, searchable, composable store of skills |
| Progressive disclosure | Load a cheap catalog always, and full bodies only when selected |
| Curriculum | A proposer that picks the next capability to learn |
| Version pinning | A parent records the exact child versions it was built against |
| Dedup on write | Collapsing near-duplicate skills into one canonical entry |

## 9. Quick check

<details><summary>1. Why does Voyager emit code rather than primitive actions?</summary>Code is composable and reusable. A function can call other functions, so capabilities stack into hierarchies and can be stored and re-run exactly.</details>
<details><summary>2. What does progressive disclosure save?</summary>Context. Only names and descriptions sit in the window. Full bodies and scripts load only for the skill actually chosen.</details>
<details><summary>3. A child skill was refined and a parent started failing. What was missing?</summary>Dependency pinning. The parent should keep using the child version it was validated against until it is deliberately upgraded and re-tested.</details>

## References

- Wang et al., Voyager: https://arxiv.org/abs/2305.16291
- Madaan et al., Self-Refine: https://arxiv.org/abs/2303.17651
- Agent skills reference architecture: https://arxiv.org/abs/2606.20631
- AGENTS.md: https://agents.md
