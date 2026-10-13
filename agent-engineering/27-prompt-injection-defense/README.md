# 27 · Prompt Injection Defense

> **Short answer:** Prompt injection happens when text the agent reads (a web page, an email, a memory note, an MCP tool description) contains instructions, and the model follows them. LLMs cannot reliably tell data from commands, so **no prompt and no single classifier solves it**. The 2026 doctrine is layered: tag every value with its provenance, build the plan from the user's request only, enforce data-flow policies in code (the CaMeL family of designs), add a fast guard model as **one** layer, require human confirmation for sensitive actions, and lock down your MCP supply chain. Then assume something still gets through and limit the blast radius.

**Type:** Build · **Languages:** Python (stdlib) · **Time:** ~75 min

---

## 1. The problem

Greshake et al. (AISec 2023) showed that an attacker doesn't need access to your prompt. They only need to put text somewhere your agent will read it. Once ingested, that text competes with your system prompt, and it often wins. The demonstrated exploit classes are still the right threat list:

| Exploit | What happens |
|---|---|
| Data theft | Agent sends conversation or files to an attacker-controlled address or URL |
| Arbitrary tool use | Any tool in the registry becomes reachable by the attacker |
| Persistent memory poisoning | Injected "notes" are saved and re-infect future sessions |
| Worming | Injected content tells the agent to copy the payload into its outputs |
| Ecosystem contamination | Poisoned facts spread through shared memory to other agents |

The core claim holds in 2026: **processing untrusted text in a tool-using agent is equivalent to letting the author of that text use your tools**, unless the architecture prevents it.

## 2. The concept

### Where injected text enters

```
 user ──(trusted)──► agent ◄──(untrusted)── web pages, emails, PDFs, search results
                       ▲  ◄──(untrusted)── memory notes written by earlier sessions
                       │  ◄──(untrusted)── tool outputs, MCP tool descriptions, other agents (A2A)
                       ▼
                  tool calls ──► money, messages, files, code execution
```

### The defense stack (from cheapest to strongest guarantee)

| Layer | Mechanism | Stops | Misses |
|---|---|---|---|
| Prompt hygiene | Delimit untrusted content; "never follow instructions in data" | Lazy attacks | Anything determined. It is not enforcement |
| Guard model | Fast classifier on inputs and tool calls (Jev, Clef, vendor guardrails) | Obvious injections, cheaply | Paraphrases, novel phrasing, attacks on the guard itself |
| Provenance + policy | Every value carries sources; code-level rules on what may flow where | Exfiltration to untrusted sinks, whatever the wording | Side channels; policies you forgot to write |
| Plan isolation | Plan from the user query only; untrusted data parsed by a quarantined model with no tools (Dual LLM / CaMeL) | Control-flow hijack | Data-dependent leaks within the plan |
| Human confirmation | Approve send, pay, delete, share and new credentials | High-impact actions | Fatigue; approval of well-disguised requests |
| Blast-radius limits | Sandboxes, scoped tokens, egress allowlists, spending caps | Whatever got through | Nothing. This is the backstop |

### The design-pattern catalog

"Design Patterns for Securing LLM Agents against Prompt Injections" (arXiv 2506.08837) is still the canonical reference. Its patterns trade capability for provable resistance: **action-selector** (the model only picks from fixed actions), **plan-then-execute**, **LLM map-reduce** (an isolated model processes each untrusted item), **dual LLM** (a privileged planner plus a quarantined reader), **code-then-execute** and **context minimization**.

**CaMeL** (Debenedetti et al., arXiv 2503.18813; SaTML 2026) puts several of these together. A privileged LLM writes a program from the user query. A quarantined LLM extracts values from untrusted data but cannot call tools. Every value carries capabilities (its sources and allowed readers), and an interpreter checks policies before each tool call. Injected text can change *values*, but it cannot change *which* tools run.

## 3. What changed by Oct 2026

