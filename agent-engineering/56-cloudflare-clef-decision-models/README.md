# 56 · Cloudflare Clef: Open-Weight Decision Models at the Edge

> **Short answer:** Clef is Cloudflare's open-source (Apache 2.0) family of System One decision models, launched 1 Oct 2026. It speaks the **same API as Jev**: `state` + typed `noul`/`choice`/`score` questions in, probabilities out. It runs on Workers AI close to your users, which puts the decision in the hot path of every agent step. Use **Clef-flash** (~39 ms) for guardrails and routing, **Clef** (27B) when precision matters, and **Clef-omni** for audio and video. Self-host the weights if data can't leave your network.

**Type:** Build · **Languages:** Python (stdlib), TypeScript (Workers) · **Time:** ~90 min · **New in:** Oct 2026

---

## 1. The family (as of 13 Oct 2026)

| Model ID | Size | Inputs | Hosted context | Price (input) | Latency (median) |
|---|---|---|---|---|---|
| `@cf/cloudflare/clef` | 27B | text, JSON, up to 4 images | 64K | $0.240 / M tok | ~152 ms @800 tok (after 9 Oct SGLang move) |
| `@cf/cloudflare/clef-flash` | 9B | text, JSON, images | 24K (256K self-hosted) | $0.038 / M tok | ~39 ms |
| `@cf/cloudflare/clef-omni` | 30B MoE, 3B active | + audio (WAV/MP3), video (MP4/WebM) | 64K | $0.150 / M tok | ~20 ms text, <100 ms image/audio, ~300 ms for a 21 s clip |

Cloudflare's own benchmarks put Clef ahead on 7 of 10 decision tasks. Examples: BANKING77 macro-F1 is 94.2 for Clef vs 79.7 for Jev, and BFCL is 98.8 for Clef-flash vs 95.8 for Jev. Median latency at launch was 2.5× faster than Jev for Clef and 13× faster for Clef-flash. **These are vendor numbers. Re-measure them on your own eval set** (Lesson 30).

## 2. The request shape

```ts
const res = await env.AI.run("@cf/cloudflare/clef", {
  model: "clef",
  state: "Checkout has been failing for every customer for the last hour.",
  questions: {
    urgent:   { type: "noul",   instructions: "Is this support request urgent?" },
    team:     { type: "choice", instructions: "Which team?", criteria: { billing: "…", technical: "…", sales: "…" } },
    severity: { type: "score",  instructions: "Customer impact?", criteria: ["None", "Minor", "Major", "Critical"] },
  },
});
```

Rules that trip people up:

- **`model` is required in the body.** Set it to the last segment of the model ID: `clef`, `clef-flash` or `clef-omni`.
- You can ask 1–64 questions per call. Ids may contain letters, digits, `_`, `.` and `-`, up to 100 characters.
- REST: `POST https://api.cloudflare.com/client/v4/accounts/{ACCOUNT_ID}/ai/run/@cf/cloudflare/clef` with a Bearer token.
- AI Gateway: pass `{ gateway: { id } }` as the third argument to `env.AI.run` to get caching, rate limits and logs.
- Clef-omni accepts media as base64 data URLs in `images`, `audio` and `videos`.
- **Moving from Jev:** change the endpoint and the model selector. The question schema is the same.

## 3. Where Clef fits in an agent

```
user ─► Worker ─► Clef-flash (≈40 ms): injection? in scope? route? urgent?
                    │ confident & safe              │ low confidence / risky
                    ▼                               ▼
          LLM on Workers AI / frontier API    human review queue
                    │ proposes tool call
                    ▼
          Clef guard (≈40 ms): risky? in scope? blast radius?
                    │ allow                    │ hold
                    ▼                          ▼
                 tool runs            approval / sandbox / deny
```

This is the **"guard every step"** pattern. Before Clef, adding an LLM judge to every tool call cost about a second and real money per step. At about 40 ms and $0.038 per M tokens, the check is cheap enough to run on every step.

## 4. Build it

`code/main.py` (stdlib, runs offline) contains:

- The `MODELS` table with published prices and latencies. `pick_model()` chooses the cheapest model that fits a latency budget and a context size.
- `WorkersAIRest` is a real REST client, with optional AI Gateway support. It is used when `CLOUDFLARE_ACCOUNT_ID` and `CLOUDFLARE_AUTH_TOKEN` are set.
- `LocalClef` is a toy scorer with the same response contract. It also enforces the `model` selector rule.
- `parse_noul` and `parse_choice` are strict parsers. Anything malformed raises, because a guard must never treat garbage as "allowed".
- `ClefGuard` checks injection, scope, risk and blast radius before every tool call. It supports **explicit fail-closed or fail-open**.
- `cost_report()` shows the daily cost of guarding a million tool calls.

