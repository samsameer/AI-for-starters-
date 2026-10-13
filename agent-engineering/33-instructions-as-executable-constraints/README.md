# 33 · Instructions as Executable Constraints

> **Short answer:** An instruction written as prose is a wish. An instruction written as a constraint is a test. Give every rule a **category**, a **check** function, a **severity** (`block` / `warn` / `info`) and an **expiry date**. Enforce it twice: at runtime, in a hook *before* the action, and after the fact, in a checker that scores the trace. Keep the root router tiny and put depth in topic docs and Agent Skills that load only when needed. A rule with no check is not a rule. Delete it or upgrade it.

**Type:** Build · **Languages:** Python (stdlib) · **Time:** ~50 min

---

## 1. The problem

A typical instruction file reads like onboarding docs: "be careful", "test thoroughly", "ask if unsure". Three days later the agent ships a change with no tests, writes into `scripts/`, and never asks for help, because nothing defined where the line was.

Instruction files also grow without bound. Every incident adds a rule and no incident removes one. A year later the file is 2,000 lines long. The agent reads the first screen and acts on a fraction of it. Nobody can tell which rules still matter.

## 2. The concept

```
 AGENTS.md (router) ──► docs/agent-rules.md ──► agent-rules.lock.json ──► checker ──► rule report
                              │ authored, reviewed      │ cache, hash-pinned        │
                              │                         ▼                           ▼
                              │                   pre-tool-use hook          CI / reviewer (L38, L39)
                              ▼                   (refuse BEFORE acting)
                         docs/<topic>.md, Agent Skills (loaded only when relevant)
```

### Five categories cover most rules

| Category | Question the rule answers | Example check |
|---|---|---|
| Startup | What must be true before work begins? | First tool call is `read:agent_state.json` |
| Forbidden | What must never happen? | No write matches `scripts/*` |
| Definition of done | What proves completion? | Acceptance command exited 0 this session |
| Uncertainty | What happens when unsure? | Confidence < 0.7 ⇒ a question note exists |
| Approval | What needs a human? | Every new dependency has a recorded approval |

If a rule fits none of these, it usually wants to be two rules.

### Anatomy of an executable rule

```markdown
## forbidden/no-release-script
- category: forbidden
- check: no_forbidden_writes
- severity: block
- expires: 2027-01-10
- incident: INC-212
Never write scripts/** or config/prod/** outside an approved release task.
```

The heading is a stable slug that shows up in diffs. `check` names a deterministic function. `severity` decides whether a violation halts the run. `expires` forces a review. `incident` records why the rule exists.

### Two enforcement points

| Point | Mechanism | Catches |
|---|---|---|
| **Before** the action | Pre-tool-use hook, permission rule, guardrail, interrupt | Forbidden writes, unapproved commands |
| **After** the turn | Checker scoring the turn trace, in CI or the verification gate | Missed startup steps, false "done", unasked questions |

Prose instructions are only feedforward. Hooks and checkers make them part of a control loop.

### Progressive disclosure: a map, not an encyclopedia

| Tier | Lives in | Loaded | Budget |
|---|---|---|---|
| Router | `AGENTS.md` | Every session | ~10–80 lines |
| Rules | `docs/agent-rules.md` | Every session start | One screen per category |
| Topic docs / Skills | `docs/<topic>.md`, `skills/*/SKILL.md` | Only when the task touches the topic | As deep as needed |

Two tests keep the tiers honest. **Reachability:** every rule is at most two hops from the router, and the router links by path. **Freshness:** the router is short enough that reviewers reread it on every PR. A dead link from the router counts as a startup violation.

## 3. What changed by Oct 2026

- **Hooks are the standard enforcement layer.** Coding agents expose lifecycle hooks: session start, pre and post tool use, stop. A pre-tool-use hook can **deny** an action with a reason the agent sees. Plugin marketplaces bundle hooks, skills and MCP servers, so a team ships its rule set as an installable plugin instead of a wiki page.
- **Permission policies became first-class.** Coding agents and hosted agent platforms offer allow / ask / deny rules per tool and path. Some add an "auto" mode in which a server-side classifier decides when to ask. Your `approval` category maps directly onto these.
- **Agent Skills took over the deep tier.** Procedures that used to bloat instruction files now live in `SKILL.md` folders with progressive disclosure, supported across vendors (provider Skills APIs, coding agents, OpenAI Shell + Skills, Google ADK skill registry, AI SDK).
- **Framework guardrails converged on the same shape.** OpenAI Agents SDK input/output/tool guardrails (stricter handling since v0.22), LangGraph interrupts and per-node timeouts, Google ADK 2.x tool confirmation in workflow nodes (`RequestInput`), and Microsoft Agent Framework 1.x middleware all run a rule before or around an action.
- **Operator messages vs user content.** Providers now allow system-level messages mid-conversation as a trusted operator channel. The Vercel AI SDK v7 rejects system messages smuggled into user-supplied `messages` by default. Rules belong in the trusted channel, never in retrieved content.

## 4. Build it

`code/main.py` runs in a temp directory and shows the whole life cycle:

