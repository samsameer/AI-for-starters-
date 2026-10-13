from __future__ import annotations

import hashlib
import json
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Iterator

REQUIRED_BY_OPERATION = {
    "create_agent": ("gen_ai.operation.name", "gen_ai.provider.name", "gen_ai.agent.name"),
    "invoke_agent": ("gen_ai.operation.name", "gen_ai.provider.name", "gen_ai.agent.name"),
    "chat": ("gen_ai.operation.name", "gen_ai.provider.name", "gen_ai.request.model"),
    "execute_tool": ("gen_ai.operation.name", "gen_ai.tool.name", "gen_ai.tool.call.id"),
}

CONTENT_KEYS = ("gen_ai.system_instructions", "gen_ai.input.messages", "gen_ai.output.messages")


@dataclass
class Span:
    name: str
    kind: str
    trace_id: str
    span_id: str
    parent_id: str | None
    start_ms: int
    end_ms: int = 0
    attributes: dict[str, object] = field(default_factory=dict)
    status: str = "UNSET"


class ContentStore:
    def __init__(self) -> None:
        self.rows: dict[str, str] = {}

    def put(self, payload: object) -> str:
        blob = json.dumps(payload, sort_keys=True)
        ref = "blob://" + hashlib.sha256(blob.encode()).hexdigest()[:12]
        self.rows[ref] = blob
        return ref


class Tracer:
    def __init__(self, capture_mode: str, store: ContentStore) -> None:
        self.capture_mode = capture_mode
        self.store = store
        self.spans: list[Span] = []
        self.stack: list[Span] = []
        self.clock_ms = 0
        self.counter = 0
        self.trace_id = "4bf92f3577b34da6a3ce929d0e0e4736"

    def next_span_id(self) -> str:
        self.counter += 1
        return f"{self.counter:016x}"

    def tick(self, ms: int) -> None:
        self.clock_ms += ms

    @contextmanager
    def span(self, name: str, kind: str, **attributes: object) -> Iterator[Span]:
        parent = self.stack[-1].span_id if self.stack else None
        current = Span(name, kind, self.trace_id, self.next_span_id(), parent, self.clock_ms, attributes=dict(attributes))
        self.stack.append(current)
        try:
            yield current
            if current.status == "UNSET":
                current.status = "OK"
        except Exception as exc:
            current.status = "ERROR"
            current.attributes["error.type"] = type(exc).__name__
        finally:
            current.end_ms = self.clock_ms
            self.stack.pop()
            self.spans.append(current)

    def record_content(self, span: Span, key: str, payload: object) -> None:
        if self.capture_mode == "off":
            return
        if self.capture_mode == "inline":
            span.attributes[key] = json.dumps(payload)
            return
        span.attributes[key + ".ref"] = self.store.put(payload)

    def traceparent(self) -> str:
        return f"00-{self.trace_id}-{self.stack[-1].span_id}-01"


class ToolFailed(Exception):
    pass


def fake_mcp_server(request: dict) -> dict:
    parent = request["params"]["_meta"]["traceparent"]
    if request["params"]["name"] == "refund":
        raise ToolFailed("upstream 409")
    return {"resultType": "complete", "content": [{"type": "text", "text": "order 812: shipped"}], "linked_to": parent}


