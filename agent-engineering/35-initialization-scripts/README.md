# 35 · Initialization Scripts for Agents

> **Short answer:** Every session that starts cold pays a **setup tax**. The agent guesses the Python version, hunts for the test command, and discovers a missing API key twenty minutes in. An init script pays that tax once. It runs deterministic **probes** (runtime, dependencies, test command, env, state freshness, board invariants, drift since last-known-good), writes an `init_report.json`, injects a short summary into the agent's context, and **refuses to launch** if anything blocking fails. In 2026 this is how you wire session-start hooks, cloud-agent setup scripts and background agents: the probes are plain plumbing, and the agent is not involved.

**Type:** Build · **Languages:** Python (stdlib) · **Time:** ~45 min

---

## 1. The problem

Open a session and watch the first ten minutes:

- `python --version`
- `ls` five times
- `pytest`, which fails because the tests use `unittest`
- an import of a package that isn't installed
- a question to the user about where the config lives

Thousands of tokens go to rediscovering facts that never change between sessions.

Worse, some failures only show up *late*. A missing API key surfaces at the first real call. A corrupt board with two `in_progress` tasks surfaces when two agents collide. Late failures are expensive and often silent.

## 2. The concept

```
 session start / container boot / scheduled trigger
        │
        ▼
 init_agent  ──► probes (deterministic, offline, < 3 s each)
        │            runtime · deps · test cmd · env (redacted) · state age · board invariant · LKG drift
        ▼
 .agent/init_report.json  ──►  session context ("[init] workbench ready" + any warnings)
        │
   ok? ─┴─ yes ─► launch agent loop
        └─ no ──► exit 1, fail loud, one place to look, a human decides
```

### Probes

| Probe | Severity | Why it matters |
|---|---|---|
| Runtime version | block | Wrong interpreter means silent wrong-version bugs |
| Dependencies importable | block | A missing package now costs less than one found mid-task |
| Test command resolvable | block | No verification path means a broken workbench |
| Required env vars (redacted) | block | A missing key is a setup failure, not a runtime mystery |
| State freshness | warn | Stale state from a crashed session needs confirmation |
| One `in_progress` task | block | Two active tasks means a coordination failure |
| Drift since last-known-good | block above budget | Large unreviewed drift should be ratified by a human |

### Properties that make init useful

- **Deterministic and offline.** No LLM calls and no network without a timeout. A probe that "asks a model" is a workflow, not a probe.
- **Idempotent.** Two runs in a row produce identical reports apart from the timestamp, so you can run it from hooks, CI and container entrypoints without side effects.
- **Fail loud, in one place.** Non-zero exit, a single report file, and a summary a human can read in five seconds.
- **Cached.** A `prereqs.lock` keyed by a fingerprint (config + dependency manifest) with a TTL lets repeated sessions skip expensive probes. Any change to the manifest invalidates it.
- **Secrets never printed.** Report "set, redacted", never the value.

### Init vs rules

Rules (Lesson 33) say what must be true. Init makes sure those rules *can* be checked: the state file exists, the test command resolves, the board is coherent. Rules without init stay "be careful". Init without rules is polished ceremony.

## 3. What changed by Oct 2026

- **Session-start hooks are the standard entry point.** Coding agents run hooks at session start that can execute a script, add its output to the agent's context, or block the session. The init script plugs straight in. The "session context" the demo prints is exactly what such a hook would inject.
- **Cloud and background agents need it most.** Coding agents now run in cloud containers with environment setup scripts, on schedules, on repo events, and as background agents in fresh git worktrees that open draft PRs. Nobody is watching the first minutes of those sessions, so init is the only thing that notices a broken environment.
- **Sandboxes became the default compute plane.** Cloudflare Sandboxes, LangSmith Sandboxes, OpenAI Agents SDK sandbox agents and AWS AgentCore shell sessions all start from an image plus a setup step. Put the probes in that setup step, and fail the sandbox, not the task.
- **Frontier-lab harness write-ups formalized "initializer, then worker".** Long-running harness designs use an initializer pass that sets up the environment, a progress file and a feature list, followed by incremental worker sessions that read them (Lessons 34, 36).
- **MCP went stateless.** In the `2026-07-28` revision there is no `initialize` handshake. Clients can call `server/discover` to probe capabilities. An init probe that checks required MCP servers should use discovery, not a session handshake.

## 4. Build it

`code/main.py` builds a fake repo in a temp dir, uses an injected clock and environment so output is deterministic, and runs init five times:

| Run | Situation | Result |
|---|---|---|
| 1 | Missing `PROVIDER_API_KEY`, two tasks `in_progress`, 30-hour-old state, a slow probe | **exit 1**, session context says BROKEN |
| 2 | Operator fixed env and board | exit 0, key shown as `set, redacted`, lock written |
| 3 | Two hours later | Lock fresh, **probes skipped** |
| 4 | `--no-cache` equivalent | Report identical modulo timestamp (**idempotent: True**) |
| 5 | `requirements.txt` changed, 61 files of drift | Lock invalidated, `lkg_drift` **fails**, agent not launched |

```bash
python3 code/main.py
```

The slow `lkg_drift` probe (simulated at 4.2 s) is downgraded to `warn` with a "move out of init or cache it" note. Init has a time budget too.

## 5. Use it in production

| Where | How init runs |
|---|---|
| Coding agent, local | Session-start hook runs `init_agent`, injects its summary, blocks on failure |
| Coding agent, cloud / background | Environment setup script + session-start hook inside the container or worktree |
| CI | A `setup-agent` job; agent jobs depend on it |
| Container | Entrypoint runs init before exec'ing the agent runtime |
| Durable / scheduled runtimes | First step of the workflow, so a failed night run halts visibly (Lesson 29) |

Keep the script framework-agnostic: Python, Make or a shell wrapper all work, and every runtime can call it.

## 6. Architect's lens

1. **Measure the setup tax.** Track tokens and wall-clock time from session start to first meaningful edit, before and after init. This is the cleanest ROI number for workbench investment.
2. **Fail closed on coordination invariants.** "At most one `in_progress` per builder" and "drift below budget" are cheap to check and expensive to violate. Make them `block`. Leave freshness as `warn` with explicit confirmation.
3. **Cache with fingerprints, not timestamps alone.** A TTL alone will reuse a stale result after a dependency bump. Hash everything that changes the answer (config, manifest, runtime version) into the lock key.
4. **Keep LLMs out of init.** **2026 update:** it's tempting to put a System One decision model (Jev or Clef, Lessons 55–56) in front of the agent to "classify whether the environment looks healthy". Don't. Probes have exact answers. A decision model is useful *after* init, for example to triage a failed `init_report.json` into "env / dependency / data / human-needed" for an on-call queue. It does not belong inside the gate.
5. **Treat init output as the start of the handoff.** The report's last-known-good anchor and probe results are the baseline the end-of-session handoff diffs against (Lesson 40).

## 7. Exercises

1. Replace the simulated `changed` list with a real `git diff --name-only <lkg> HEAD` behind a two-second timeout, falling back to `warn` when git is missing.
2. Add a `--fix` mode that creates missing *dev* directories and files but never installs runtime dependencies without an approval.
3. Add a probe that checks required MCP servers via capability discovery, with a timeout, and degrades to `warn` for optional servers.
4. Emit the session context as JSON with `ok`, `warnings` and `next_action` so a hook can parse it.
5. Measure: run a small agent task 10 times with and without init, and compare tokens before the first edit.

## 8. Key terms

| Term | Meaning |
|---|---|
| Probe | Deterministic check returning name, status, detail, severity and duration |
| Init report | JSON record of every probe, written before the agent starts |
| Setup tax | Tokens and time spent rediscovering the environment each session |
| Prereqs lock | Fingerprinted cache that lets init skip probes until something changes |
| Last-known-good (LKG) | Commit anchor for drift checks and the session's handoff diff |
| Session-start hook | Coding-agent hook that runs a script and injects or blocks before work starts |
| Fail loud | Non-zero exit, a single report, a human decides; never a silent fallback |

## 9. Quick check

<details><summary>1. Why did run 5 ignore the fresh lock from run 2?</summary>The fingerprint includes <code>requirements.txt</code>. Adding a dependency changed the hash, so the lock no longer matched and every probe ran again, which caught the drift.</details>
<details><summary>2. Why is state freshness <code>warn</code> while the board invariant is <code>block</code>?</summary>Old state may still be correct, so a human confirms it and the session continues. Two tasks <code>in_progress</code> is a guaranteed coordination bug, and starting would make it worse.</details>
<details><summary>3. Should an init probe call an LLM to judge environment health?</summary>No. Init must be deterministic, offline-safe and fast. Exact checks have exact answers. Use models, including decision models, only to triage a failed report afterwards.</details>

## References

- Böckeler, Harness engineering for coding agent users: https://martinfowler.com/articles/harness-engineering.html
- OpenAI, Harness engineering: leveraging Codex in an agent-first world: https://openai.com/index/harness-engineering/
- MCP 2026-07-28 changelog (`server/discover`): https://modelcontextprotocol.io/specification/2026-07-28/changelog
- GitHub Actions, creating a composite action: https://docs.github.com/en/actions/sharing-automations/creating-actions/creating-a-composite-action
- Cloudflare Agents Week recap (Sandboxes): https://blog.cloudflare.com/agents-week-in-review/
- AWS Bedrock AgentCore release notes: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/release-notes.html