1. **Parse** `docs/agent-rules.md` into `Rule` objects (slug, category, check, severity, expiry, incident). The "be careful" entry is **rejected** as aspirational because it has no check and no category.
2. **Lock**: hash the markdown into `agent-rules.lock.json`. After an edit the lock is stale, which is the cue to regenerate it in pre-commit.
3. **Pre-tool-use hook**: `write scripts/release.sh` is **denied before it happens**, while reading the same file is allowed.
4. **Score two traces.** The bad turn fails four `block` rules and one `warn`, so the verdict is **REFUSE**. The good turn passes everything, including an approved dependency.
5. **Reachability**: the router points at a missing `docs/deploy.md`.
6. **Expiry sweep**: the stale style rule comes up for "justify, weaken or delete".

```bash
python3 code/main.py
```

## 5. Use it in production

| Rule category | Runtime enforcement (Oct 2026) | After-the-fact check |
|---|---|---|
| Startup | Session-start hook injects and verifies state (L35) | Trace shows state read first |
| Forbidden | Pre-tool-use hook deny; permission deny globs; sandbox mounts | Diff/scope check in CI (L36) |
| Definition of done | Stop hook refuses "done" without a passing gate | Verification gate (L38) |
| Uncertainty | Ask-user tool; interrupt; elicitation via MCP multi-round-trip | Reviewer looks for unasked questions (L39) |
| Approval | Permission "ask" rules; Agents SDK tool approval; ADK `RequestInput` | Audit log of approvals and overrides |

Keep the checks deterministic and cheap enough to run every turn. If a check needs judgement, put it in the reviewer tier, not the rule tier.

## 6. Architect's lens

1. **Severity is a calibration decision.** Tag it when the rule is written, not during an incident. Too many `block` rules and the team disables the checker. Too many `warn` rules and nobody reads them. Track *block overrides per week*. A rising number means a rule is wrong or the work has changed.
2. **Expiry stops rule rot.** A rule that has not fired in a quarter is either doing its job silently or dead weight. The expiry review makes someone decide. Teams that skip this see rule sets grow without limit.
3. **Hooks over hope.** Anything with a `block` severity should have a pre-action enforcement point the model cannot talk its way past. Prose plus a post-hoc checker only *detects*. A hook *prevents*.
4. **Deterministic rules, probabilistic signals.** **2026 update:** some rules need judgement, such as "is the agent unsure?" or "does this command touch production?". A System One decision model (Jev or Clef, Lessons 55–56) can answer these as a calibrated `noul` in milliseconds. Treat that answer as an *input* to a deterministic rule with a threshold in code. Never let it replace a `block` check that a glob or exit code can decide.
5. **Rules are code.** Review them in PRs, give them owners, and link each one to the incident that created it. The lock file keeps parsing out of the hot path and makes the active rule set auditable.

## 7. Exercises

1. Add a `max_files_per_turn` rule (warn at 5, block at 10) and its check.
2. Make the checker emit a `rule_report.json` with per-severity counts, and fail CI only on `block`.
3. Implement override logging: a human can override a `block` rule, but only by appending a signed line to `overrides.jsonl`, and the checker reports override counts.
4. Take a real instruction file you own and classify every line: operational (has a check), routing (a pointer) or aspirational. What share was aspirational?
5. Move the release procedure into a `skills/release/SKILL.md` folder, gated behind the approval rule, and remove it from the router.

## 8. Key terms

| Term | Meaning |
|---|---|
| Operational rule | A rule with a deterministic check the workbench can run |
| Aspirational rule | A rule with no check; delete it or upgrade it |
| Severity | `block` halts, `warn` reports, `info` records |
| Rule expiry | Date after which a rule must be re-justified |
| Pre-tool-use hook | Code that runs before an agent action and can deny it |
| Lock file | Hash-pinned cache of the parsed rules, read in the hot path |
| Progressive disclosure | Load deeper docs or skills only when the task needs them |

## 9. Quick check

<details><summary>1. Why was "Always be careful and test thoroughly" rejected?</summary>It has no category and no check, so nothing can verify it. Split it into operational rules, for example "acceptance command exited 0" under definition of done, or delete it.</details>
<details><summary>2. The checker already flags forbidden writes. Why also add a pre-tool-use hook?</summary>The checker runs after the fact, so the release script would already be modified. The hook denies the write before it happens. Detection and prevention are different jobs.</details>
<details><summary>3. When is a decision model appropriate inside the rule system?</summary>For judgement signals such as uncertainty or "touches production?". Feed its calibrated probability into a deterministic rule with a threshold in code. Never use it for a check that a glob, exit code or hash can settle.</details>

## References

- OpenAI Agents SDK guardrails: https://openai.github.io/openai-agents-python/guardrails/
- LangGraph human-in-the-loop: https://docs.langchain.com/oss/python/langgraph/overview
- Google ADK changelog (tool confirmation, skills): https://raw.githubusercontent.com/google/adk-python/main/CHANGELOG.md
- Böckeler, Harness engineering for coding agent users: https://martinfowler.com/articles/harness-engineering.html
- Cloudflare, Orchestrating AI code review at scale: https://blog.cloudflare.com/ai-code-review/
- Type-Checked Compliance: Deterministic Guardrails: https://arxiv.org/abs/2604.01483
- AGENTS.md open format: https://agents.md/
