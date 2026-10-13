# 23 · OpenTelemetry GenAI Semantic Conventions

> **Short answer:** The OpenTelemetry GenAI semantic conventions are a shared vocabulary for agent telemetry: span names such as `invoke_agent`, `chat` and `execute_tool`, attributes such as `gen_ai.provider.name` and `gen_ai.usage.input_tokens`, and rules for when prompt content may be recorded. Instrument against them and your traces read the same in Datadog, Grafana, Langfuse, Phoenix or Jaeger. As of Oct 2026 they are **still in Development status, not Stable**, and they now live in their own repository. Adopt them, but pin the version you emit.

**Type:** Learn + Build · **Languages:** Python (stdlib) · **Time:** ~60 min

---

## 1. The problem

Every agent framework used to invent its own trace format. LangChain called a step one thing, CrewAI another, and your in-house loop a third. The result was one dashboard per framework, no cross-provider cost view, and no way to follow a request from your agent into an MCP server and back.

Telemetry also has a second, sharper problem: **content**. Prompts contain customer emails, account numbers and secrets. A tracing setup that copies every message into span attributes turns your observability backend into the largest unaudited PII store in the company.

The GenAI conventions address both: a common schema, and a capture policy where recording content is opt-in.

## 2. The concept

### Span tree

```
invoke_agent support-agent        INTERNAL (in-process) / CLIENT (remote agent service)
├── chat gpt-6-luna               CLIENT   model call: tokens, model, finish reasons
├── execute_tool lookup_order     INTERNAL one per tool call
│     └── (MCP server spans)      linked via W3C traceparent in the request _meta
├── execute_tool refund           status=ERROR, error.type=...
└── chat gpt-6-luna               CLIENT
```

`create_agent` marks agent construction. Span names follow `{operation} {target}`, for example `invoke_agent {gen_ai.agent.name}` or `chat {gen_ai.request.model}`.

### Core attributes

| Attribute | Example | Why it matters |
|---|---|---|
| `gen_ai.operation.name` | `chat`, `invoke_agent`, `execute_tool`, `create_agent`, `embeddings` | The query key for every dashboard |
| `gen_ai.provider.name` | `openai`, `gcp.gemini`, `aws.bedrock` | Cost and error split by provider |
| `gen_ai.request.model` / `gen_ai.response.model` | requested vs resolved snapshot | Routing and alias drift show up here |
| `gen_ai.agent.name` / `gen_ai.agent.id` | `support-agent` | Per-agent SLOs |
| `gen_ai.conversation.id` | `conv-77` | Joins turns into a session |
| `gen_ai.tool.name` / `gen_ai.tool.call.id` | `refund`, `call_2` | Ties a tool span to the model's tool call |
| `gen_ai.usage.input_tokens` / `output_tokens` | 812 / 41 | Cost |
| `gen_ai.response.finish_reasons` | `["tool_calls"]` | Truncation and refusal analysis |
| `gen_ai.data_source.id` | `kb-prod` | Which retrieval corpus answered |
| `error.type` | `ToolFailed` | Error rate by class |

Metrics include `gen_ai.client.token.usage` and `gen_ai.client.operation.duration` (histograms). Provider-specific extensions exist for OpenAI, Azure AI Inference, AWS Bedrock and others.

### Content capture: three modes

| Mode | What spans carry | Use |
|---|---|---|
| Off (default) | Metadata only | Production default |
| Reference | `...messages.ref = blob://...` pointing to a governed store | Production debugging with retention and access control |
| Inline | `gen_ai.input.messages`, `gen_ai.output.messages`, `gen_ai.system_instructions` as attributes | Local development only |

The spec says instrumentations SHOULD NOT capture content by default. Use the reference pattern in production: keep content in a store with retention, redaction and an access policy, and keep only the pointer on the span.

## 3. What changed by Oct 2026

- **Still not stable.** All `gen_ai.*` attributes, spans, metrics and events remain at **Development** stability. Set `OTEL_SEMCONV_STABILITY_OPT_IN=gen_ai_latest_experimental` where your instrumentation supports it, and expect renames.
- **New home.** Around Jun 2026 (semconv v1.42 timeframe) the GenAI conventions moved out of the main `semantic-conventions` repo into **`open-telemetry/semantic-conventions-genai`**. Update bookmarks, CI schema checks and links in internal docs.
- **Agent spans are mainstream.** `create_agent`, `invoke_agent` and `execute_tool`, plus model `chat` spans, are what the OpenAI Agents SDK, Google ADK, Microsoft Agent Framework, LangGraph and Pydantic AI (via Logfire / OpenInference) emit or map to.
- **MCP propagates trace context.** The MCP `2026-07-28` spec carries OTel `traceparent` in request `_meta`. A tool call and the server work it triggers now land in one trace, even though the protocol is stateless.
- **Vercel AI SDK v7** made telemetry stable and moved it into a separate `@ai-sdk/otel` package. Its `experimental_decide` (decision-model) calls emit spans as well.
- **2026 update, System One:** treat decision-model calls (Jev, Clef) as first-class spans. Record the question ids, the chosen answer and the probability as attributes, so you can audit every guard or router verdict later (Lessons 55–57).

