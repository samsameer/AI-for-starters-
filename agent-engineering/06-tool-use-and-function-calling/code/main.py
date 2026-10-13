from __future__ import annotations

import json
import re
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Callable

ORDERS = {"A-100": {"status": "shipped", "total": 42.0}, "A-101": {"status": "pending", "total": 18.5}}
REFUNDS: list[dict[str, Any]] = []


@dataclass
class Tool:
    name: str
    description: str
    schema: dict[str, Any]
    run: Callable[..., Any]
    effect: str = "read"
    timeout_s: float = 1.0


@dataclass(frozen=True)
class Call:
    call_id: str
    name: str
    args: dict[str, Any]


@dataclass
class Result:
    call_id: str
    ok: bool
    content: str


def check_type(value: Any, expected: str) -> bool:
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    return {"string": str, "boolean": bool, "array": list, "object": dict}[expected] is type(value)


def coerce(value: Any, expected: str) -> Any:
    if isinstance(value, str) and expected in ("integer", "number"):
        try:
            return int(value) if expected == "integer" else float(value)
        except ValueError:
            return value
    return value


def validate(args: dict[str, Any], schema: dict[str, Any], strict: bool) -> tuple[dict[str, Any], list[str]]:
    errors: list[str] = []
    clean: dict[str, Any] = {}
    props = schema["properties"]
    for name in schema.get("required", []):
        if name not in args:
            errors.append(f"missing required field '{name}'")
    for name, value in args.items():
        spec = props.get(name)
        if spec is None:
            if schema.get("additionalProperties") is False:
                errors.append(f"unknown field '{name}' (allowed: {sorted(props)})")
            continue
        if not strict:
            value = coerce(value, spec["type"])
        if not check_type(value, spec["type"]):
            errors.append(f"'{name}' must be {spec['type']}, got {type(value).__name__} {value!r}")
            continue
        if "enum" in spec and value not in spec["enum"]:
            errors.append(f"'{name}'={value!r} not one of {spec['enum']}")
            continue
        if "minimum" in spec and value < spec["minimum"]:
            errors.append(f"'{name}'={value} below minimum {spec['minimum']}")
            continue
        if spec.get("format") == "date":
            try:
                date.fromisoformat(value)
            except ValueError:
                errors.append(f"'{name}'={value!r} is not an ISO date (YYYY-MM-DD)")
                continue
        clean[name] = value
    return clean, errors


def lint_description(tool: Tool) -> list[str]:
    findings: list[str] = []
    text = tool.description.lower()
    if len(tool.description) < 40:
        findings.append("description under 40 chars; say what it does AND when to use it")
    if "use when" not in text and "use for" not in text:
        findings.append("no 'use when' guidance; the model has to guess when to pick it")
    for name, spec in tool.schema["properties"].items():
        if "description" not in spec:
            findings.append(f"parameter '{name}' has no description")
    return findings


@dataclass
class Breaker:
    threshold: int = 2
    failures: dict[str, int] = field(default_factory=dict)

    def is_open(self, name: str) -> bool:
        return self.failures.get(name, 0) >= self.threshold

    def record(self, name: str, ok: bool) -> None:
        self.failures[name] = 0 if ok else self.failures.get(name, 0) + 1


class Registry:
    def __init__(self, strict: bool, approved_effects: set[str]) -> None:
        self.tools: dict[str, Tool] = {}
        self.strict = strict
        self.approved_effects = approved_effects
        self.breaker = Breaker()
        self.pool = ThreadPoolExecutor(max_workers=4)

    def register(self, tool: Tool) -> None:
        self.tools[tool.name] = tool

    def catalog(self, names: list[str] | None = None) -> list[dict[str, Any]]:
        chosen = sorted(names if names is not None else self.tools)
        return [{"name": n, "description": self.tools[n].description, "input_schema": self.tools[n].schema} for n in chosen]

    def search(self, query: str, limit: int = 2) -> list[str]:
        words = set(re.findall(r"[a-z]+", query.lower()))
        scored = []
        for tool in self.tools.values():
            haystack = set(re.findall(r"[a-z]+", (tool.name.replace("_", " ") + " " + tool.description).lower()))
            scored.append((len(words & haystack), tool.name))
        scored.sort(key=lambda pair: (-pair[0], pair[1]))
        return [name for score, name in scored[:limit] if score > 0]

    def preflight(self, call: Call) -> tuple[Tool | None, dict[str, Any], str | None]:
        tool = self.tools.get(call.name)
        if tool is None:
            near = self.search(call.name.replace("_", " "), 1)
            return None, {}, f"unknown tool '{call.name}'" + (f"; did you mean '{near[0]}'?" if near else "")
        if self.breaker.is_open(tool.name):
            return None, {}, f"tool '{tool.name}' is temporarily disabled after repeated failures; try another approach"
        clean, errors = validate(call.args, tool.schema, self.strict)
        if errors:
            return None, {}, "invalid arguments: " + "; ".join(errors)
        if tool.effect not in self.approved_effects:
            return None, {}, f"'{tool.name}' has effect '{tool.effect}' and needs human approval; not executed"
        return tool, clean, None

    def dispatch(self, calls: list[Call]) -> list[Result]:
        futures = {}
        results: dict[str, Result] = {}
        for call in calls:
            tool, clean, problem = self.preflight(call)
            if problem:
                results[call.call_id] = Result(call.call_id, False, problem)
                continue
            futures[call.call_id] = (call, tool, self.pool.submit(tool.run, **clean))
        for call_id, (call, tool, future) in futures.items():
            try:
                value = future.result(timeout=tool.timeout_s)
                results[call_id] = Result(call_id, True, json.dumps(value))
                self.breaker.record(tool.name, True)
            except FutureTimeout:
                results[call_id] = Result(call_id, False, f"'{tool.name}' timed out after {tool.timeout_s}s")
                self.breaker.record(tool.name, False)
            except Exception as error:
                results[call_id] = Result(call_id, False, f"'{tool.name}' failed: {type(error).__name__}: {error}")
                self.breaker.record(tool.name, False)
        return [results[c.call_id] for c in calls]


