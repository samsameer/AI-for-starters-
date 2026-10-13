# 28 · Orchestration Patterns

> **Short answer:** Four topologies keep recurring in multi-agent systems. A **supervisor** routes work to specialists. A **swarm** lets peers hand off to each other. A **hierarchy** nests supervisors. A **debate** has several proposers vote or critique. Choose the problem before the topology. Start with one agent plus workflow patterns, and add topology only when you can say which metric it improves. In Oct 2026, put a calibrated System One router in front of the supervisor, and use A2A v1.0 when the specialist belongs to another team or company.

**Type:** Learn + Build · **Languages:** Python (stdlib) · **Time:** ~60 min

---

## 1. The problem

Teams often decide "we need multi-agent" before they know what multi-agent would fix. Then they pay for it. Each extra hop is another model call, another place for context to get lost, and another span to debug. Specialists hand tasks back and forth (A → B → A). Three-layer hierarchies get built for organizations that really have two teams.

The cure is vocabulary plus measurement. Once you can name the four patterns and count what each one costs, picking between them becomes an engineering decision instead of a matter of taste.

## 2. The concept

```
 SUPERVISOR                SWARM                   HIERARCHICAL                 DEBATE
   router                 A ⇄ B                        top                  P1   P2   P3
  /  |  \                  ⇅ ⇅                       /     \                  \   |   /
 S1  S2  S3               C ⇄ D                   sup-1   sup-2               judge/vote
 (no S↔S talk)       (no central control)        / | \    / | \              (accuracy for $)
```

| Pattern | Control | Strength | Failure mode | Reach for it when |
|---|---|---|---|---|
| Supervisor-worker | Central router | Easiest to debug, one place to set policy | The router becomes a bottleneck and a single point of failure | You have 2–6 specialists |
| Swarm / handoffs | Peers | Fewer hops, lower latency | Bouncing (A→B→A), nobody owns the outcome | Latency matters more than clarity |
| Hierarchical | Nested routers | Scales past one router's context budget | Fake depth: layers that copy the org chart | The router's prompt can't hold every specialist |
| Debate | Parallel + judge | Higher accuracy on hard calls | Costs N× or more | Being wrong costs more than calls do |

**Escalation order** (the "build the right system" rule): one agent + workflow patterns (Lesson 12) → supervisor → swarm → hierarchy → debate. Climb one rung only when an eval says the current rung is failing.

**Supervision via tool calls.** LangChain recommends implementing the supervisor as an agent whose tools *are* the specialists, instead of using a prebuilt supervisor wrapper. That way you decide exactly what context each specialist sees.

**Flows vs crews.** CrewAI's split also applies elsewhere. A deterministic *Flow* (event-driven, code-owned) is the production default. An autonomous *Crew* is for exploratory work.

## 3. What changed by Oct 2026

- **A2A is stable.** v1.0.0 shipped on 2026-03-12 and v1.0.1 on 2026-05-26. The spec now separates the application protocol from transport bindings (JSON-RPC, gRPC, HTTP). It adds `tasks/list`, modernizes OAuth (implicit and password flows removed, device code and PKCE added), adds multi-tenancy, and prefers the `application/a2a+json` media type. Signed Agent Cards appear in v1.0 coverage. A2A is how a supervisor reaches a specialist **owned by another org**. Inside one codebase you still use plain function or tool calls.
- **Dynamic multi-agent workflows are productized.** Coding agents have `/workflows` commands, and hosted agent platforms have multiagent rosters with dynamic workflows. Google ADK 2.0 (GA in Python on 2026-05-19) has a unified graph-based workflow engine that mixes deterministic and model-led nodes.
- **Microsoft Agent Framework 1.0** reached GA around 2026-04-03 as the successor to Semantic Kernel and AutoGen. AutoGen is in maintenance, and AG2 is a separate community fork. LangGraph is at 1.2.x, and CrewAI is past 1.x.
- **System One routers.** A supervisor's main job is a `choice` decision. Decision models such as TypeSafe Jev and Cloudflare Clef (Lessons 55–56) return calibrated probabilities over the specialists in tens to hundreds of ms. That gives the router an explicit **abstain** path, which an LLM-as-router returning JSON does not have.
- **Security has names now.** The OWASP Top 10 for Agentic Applications lists ASI07 *Insecure Inter-Agent Communication* and ASI08 *Cascading Failures*. Both are orchestration problems.

## 4. Build it

`code/main.py` sends the same four support tickets through five orchestrators:

- `supervisor_llm`: an LLM-style router. It always picks a label, even on the ambiguous "hello, can someone call me back?".
- `supervisor_system_one`: a toy System One `choice` with probabilities. Below 0.6 confidence it routes to `human` instead of guessing.
- `swarm`: peers hand off directly. A visited-list guard detects the `sales → refund → sales` bounce and escalates.
- `hierarchical`: top router → division → specialist (two extra hops).
- `debate`: three voters plus a judge.
- `a2a_send`: an A2A-*shaped* request to a remote agent. It refuses unsigned Agent Cards. The method name in the demo is illustrative; take exact wire names from the v1.0 spec.