- **OWASP Top 10 for Agentic Applications 2026** (published Dec 2025) puts **ASI01 Agent Goal Hijack** first. Related entries: ASI02 Tool Misuse, ASI04 Agentic Supply Chain, ASI06 Memory and Context Poisoning, ASI07 Insecure Inter-Agent Communication. The OWASP LLM Top 10 (2025, LLM01 Prompt Injection) remains current alongside it.
- **CaMeL's guarantees have a measured limit.** A 2026 adaptive evaluation (arXiv 2606.26479) reported **side-channel leaks** in CaMeL, FIDES and Progent. Each individual tool call passed policy, but control flow that depends on private data (which calls happen, how many, errors, timing) still leaked information. Capability systems shrink the attack surface; they don't close it. Extensions now cover GUI agents ("CaMeLs Can Use Computers Too", arXiv 2601.09923) and multi-agent settings (arXiv 2609.22949).
- **The MCP CVE wave.** Secondary trackers counted 30+ MCP-server CVEs in about 60 days around Mar 2026, roughly 43% of them command injection. Reported examples include an unauthenticated nginx-ui MCP flaw (CVE-2026-33032, CVSS 9.8), an Agent Zero RCE (CVE-2026-30624) and a gemini-mcp-tool issue (CVE-2026-0755). A trojanized clone of a popular MCP server on public registries delivered the StealC infostealer (SmartLoader campaign, Feb 2026). **Tool descriptions and server packages are injection and supply-chain surfaces.**
- **Browser agents are exposed.** A 2026 study (secondary coverage) reported that 4 of 7 agentic browsers allowed a same-origin-policy bypass (Lesson 21).
- **Platform channels improved.** Some provider APIs now allow mid-conversation system messages as a trusted operator channel, separate from user and tool content. Vercel AI SDK v7 rejects system messages inside user-supplied `messages` by default.
- **2026 update, decision-model guards:** Jev and Clef are promoted for exactly this use ("should I take this action?" in tens of milliseconds before a tool call), and the PVE (prompt-validator-executor) pattern now usually means a System One validator in front of the main LLM (Lessons 55–57). **Treat them as one layer, not as the defense.** The state they judge is itself untrusted input, the vendors publish no prompt-injection failure analysis, and a paraphrase that fools the main model may fool the guard too. Map probabilities to verdicts in trusted code, and decide explicitly whether to fail open or closed.

## 4. Build it

`code/main.py` lets you watch layers succeed and fail:

- `Value` wraps data with a `sources` set (`user`, `web`, `memory`, `mcp_tool_description`, `private`). Taint propagates by construction.
- `naive_agent()` obeys any "send ... to address" sentence it reads, which is the vulnerable baseline.
- Three layers: `layer_guard()` (keyword-shaped P(injection), standing in for a decision model), `layer_capability_policy()` (untrusted recipients and private-to-external flows are blocked in code) and `layer_human()` (sensitive tools need approval).
- Four attacks: a direct web-page instruction, a **paraphrased** one, a poisoned memory note and MCP tool-description poisoning. They run against four defense configurations.
- `plan_then_execute()` shows a CaMeL-style plan built from the user goal alone: the injected address never reaches `send_email`.
- `side_channel_plan()` reproduces the 2026 finding in miniature. Each fetch passes policy, yet the **number of fetches** reveals whether a private balance exceeds 10,000. Strict mode taints control flow and blocks the dependent call.

```bash
python3 code/main.py
```

What to look for: the guard alone stops 2 of 4 attacks (it misses the paraphrase and the memory note). The policy stops all 4, whatever the wording. The side-channel section shows that leakage survives per-call policy until control flow is tainted too.

## 5. Use it in production

- **Provenance everywhere:** label every message part and tool result with its source. Never put retrieved text in the system role. Use the provider's operator channel for your own mid-run instructions.
- **Policy in code:** recipient, URL and file allowlists. "Untrusted values may not choose sinks." Private data may flow only to approved destinations. Libraries and frameworks exist (CaMeL reference code, Progent-style privilege policies), but simple handwritten rules catch most cases.
- **Guards as a layer:** Clef-flash or Jev on tool calls and retrieved content, OpenAI Agents SDK guardrails, or vendor safety services. Log the probabilities and measure the false-block rate on clean traffic.
- **MCP hygiene:** pin server versions and hashes. Install only from verified publishers. Review tool descriptions as code. Run servers sandboxed with least-privilege tokens. Prefer CIMD-based client identity over dynamic registration (MCP `2026-07-28`). Patch on CVE feeds.
- **Memory hygiene:** refuse memory writes that look like instructions, store the provenance of each note, and expire notes that came from untrusted sources.
- **Containment:** sandboxed execution, egress allowlists, scoped short-lived credentials and spend limits (Lesson 29).