```bash
python3 code/main.py
```

Expected output: the two safe reads run. The `DROP TABLE` with an injected instruction is **held**. The email that exfiltrates a secret is **held as out of scope**.

`code/worker.ts` is a deployable Cloudflare Worker. It uses Clef-flash to triage, block injections and route low-confidence cases to humans. It calls an LLM (`@cf/openai/gpt-oss-120b`) **only** for urgent cases that need generated text.

```bash
npm create cloudflare@latest clef-triage -- --type hello-world --lang ts
cp code/worker.ts clef-triage/src/index.ts
cd clef-triage && npx wrangler deploy
```

Add the Workers AI binding to your wrangler config before you deploy. In `wrangler.jsonc` that is `"ai": { "binding": "AI" }`, and in `wrangler.toml` it is `[ai]` with `binding = "AI"`.

## 5. Decision playbook: Clef vs Jev vs an LLM

| Need | Pick |
|---|---|
| Hot-path guard or router, latency budget under 100 ms | Clef-flash |
| Highest precision on hard text and vision classification | Clef (27B), or Jev, measured on your data |
| Voice or video agents: "did they say yes?", "is the fan running?" | Clef-omni |
| Data residency, air-gapped deployment or custom fine-tuning | Self-host the Clef weights from Hugging Face (SGLang ≥ 0.5.22) |
| Managed vendor with SDK type inference in TS and Python | Jev (`@typesafe-ai/sdk`) |
| Already all-in on OpenAI, image input | OpenAI Decisions API (`gpt-6-luna`, public beta since 6 Oct 2026) |
| Open-ended output: plans, code, prose, tool arguments | An LLM (System Two) |

Cloudflare also opened a **reinforcement-learning fine-tuning service** for Clef. It is currently design-partner access, with self-serve announced for later. Use it when your labels differ from general-purpose ones.

## 6. Architect's lens

1. **Decide fail-open vs fail-closed per decision**, and write the choice down. A spam gate can fail open. A payments guard must fail closed.
2. **Keep probability → action in code**, as Cloudflare's own docs pipeline does (`HIGH = 0.8`, `MEDIUM = 0.5`, with parsers that throw).
3. **Clef does not remove prompt-injection risk.** The model card and launch post publish no injection guidance, and `state` is attacker-controlled. Use Clef as one layer alongside capability limits, CaMeL-style data and control separation, and human approval for irreversible actions (Lesson 27).
4. **Measure end to end, not model latency alone.** Browser Run plus Clef classified a site in 2.2 s, compared with 4.7 s for gpt-oss-120b. Most of the time went to fetching and rendering the page, not the model.
5. **Watch context limits.** Hosted Clef-flash is now limited to 24K tokens, so trim `state` or move to Clef (64K).

## 7. Exercises

1. Point `main.py` at a real Workers AI account. Compare `LocalClef` verdicts with real Clef verdicts on 50 tool calls you label yourself.
2. Add an AI Gateway ID and cache identical guard calls. Measure the hit rate on a replayed agent trace.
3. Port Lesson 55's triage to Clef by changing only the transport. Prove the answers have the same shape.
4. Build a Clef-omni check for voice agents (Lesson 22): "Did the caller confirm the payment amount?"

## 8. Quick check

<details><summary>1. What happens if you omit <code>model</code> in the body?</summary>The request fails schema validation. It is required and must match the model ID selector.</details>
<details><summary>2. Why can a guard on every step be affordable now?</summary>Single-pass scoring takes tens of milliseconds and pennies per thousand calls, with no generated tokens.</details>
<details><summary>3. Name one case where Clef is the wrong tool.</summary>Producing the tool arguments, a plan or a reply. Those are generation tasks.</details>

## References

- Workers AI changelog, Clef launch (2026-10-01) and Clef-omni (2026-10-09): https://developers.cloudflare.com/changelog/
- Model pages: https://developers.cloudflare.com/workers-ai/models/clef/ · Hugging Face: https://huggingface.co/Cloudflare/clef
- Launch post: https://blog.cloudflare.com/clef-decision-models/
