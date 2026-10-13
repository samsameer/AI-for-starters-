from __future__ import annotations

import ast
import hashlib
import json
import operator
from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class Tool:
    name: str
    description: str
    input_schema: dict[str, Any]
    run: Callable[..., str]


def tool_result(tool_use_id: str, content: str, is_error: bool) -> dict[str, Any]:
    return {"type": "tool_result", "tool_use_id": tool_use_id, "content": content, "is_error": is_error}


class ToolRegistry:
    def __init__(self) -> None:
        self.tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        self.tools[tool.name] = tool

    def catalog(self) -> list[dict[str, Any]]:
        ordered = sorted(self.tools.values(), key=lambda t: t.name)
        return [{"name": t.name, "description": t.description, "input_schema": t.input_schema} for t in ordered]

    def execute(self, block: dict[str, Any]) -> dict[str, Any]:
        tool = self.tools.get(block["name"])
        if tool is None:
            return tool_result(block["id"], f"unknown tool {block['name']!r}; available: {sorted(self.tools)}", True)
        missing = [k for k in tool.input_schema.get("required", []) if k not in block["input"]]
        if missing:
            return tool_result(block["id"], f"missing required field(s) {missing} for {tool.name}", True)
        try:
            return tool_result(block["id"], tool.run(**block["input"]), False)
        except Exception as error:
            return tool_result(block["id"], f"{type(error).__name__}: {error}", True)


SAFE_OPERATORS: dict[type, Callable[[float, float], float]] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
}


def safe_arithmetic(node: ast.AST) -> float:
    if isinstance(node, ast.Expression):
        return safe_arithmetic(node.body)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return float(node.value)
    if isinstance(node, ast.BinOp) and type(node.op) in SAFE_OPERATORS:
        return SAFE_OPERATORS[type(node.op)](safe_arithmetic(node.left), safe_arithmetic(node.right))
    raise ValueError("only + - * / on numbers is allowed")


def calculator(expression: str) -> str:
    return f"{safe_arithmetic(ast.parse(expression, mode='eval')):g}"


class KeyValueStore:
    def __init__(self) -> None:
        self.data: dict[str, str] = {}

    def get(self, key: str) -> str:
        return self.data.get(key, f"missing:{key}")

    def put(self, key: str, value: str) -> str:
        self.data[key] = value
        return f"stored {key}={value}"


def tool_use(block_id: str, name: str, payload: dict[str, Any]) -> dict[str, Any]:
    return {"type": "tool_use", "id": block_id, "name": name, "input": payload}


def thinking(signature: str) -> dict[str, Any]:
    return {"type": "thinking", "thinking": "", "signature": signature}


