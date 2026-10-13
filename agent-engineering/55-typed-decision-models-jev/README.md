# 55 · Typed Decision Models: TypeSafe Jev and the System One API

> **Short answer:** Jev is a decision model, not a text model. You send it `state` plus a set of typed questions (`noul`, `choice`, `score`). In one forward pass it returns a calibrated probability for every allowed answer. Your code, not the model, decides what happens next. Use it for agent routers, guards, stop conditions and judges. Keep LLMs for work that actually needs generation.

**Type:** Build · **Languages:** Python (stdlib), TypeScript · **Time:** ~75 min · **New in:** Oct 2026

---

## 1. Why this lesson exists

In 2023–2025 most agent stacks made routing and gating decisions the expensive way:

```
LLM("Return JSON {team: billing|technical|other}") -> parse -> retry on bad JSON -> hope
```

That pattern has four problems:

1. **Latency.** It costs seconds of reasoning tokens for a decision that has three possible answers.
2. **No calibration.** `"billing"` arrives with no probability, so you can't set a threshold.
3. **Schema drift.** The model can return `"Billing"`, `"payments"` or prose.
4. **Cost at scale.** Every tool call, every message and every step pays a generation tax.

TypeSafe AI calls its answer **System One models**, after Kahneman's fast/slow split. Jev is the hosted model (`jev-latest`; `jev-1.13` at the time of writing). It reads a state and a typed question schema and scores every allowed answer at once. It never writes free text.

## 2. The API in one screen

| Primitive | You send | You get back |
|---|---|---|
| `noul` | yes/no `instructions`, optional `criteria: {true, false}` | `noul`: P(yes) ∈ [0,1] |
| `choice` | `instructions`, `criteria: {label: description \| null}` | `choice`, `confidence`, `probabilities{label}` |
| `score` | `instructions`, ordered `criteria: [level0, level1, …]` (≥2) | `score` (expected level, can be fractional), `confidence`, `legend`, `probabilities` |

Request: `POST https://api.typesafe.ai/v1/systemone` with `{model, state, questions}`. Response: `{model, answers, usage}`.
SDKs: `npm i @typesafe-ai/sdk` (Node ≥20) and `uv add typesafe-sdk` (Python ≥3.10). Both read `TYPESAFE_API_KEY`.

### Why "typesafe" is literal

The TS SDK uses `const` generics, so the labels you write become literal types:

```ts
const q = { team: choice("Which team?", { billing: null, technical: null, other: null }) };
const { answers } = await client.systemOne({ state, questions: q });
answers.team.choice
answers.team.probabilities.billing
```

`answers.team.choice` is typed `"billing" | "technical" | "other"`. A typo like `answers.team.probabilities.biling` fails at **compile time**. In TypeScript, a `switch` over `choice` can be checked for exhaustiveness. Rename a label and the compiler finds every branch that broke. Calling an LLM for JSON gives you none of this.

## 3. Mental model: System One vs System Two

```
            ┌──────────── System One (ms) ─────────────┐
 state ───► │ route? guard? done? quality? risk?       │──► probabilities ──► code decides
            └──────────────────────────────────────────┘                      │
                                                                              ▼
            ┌──────────── System Two (s) ──────────────┐            only if needed
            │ LLM agent loop: plan, call tools, write  │◄───────────────────────┘
            └──────────────────────────────────────────┘
```

In a typical 2026 agent, these decisions are good fits for System One:

| Agent decision | Primitive |
|---|---|
| Which sub-agent or tool handles this? | `choice` |
| Is this tool call safe and within scope? | `noul` |
| Is the task done, so the loop can stop? | `noul` |
| How good is this draft, on a 0–4 rubric? | `score` (replaces many LLM-as-judge calls) |
| Is this retrieved doc relevant? | `noul` per doc, up to 64 questions per call |
| Does this message contain an injection attempt? | `noul` |

## 4. Build it

`code/main.py` implements the whole contract with the stdlib:

- `Noul`, `Choice` and `Score` dataclasses, plus `validate()`. Validation enforces 1–64 questions, legal ids, at least two labels per `choice` and an ordered list for `score`. It rejects bad requests before they reach the network.
- `LocalSystemOne` is a deterministic toy scorer with the same response shape as Jev, so the lesson runs offline.
- `TypeSafeHttp` is the real `POST /v1/systemone` call. It is used automatically when `TYPESAFE_API_KEY` is set.
- `route()` is the important part: **thresholds and control flow live in your code.**