```bash
python3 code/main.py
```

What to look for: the cost table at the end (LLM calls, decision calls, hops, cost units with a decision call priced at 0.05 of an LLM call), the System One router abstaining with `p=0.333`, and the swarm bounce being caught.

## 5. Use it in production

| Need | Oct 2026 tooling |
|---|---|
| Supervisor / hierarchy in Python | LangGraph 1.2 (subgraphs), ADK 2.0 graph workflows, Microsoft Agent Framework 1.x |
| Handoffs as tools | OpenAI Agents SDK handoffs, agent SDK subagents (now including background subagents) |
| Many agents, dynamic fan-out | Coding agent `/workflows`, hosted agent platform multiagent rosters |
| Deterministic production flows | CrewAI Flows, Vercel `WorkflowAgent`, Temporal (Lesson 29) |
| Cross-org specialists | A2A v1.0.x with signed Agent Cards and OAuth/PKCE |
| Router decision | Jev / Clef `choice` behind the supervisor, LLM as the fallback |

## 6. Architect's lens

1. **Count hops, not agents.** Latency and cost scale with the critical path. A three-specialist supervisor is 2 calls per task. The same work as a hierarchy is 3+. As a debate it is N+2. Put these numbers in the design doc.
2. **The router is a classifier, so treat it like one.** Measure routing accuracy and calibration on a labeled set (Lesson 30). Pick the abstain threshold from a cost matrix, because a misrouted refund costs more than a human triage. **2026 update:** a System One `choice` call (Jev/Clef) gives you calibrated probabilities and a typed label set for a fraction of an LLM call, so the LLM only runs on the abstain branch.
3. **Every handoff needs a budget and an owner.** Use hop counters, a visited set, and one agent that is accountable for the final answer. Swarms without these produce ASI08 cascades.
4. **Draw the trust boundary at the org boundary.** Treat A2A peers as untrusted input. Verify card signatures, scope OAuth tokens per task, and never let a remote agent's output trigger privileged tools without your own guard (Lesson 27).
5. **Context is the hidden cost.** Pass each specialist the minimum slice it needs. Tool-call supervision exists so that you choose what goes over the wire.

## 7. Exercises

1. Remove the router and convert the supervisor into a swarm. Which ticket gets worse, and which metric improves?
2. Sweep the System One threshold from 0.4 to 0.9 and plot human-escalation rate against misroutes on 50 labeled tickets.
3. Add a 12-specialist domain. At what number of specialists does a single router's description list stop fitting your context budget?
4. Wrap `a2a_send` so that it also checks an allowed-skills list from the Agent Card before sending.
5. Map three of your own production flows onto the four patterns. Which ones don't map cleanly, and why?

## 8. Key terms

| Term | Meaning |
|---|---|
| Supervisor-worker | A central router dispatches to specialists that never talk to each other |
| Swarm / handoff | Peers transfer control directly through a shared tool surface |
| Hierarchical | Routers of routers, built as nested subgraphs |
| Debate | Parallel proposers plus a critique or vote step |
| Abstain path | The explicit route taken when router confidence is low |
| Agent Card | A2A metadata describing a remote agent's identity, skills and endpoint |
| Bounce | A handoff loop (A→B→A) with no progress |

## 9. Quick check

<details><summary>1. Why does the System One supervisor cost less than the LLM supervisor in the demo?</summary>Routing becomes one cheap decision call instead of an LLM call. The specialist LLM call is the same in both. The saving grows with ticket volume.</details>
<details><summary>2. When is A2A the right transport between two agents?</summary>When they are owned and deployed by different teams or orgs and need discovery, auth and task lifecycle. Inside one service, a function or tool call is simpler and safer.</details>
<details><summary>3. What is the minimum guard for a swarm?</summary>A hop limit plus a visited set, so that A→B→A is detected and escalated to an owner.</details>

## References

- A2A changelog (v1.0.0, v1.0.1): https://raw.githubusercontent.com/a2aproject/A2A/main/CHANGELOG.md
- A2A at 150+ organizations (Linux Foundation): https://www.linuxfoundation.org/press/a2a-protocol-surpasses-150-organizations-lands-in-major-cloud-platforms-and-sees-enterprise-production-use-in-first-year
- LangGraph overview: https://docs.langchain.com/oss/python/langgraph/overview
- CrewAI Crews vs Flows: https://docs.crewai.com/en/introduction
- Du et al., Improving Factuality and Reasoning through Multiagent Debate (arXiv:2305.14325)
- OWASP Top 10 for Agentic Applications 2026 summary: https://www.giskard.ai/knowledge/owasp-top-10-for-agentic-application-2026