class ScriptedModel:
    def __init__(self, responses: list[dict[str, Any]]) -> None:
        self.responses = responses
        self.calls = 0

    def create(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> dict[str, Any]:
        self.calls += 1
        if self.calls > len(self.responses):
            return {"stop_reason": "end_turn", "content": [{"type": "text", "text": "nothing left to do"}]}
        return self.responses[self.calls - 1]


def fingerprint(message: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(message, sort_keys=True).encode()).hexdigest()[:12]


@dataclass
class AppendOnlyGuard:
    seen: list[str] = field(default_factory=list)

    def check(self, messages: list[dict[str, Any]]) -> None:
        current = [fingerprint(m) for m in messages]
        for index, old in enumerate(self.seen):
            if index >= len(current) or current[index] != old:
                raise RuntimeError(f"history edited at message {index}: thinking and cache would be invalidated")
        self.seen = current


@dataclass
class RunReport:
    final: str
    stop: str
    turns: int
    tool_calls: int
    tool_errors: int
    messages: list[dict[str, Any]]


class AgentLoop:
    def __init__(self, model: ScriptedModel, tools: ToolRegistry, max_turns: int = 8,
                 history_hook: Callable[[list[dict[str, Any]]], None] | None = None) -> None:
        self.model = model
        self.tools = tools
        self.max_turns = max_turns
        self.history_hook = history_hook

    def run(self, user_text: str) -> RunReport:
        messages: list[dict[str, Any]] = [{"role": "user", "content": user_text}]
        guard = AppendOnlyGuard()
        calls = errors = 0
        for turn in range(1, self.max_turns + 1):
            if self.history_hook:
                self.history_hook(messages)
            guard.check(messages)
            response = self.model.create(messages=messages, tools=self.tools.catalog())
            messages.append({"role": "assistant", "content": response["content"]})
            stop = response["stop_reason"]
            if stop == "tool_use":
                results = [self.tools.execute(b) for b in response["content"] if b["type"] == "tool_use"]
                calls += len(results)
                errors += sum(1 for r in results if r["is_error"])
                messages.append({"role": "user", "content": results})
                continue
            text = " ".join(b["text"] for b in response["content"] if b["type"] == "text")
            if stop == "end_turn":
                return RunReport(text, "end_turn", turn, calls, errors, messages)
            return RunReport(f"stopped early: {stop}", stop, turn, calls, errors, messages)
        return RunReport("turn budget exhausted", "max_turns", self.max_turns, calls, errors, messages)


def build_registry() -> ToolRegistry:
    store = KeyValueStore()
    registry = ToolRegistry()
    registry.register(Tool("calculator", "Evaluate + - * / arithmetic. Use for any math.",
                           {"type": "object", "properties": {"expression": {"type": "string"}}, "required": ["expression"]},
                           calculator))
    registry.register(Tool("kv_put", "Save a named value for later steps.",
                           {"type": "object", "properties": {"key": {"type": "string"}, "value": {"type": "string"}},
                            "required": ["key", "value"]}, store.put))
    registry.register(Tool("kv_get", "Read a value saved earlier with kv_put.",
                           {"type": "object", "properties": {"key": {"type": "string"}}, "required": ["key"]}, store.get))
    return registry


def build_script() -> list[dict[str, Any]]:
    return [
        {"stop_reason": "tool_use", "content": [
            thinking("sig-a"),
            tool_use("toolu_01", "kv_put", {"key": "base", "value": "120"}),
            tool_use("toolu_02", "calculator", {"expression": "120 * 0.15"}),
        ]},
        {"stop_reason": "tool_use", "content": [
            thinking("sig-b"),
            tool_use("toolu_03", "calculator", {"expr": "120 + 18"}),
        ]},
        {"stop_reason": "tool_use", "content": [
            thinking("sig-c"),
            tool_use("toolu_04", "calculator", {"expression": "120 + 18"}),
        ]},
        {"stop_reason": "end_turn", "content": [
            thinking("sig-d"),
            {"type": "text", "text": "Total with 15% tax is 138."},
        ]},
    ]


def print_trace(messages: list[dict[str, Any]]) -> None:
    for index, message in enumerate(messages):
        content = message["content"]
        if isinstance(content, str):
            print(f"  [{index:02d} {message['role']:>9}] {content}")
            continue
        for block in content:
            kind = block["type"]
            if kind == "thinking":
                print(f"  [{index:02d} {message['role']:>9}] thinking (opaque, signature={block['signature']})")
            elif kind == "tool_use":
                print(f"  [{index:02d} {message['role']:>9}] tool_use {block['id']} {block['name']}({block['input']})")
            elif kind == "tool_result":
                flag = "ERROR" if block["is_error"] else "ok"
                print(f"  [{index:02d} {message['role']:>9}] tool_result {block['tool_use_id']} {flag}: {block['content']}")
            elif kind == "text":
                print(f"  [{index:02d} {message['role']:>9}] text: {block['text']}")


def trim_old_tool_results(messages: list[dict[str, Any]]) -> None:
    if len(messages) > 4 and isinstance(messages[2]["content"], list):
        messages[2]["content"] = [dict(b, content="[trimmed]") for b in messages[2]["content"]]


def main() -> None:
    print("=" * 72)
    print("LESSON 01 - THE AGENT LOOP (Oct 2026 shape: blocks, ids, append-only)")
    print("=" * 72)
    agent = AgentLoop(ScriptedModel(build_script()), build_registry(), max_turns=6)
    report = agent.run("What is 120 plus 15% tax? Save the base price.")
    print_trace(report.messages)
    print()
    print(f"final answer : {report.final}")
    print(f"stop reason  : {report.stop}")
    print(f"turns        : {report.turns}  tool calls: {report.tool_calls}  tool errors recovered: {report.tool_errors}")

    print("\nbudget demo: same script, max_turns=2")
    short = AgentLoop(ScriptedModel(build_script()), build_registry(), max_turns=2).run("same task")
    print(f"  stop={short.stop} final={short.final!r}")

    print("\nharness bug demo: a hook that trims old tool results in place")
    broken = AgentLoop(ScriptedModel(build_script()), build_registry(), history_hook=trim_old_tool_results)
    try:
        broken.run("same task")
    except RuntimeError as error:
        print(f"  guard tripped -> {error}")
    print("\nlesson: keep the transcript append-only; clear or compact with API features, not by editing history.")


if __name__ == "__main__":
    main()