```bash
python3 code/main.py
TYPESAFE_API_KEY=ts-... python3 code/main.py
```

`code/main.ts` is the production TypeScript version, built on the official SDK and a discriminated-union `Action` type:

```bash
npm i @typesafe-ai/sdk && npx tsx code/main.ts "The API is down for everyone"
```

## 5. Use it (Oct 2026 ecosystem)

**Timeline:** Jev launched 15 Sep 2026. Cloudflare Clef launched 1 Oct with the same API and open weights. The OpenAI Decisions API (`POST /v1/decisions`, `gpt-6-luna`) entered public beta on 6 Oct. Decision models went from one vendor to an industry pattern in about three weeks.

- **Direct SDKs:** `@typesafe-ai/sdk` (TS) and `typesafe-sdk` (Python).
- **Vercel AI SDK v7:** typed choice, score and boolean questions through `experimental_decide`. It was renamed from `experimental_evaluate` in 7.0.128; use `decide`.
- **Pydantic AI:** provides a `DecisionModel` abstraction. Your output type *is* the question schema: `bool` becomes noul, `Literal`/`Enum` becomes choice, and `IntEnum` becomes score. Backends include `typesafe:jev-latest`, `system-one:<model>` for any `/v1/systemone`-compatible server, and `openai-decisions:gpt-6-luna`. `FallbackModel("typesafe:jev-latest", "<your-llm>")` escalates to an LLM when a field cannot be decided. This is System One → System Two in one line.
- **Gateways:** Cloudflare Workers AI lists Jev as a third-party model. Community sources also report OpenRouter and other gateway routes; verify them before relying on them.
- **Drop-in open alternative:** Cloudflare **Clef** (Lesson 56).

## 6. Architect's lens (principal-level design notes)

1. **Thresholds are product decisions.** Pick them from a labeled eval set (Lesson 30) and a cost matrix, not from intuition. A wrong auto-refund costs more than a wrong queue assignment.
2. **Always have an abstain path.** Use a low `confidence`, an `other` label or a `score` that sits mid-range to send work to a human or to System Two. This is how you get "no human in the loop" safely for the confident 90%.
3. **Batch questions.** One call with 10 questions is one forward pass. Ten LLM calls means ten generations.
4. **State is still untrusted.** A decision model is harder to hijack than a generator because it can't emit arbitrary actions. It can still be biased by injected text. Pair it with the rules in Lesson 27.
5. **Log probabilities, not just labels.** Calibration drift is how you detect data drift. Alert when the mean `confidence` drops week over week.
6. **Version-pin in production** (`jev-1.13`, not `jev-latest`), and re-run your decision eval on every model bump.

## 7. Exercises

1. Add a `stop` noul to Lesson 01's agent loop: "Has the user's task been fully completed?" Stop when P > 0.85. Compare the turn counts.
2. Turn an LLM-as-judge rubric from Lesson 30 into a `score` question. Measure agreement against human labels.
3. Build a cost-matrix threshold picker: given labeled data and a cost per error type, choose the threshold with minimum expected cost.
4. Make `route()` exhaustive in TypeScript using a `never` check, then add a `sales` label and watch the compiler point at the gap.

## 8. Key terms

| Term | Meaning |
|---|---|
| System One model | A model that scores a fixed answer space in one pass and never generates text |
| `noul` | A yes/no question answered as P(yes) |
| Calibration | Whether a 0.8 means "right 80% of the time" |
| Abstain path | The explicit route taken when confidence is low |

## 9. Quick check

<details><summary>1. Why is <code>score</code> returned as a float?</summary>It is the probability-weighted expected level, so 1.6 means "between Today and Right now, leaning Right now".</details>
<details><summary>2. Where should the 0.9 threshold live?</summary>In your code and config, tuned on evals. Never put it inside the prompt.</details>
<details><summary>3. When would you still use an LLM?</summary>When the output is open-ended: plans, code, prose, or tool arguments that can't be enumerated.</details>

## References

- TypeSafe JS SDK: https://github.com/typesafe-ai/typesafe-sdk-js · Python SDK: https://github.com/typesafe-ai/typesafe-sdk-python
- Docs: https://docs.typesafe.ai · Community guide: https://github.com/AbdelStark/awesome-typesafe-jev