def get_order(order_id: str) -> dict[str, Any]:
    if order_id not in ORDERS:
        raise KeyError(f"no order {order_id}")
    return {"order_id": order_id, **ORDERS[order_id]}


def list_orders(status: str, limit: int) -> list[str]:
    return [oid for oid, o in ORDERS.items() if o["status"] == status][:limit]


def schedule_callback(day: str, topic: str) -> str:
    return f"callback booked for {day} about {topic}"


def issue_refund(order_id: str, amount: float) -> str:
    REFUNDS.append({"order_id": order_id, "amount": amount})
    return f"refunded {amount} on {order_id}"


def legacy_inventory(sku: str) -> int:
    time.sleep(0.25)
    return 7


def build_registry(strict: bool) -> Registry:
    registry = Registry(strict=strict, approved_effects={"read", "write"})
    obj = {"type": "object", "additionalProperties": False}
    registry.register(Tool("get_order", "Fetch one order by id. Use when the user names a specific order like A-100.",
                           {**obj, "properties": {"order_id": {"type": "string", "description": "Order id, e.g. A-100"}}, "required": ["order_id"]}, get_order))
    registry.register(Tool("list_orders", "List order ids by status. Use for questions about many orders at once.",
                           {**obj, "properties": {"status": {"type": "string", "enum": ["pending", "shipped", "cancelled"], "description": "Order status"},
                                                  "limit": {"type": "integer", "minimum": 1, "description": "Max ids to return"}}, "required": ["status", "limit"]}, list_orders))
    registry.register(Tool("schedule_callback", "Book a phone callback. Use when the user asks to be called back.",
                           {**obj, "properties": {"day": {"type": "string", "format": "date", "description": "ISO date"},
                                                  "topic": {"type": "string", "description": "What the call is about"}}, "required": ["day", "topic"]}, schedule_callback, effect="write"))
    registry.register(Tool("issue_refund", "Refund money. Use only after the order is confirmed eligible.",
                           {**obj, "properties": {"order_id": {"type": "string", "description": "Order id"},
                                                  "amount": {"type": "number", "minimum": 0, "description": "Amount in USD"}}, "required": ["order_id", "amount"]}, issue_refund, effect="irreversible"))
    registry.register(Tool("legacy_inventory", "Stock count.",
                           {**obj, "properties": {"sku": {"type": "string"}}, "required": ["sku"]}, legacy_inventory, timeout_s=0.1))
    return registry


def scripted_model(turn: int) -> list[Call]:
    if turn == 1:
        return [
            Call("call_1", "get_order", {"order_id": "A-100"}),
            Call("call_2", "list_orders", {"status": "in_progress", "limit": "5"}),
            Call("call_3", "schedule_callback", {"day": "next tuesday", "topic": "refund", "urgency": "high"}),
            Call("call_4", "issue_refund", {"order_id": "A-100", "amount": 42.0}),
            Call("call_5", "get_shipment", {"order_id": "A-100"}),
            Call("call_6", "legacy_inventory", {"sku": "SKU-9"}),
        ]
    if turn == 2:
        return [
            Call("call_7", "list_orders", {"status": "pending", "limit": 5}),
            Call("call_8", "schedule_callback", {"day": "2026-10-20", "topic": "refund"}),
            Call("call_9", "legacy_inventory", {"sku": "SKU-9"}),
        ]
    return [Call("call_10", "legacy_inventory", {"sku": "SKU-9"})]


def show(results: list[Result], calls: list[Call]) -> None:
    by_id = {c.call_id: c for c in calls}
    for r in results:
        mark = "ok " if r.ok else "ERR"
        print(f"  {r.call_id:<8} {by_id[r.call_id].name:<18} {mark} {r.content}")


def main() -> None:
    print("=" * 78)
    print("LESSON 06 - Tool use and function calling: a production-shaped registry")
    print("=" * 78)
    registry = build_registry(strict=True)

    print("\nDESCRIPTION LINT (bad descriptions are the top cause of wrong-tool picks)")
    for tool in registry.tools.values():
        for finding in lint_description(tool):
            print(f"  {tool.name}: {finding}")

    print("\nTOOL SEARCH (load only relevant schemas into context)")
    for query in ("refund an order", "call me back tomorrow"):
        hits = registry.search(query)
        size = len(json.dumps(registry.catalog(hits)))
        print(f"  {query!r:<26} -> {hits}  ({size} chars vs {len(json.dumps(registry.catalog()))} for all tools)")

    for turn in (1, 2, 3):
        calls = scripted_model(turn)
        print(f"\nTURN {turn}: model emits {len(calls)} call(s) in one message (strict mode)")
        show(registry.dispatch(calls), calls)

    print("\nSTRICT vs LENIENT on the same malformed call")
    bad = [Call("call_x", "list_orders", {"status": "pending", "limit": "5"})]
    for strict in (True, False):
        print(f"  strict={strict}:")
        show(build_registry(strict).dispatch(bad), bad)

    print(f"\nside effects actually performed: refunds={REFUNDS}")
    print("takeaways:")
    print("  - every failure returns a readable observation keyed by call id; nothing crashes the loop")
    print("  - irreversible tools are blocked by policy, not by hoping the model behaves")
    print("  - the circuit breaker stops a slow legacy tool from eating the turn budget")
    registry.pool.shutdown(wait=True)


if __name__ == "__main__":
    main()