def run_agent(tracer: Tracer) -> None:
    common = {"gen_ai.provider.name": "openai", "gen_ai.agent.name": "support-agent"}
    with tracer.span("create_agent support-agent", "INTERNAL", **{"gen_ai.operation.name": "create_agent"}, **common):
        tracer.tick(3)
    with tracer.span("invoke_agent support-agent", "INTERNAL", **{"gen_ai.operation.name": "invoke_agent", "gen_ai.conversation.id": "conv-77"}, **common) as agent:
        tracer.record_content(agent, "gen_ai.system_instructions", [{"type": "text", "content": "You are a support agent."}])
        with tracer.span("chat gpt-6-luna", "CLIENT", **{"gen_ai.operation.name": "chat", "gen_ai.provider.name": "openai", "gen_ai.request.model": "gpt-6-luna"}) as chat:
            tracer.tick(420)
            tracer.record_content(chat, "gen_ai.input.messages", [{"role": "user", "parts": [{"type": "text", "content": "Where is order 812? My email is ana@example.com"}]}])
            chat.attributes.update({"gen_ai.response.model": "gpt-6-luna-2026-10-01", "gen_ai.usage.input_tokens": 812, "gen_ai.usage.output_tokens": 41, "gen_ai.response.finish_reasons": ["tool_calls"]})
        for call_id, tool in (("call_1", "lookup_order"), ("call_2", "refund")):
            with tracer.span(f"execute_tool {tool}", "INTERNAL", **{"gen_ai.operation.name": "execute_tool", "gen_ai.tool.name": tool, "gen_ai.tool.call.id": call_id, "gen_ai.tool.type": "extension"}) as tool_span:
                tracer.tick(130)
                request = {"method": "tools/call", "params": {"name": tool, "_meta": {"traceparent": tracer.traceparent()}}}
                result = fake_mcp_server(request)
                tool_span.attributes["mcp.traceparent.forwarded"] = result["linked_to"]
        with tracer.span("chat gpt-6-luna", "CLIENT", **{"gen_ai.operation.name": "chat", "gen_ai.provider.name": "openai", "gen_ai.request.model": "gpt-6-luna"}) as chat2:
            tracer.tick(380)
            chat2.attributes.update({"gen_ai.usage.input_tokens": 990, "gen_ai.usage.output_tokens": 63, "gen_ai.response.finish_reasons": ["stop"]})
            tracer.record_content(chat2, "gen_ai.output.messages", [{"role": "assistant", "parts": [{"type": "text", "content": "Order 812 has shipped."}]}])


def render_tree(spans: list[Span]) -> None:
    children: dict[str | None, list[Span]] = {}
    for s in sorted(spans, key=lambda s: (s.start_ms, s.span_id)):
        children.setdefault(s.parent_id, []).append(s)

    def walk(parent: str | None, depth: int) -> None:
        for s in children.get(parent, []):
            print(f"  {'  ' * depth}{s.name:<34} {s.kind:<8} {s.end_ms - s.start_ms:>4} ms  {s.status}")
            walk(s.span_id, depth + 1)

    walk(None, 0)


def lint(spans: list[Span]) -> list[str]:
    problems = []
    for s in spans:
        op = str(s.attributes.get("gen_ai.operation.name"))
        for key in REQUIRED_BY_OPERATION.get(op, ()):
            if key not in s.attributes:
                problems.append(f"{s.name}: missing {key}")
        for key in CONTENT_KEYS:
            if key in s.attributes:
                problems.append(f"{s.name}: raw content in {key} (PII risk)")
    return problems


def token_metrics(spans: list[Span]) -> dict[str, int]:
    totals = {"input": 0, "output": 0}
    for s in spans:
        totals["input"] += int(s.attributes.get("gen_ai.usage.input_tokens", 0))
        totals["output"] += int(s.attributes.get("gen_ai.usage.output_tokens", 0))
    return totals


def main() -> None:
    print("=" * 74)
    print("OTEL GENAI SEMANTIC CONVENTIONS (status: Development, Oct 2026)")
    print("env: OTEL_SEMCONV_STABILITY_OPT_IN=gen_ai_latest_experimental")
    print("=" * 74)
    for mode in ("off", "reference", "inline"):
        store = ContentStore()
        tracer = Tracer(mode, store)
        run_agent(tracer)
        print(f"\ncapture mode = {mode!r}")
        render_tree(tracer.spans)
        tokens = token_metrics(tracer.spans)
        print(f"  gen_ai.client.token.usage: input={tokens['input']} output={tokens['output']}")
        print(f"  external store rows: {len(store.rows)}")
        issues = lint(tracer.spans)
        print(f"  lint: {'clean' if not issues else str(len(issues)) + ' issue(s)'}")
        for issue in issues:
            print(f"    - {issue}")
    errored = [s for s in tracer.spans if s.status == "ERROR"]
    print("\nerror attribution:")
    for s in errored:
        print(f"  {s.name}: error.type={s.attributes['error.type']} parent={s.parent_id}")
    sample = next(s for s in tracer.spans if s.attributes.get("gen_ai.tool.name") == "lookup_order")
    print(f"\nW3C traceparent forwarded to MCP server in _meta: {sample.attributes['mcp.traceparent.forwarded']}")


if __name__ == "__main__":
    main()