## 4. Build it

`code/main.py` is a stdlib tracer that emits convention-shaped spans:

- `Tracer.span()` is a context manager that nests spans, sets `status`, and records `error.type` on exceptions.
- `run_agent()` emits `create_agent`, `invoke_agent`, two `chat` spans and two `execute_tool` spans. One tool fails.
- `fake_mcp_server()` receives the W3C `traceparent` inside `_meta`, the way an MCP `2026-07-28` server does.
- `record_content()` implements the three capture modes. `ContentStore` holds blobs addressed by content hash.
- `lint()` checks required attributes per operation and flags raw content in spans.

```bash
python3 code/main.py
```

What to look for: the same tree under all three capture modes. Only `inline` fails the lint with PII warnings. The error is attributed to `execute_tool refund`, and the `traceparent` was forwarded to the tool server.

## 5. Use it in production

- **Instrumentation:** framework-native OTel exporters (OpenAI Agents SDK tracing processors, ADK, Microsoft Agent Framework, `@ai-sdk/otel`), or the OpenLLMetry / OpenInference instrumentors for raw provider SDKs.
- **Pipeline:** export to an OTel Collector. Redact there (attribute processors), sample by tail (keep every errored or slow trace), then fan out to your backends.
- **Backends:** Datadog LLM Observability, Grafana Tempo, Honeycomb and Jaeger for raw traces; Langfuse, Arize Phoenix and LangSmith for agent-centric views and evals (Lesson 24).
- **Version pinning:** record the semconv version your instrumentation emits (a resource attribute or schema URL) so backend upgrades don't silently break dashboards.

## 6. Architect's lens

1. **Telemetry is a data-governance system.** Default to no content. Use references with retention and role-based access, and redact at the Collector. A trace backend breach must not become a customer-data breach.
2. **Design for renames.** The conventions are still in Development. Keep a thin mapping layer so a rename is a config change, and run a schema lint in CI, like `lint()` here.
3. **Propagate context across every hop.** Agent → tool → MCP server → sub-agent (A2A) should be one trace. Orphaned spans are the most common reason "observability" fails during an incident.
4. **Tail-sample, don't head-sample.** Agent traces are big and most are boring. Keep 100% of errors, timeouts, guard blocks and high-cost runs, and a small share of the rest.
5. **Tokens on spans are your cost ledger.** Summing `gen_ai.usage.*` by agent, model and tenant gives you finance-grade cost attribution without a separate billing pipeline.

## 7. Exercises

1. Add a `gen_ai.data_source.id` attribute to a new `retrieve` span and show which corpus each answer came from.
2. Implement tail sampling: export only traces that contain an `ERROR` span or exceed 1,000 ms.
3. Add a Collector-style redaction step that masks email addresses in any attribute before export.
4. Model a remote agent call: an `invoke_agent` span with kind `CLIENT` whose child spans come from another process via `traceparent`.
5. Add a decision-model span (`gen_ai.operation.name = "decide"` as a local extension) carrying the guard's probability. How would you query "all actions blocked at P > 0.9 last week"?

## 8. Key terms

| Term | Meaning |
|---|---|
| Semantic conventions | Agreed names and meanings for span names, attributes and metrics |
| `invoke_agent` | Span for one agent run. INTERNAL in-process, CLIENT for a remote agent service |
| `execute_tool` | Span for one tool invocation |
| `chat` span | Span for one model inference call |
| Content capture | Opt-in recording of prompts and responses. Store by reference in production |
| Stability opt-in | `OTEL_SEMCONV_STABILITY_OPT_IN` value that selects the latest experimental conventions |
| traceparent | W3C header that links spans across processes, now carried in MCP `_meta` |
| Tail sampling | Deciding to keep a trace after it completes, based on its content |

## 9. Quick check

<details><summary>1. Are the GenAI conventions stable in Oct 2026?</summary>No. They remain at Development status and now live in the separate semantic-conventions-genai repo. Pin the version you emit and expect renames.</details>
<details><summary>2. Why record a reference instead of the prompt on the span?</summary>Prompts carry PII and secrets. A reference lets you apply retention, redaction and access control in one governed store while keeping traces debuggable.</details>
<details><summary>3. How does a tool span connect to the work an MCP server does?</summary>The client puts the W3C traceparent in the request's _meta. The server starts its spans as children of that context, so both sides land in one trace.</details>

## References

- OTel GenAI semantic conventions: https://opentelemetry.io/docs/specs/semconv/gen-ai/
- GenAI conventions repository: https://github.com/open-telemetry/semantic-conventions-genai
- Background on the repo move: https://john-hodge.com/blog/opentelemetry-genai-semantic-conventions/
- MCP 2026-07-28 changelog: https://modelcontextprotocol.io/specification/2026-07-28/changelog
- W3C Trace Context: https://www.w3.org/TR/trace-context/
- OpenAI Agents SDK tracing: https://openai.github.io/openai-agents-python/tracing/
- Vercel AI SDK changelog: https://raw.githubusercontent.com/vercel/ai/main/packages/ai/CHANGELOG.md