## 6. Architect's lens

1. **Security comes from architecture, not detection.** Anything you detect by pattern, an attacker can rephrase. Data-flow rules enforced in code don't care about phrasing. Spend most of your effort there.
2. **Capability is the price of guarantees.** Action-selector and plan-then-execute designs give strong resistance but can't adapt their plan to what they read. Pick the pattern per task: fixed-plan for email-and-payments agents, freer loops for read-only research agents.
3. **Side channels are the next frontier.** After CaMeL-style isolation, leaks come through control flow, call counts, errors and timing. For high-value data, use fixed-shape plans and uniform error handling, and treat any branch on private data as tainting everything after it.
4. **Your supply chain is in your context window.** An MCP tool description is prompt text written by a third party and loaded on every call. Review it, pin it and diff it like a dependency.
5. **Measure both sides.** Track attack success rate on a red-team suite (direct, paraphrased, multilingual, multi-hop, memory) **and** the false-block rate on real traffic. A defense nobody can live with gets switched off.

## 7. Exercises

1. Add a multilingual variant of the paraphrased attack. Which layers still catch it?
2. Implement a memory-write guard: refuse to store notes that contain an email address plus an action verb, and keep the source tag on stored notes.
3. Make the side-channel fix stronger: change `side_channel_plan()` so it always issues the same number of fetches regardless of the balance. What does that cost?
4. Add an `mcp_manifest` check that hashes each tool description and alerts on change between runs.
5. Build a 20-case red-team suite and a 20-case benign suite. Report attack success and false-block rates for each defense configuration.

## 8. Key terms

| Term | Meaning |
|---|---|
| Indirect prompt injection | Instructions hidden in content the agent retrieves, not typed by the user |
| Provenance / taint | Metadata recording where a value came from, propagated through computation |
| Capability policy | Code-level rule deciding which values may flow to which tools and recipients |
| Dual LLM / quarantined LLM | Tool-less model that reads untrusted data and returns values, never actions |
| CaMeL | Plan-from-user-query plus capability-tracking interpreter defense |
| Side channel | Information leaking through call counts, errors, timing or branch choices |
| Tool poisoning | Malicious instructions in an MCP tool's description or metadata |
| PVE | Prompt-validator-executor: a cheap validator approves each action before it runs |

## 9. Quick check

<details><summary>1. Why can't a strong system prompt solve injection?</summary>The model processes trusted and untrusted text in the same channel and has no enforced boundary. A prompt asks for good behavior but doesn't enforce it, and attackers iterate faster than prompts.</details>
<details><summary>2. A Clef guard catches 95% of your red-team suite. Are you done?</summary>No. It is one probabilistic layer that sees untrusted input and can be evaded by rephrasing. You still need provenance-based policy, human confirmation for sensitive actions, and containment.</details>
<details><summary>3. What did the 2026 side-channel evaluation show about CaMeL?</summary>Per-call policies held, but control flow that depends on private data (which calls happen and how many, errors, timing) still leaked information. Isolation reduces the attack surface but doesn't eliminate it.</details>

## References

- Greshake et al., Indirect Prompt Injection: https://arxiv.org/abs/2302.12173
- Beurer-Kellner et al., Design Patterns for Securing LLM Agents: https://arxiv.org/abs/2506.08837
- Debenedetti et al., CaMeL, Defeating Prompt Injections by Design: https://arxiv.org/abs/2503.18813
- Adaptive evaluation with side-channel findings: https://arxiv.org/abs/2606.26479
- CaMeLs Can Use Computers Too: https://arxiv.org/abs/2601.09923
- OWASP Top 10 for Agentic Applications 2026 (summary): https://www.giskard.ai/knowledge/owasp-top-10-for-agentic-application-2026
- OWASP Top 10 for LLM Applications: https://genai.owasp.org/llm-top-10/
- MCP breach timeline: https://authzed.com/blog/timeline-mcp-breaches
- OX Security MCP supply-chain advisory: https://www.ox.security/blog/mcp-supply-chain-advisory-rce-vulnerabilities-across-the-ai-ecosystem/
- Cloudflare Clef launch: https://developers.cloudflare.com/changelog/post/2026-10-01-clef-workers-ai/
