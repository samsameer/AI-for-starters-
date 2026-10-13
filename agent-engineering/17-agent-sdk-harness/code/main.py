from __future__ import annotations

import hashlib
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Callable

FILES = {
    "src/auth.py": "def login(user):\n    return token(user)\n" * 6,
    "src/billing.py": "def charge(card, amount):\n    return gateway(card, amount)\n" * 6,
    "src/search.py": "def search(q):\n    return index.lookup(q)\n" * 6,
    "tests/test_auth.py": "def test_login():\n    assert login('a')\n",
    "tests/test_search.py": "def test_search():\n    assert search('x') == []\n",
}


@dataclass
class ToolCall:
    name: str
    args: dict[str, Any]


@dataclass
class Hooks:
    handlers: dict[str, list[Callable[..., str | None]]] = field(default_factory=dict)
    log: list[str] = field(default_factory=list)

    def on(self, event: str, fn: Callable[..., str | None]) -> None:
        self.handlers.setdefault(event, []).append(fn)

    def fire(self, event: str, **payload: Any) -> str | None:
        self.log.append(event)
        for fn in self.handlers.get(event, []):
            verdict = fn(**payload)
            if verdict:
                return verdict
        return None


class ToolRegistry:
    def __init__(self, fs: dict[str, str]) -> None:
        self.fs = fs
        self.tools: dict[str, Callable[..., str]] = {
            "list_dir": lambda path: "\n".join(sorted(p for p in fs if p.startswith(path))),
            "read_file": lambda path: fs.get(path, f"error: {path} not found"),
            "write_file": self.write_file,
            "grep": lambda pattern: "\n".join(p for p, text in sorted(fs.items()) if pattern in text),
        }

    def write_file(self, path: str, content: str) -> str:
        self.fs[path] = content
        return f"wrote {len(content)} chars to {path}"


@dataclass
class PermissionPolicy:
    allow: set[str]
    ask: set[str]
    approvals: dict[str, bool] = field(default_factory=dict)

    def decide(self, call: ToolCall) -> str:
        if call.name in self.allow:
            return "allow"
        if call.name in self.ask:
            return "allow" if self.approvals.get(call.name, False) else "deny"
        return "deny"


@dataclass
class SessionStore:
    rows: dict[str, list[str]] = field(default_factory=dict)

    def append(self, key: str, entry: str) -> None:
        self.rows.setdefault(key, []).append(entry)

    def load(self, key: str) -> list[str]:
        return list(self.rows.get(key, []))

    def list_sessions(self) -> list[str]:
        return sorted(k for k in self.rows if "/" not in k)

    def list_subkeys(self, key: str) -> list[str]:
        return sorted(k for k in self.rows if k.startswith(key + "/"))

    def fork(self, key: str, new_key: str, at_entry: int) -> None:
        self.rows[new_key] = self.rows[key][:at_entry]

    def delete(self, key: str) -> int:
        doomed = [key] + self.list_subkeys(key)
        for k in doomed:
            self.rows.pop(k, None)
        return len(doomed)


def traceparent(trace_id: str, span_name: str) -> str:
    span_id = hashlib.sha256(span_name.encode()).hexdigest()[:16]
    return f"00-{trace_id}-{span_id}-01"


@dataclass
class Harness:
    name: str
    registry: ToolRegistry
    policy: PermissionPolicy
    hooks: Hooks
    store: SessionStore
    trace_id: str
    context: list[str] = field(default_factory=list)
    context_budget: int = 900

    def call(self, call: ToolCall) -> str:
        blocked = self.hooks.fire("pre_tool_use", agent=self.name, call=call)
        decision = "deny" if blocked else self.policy.decide(call)
        if decision == "deny":
            result = f"denied: {blocked or 'policy'}"
        else:
            result = self.registry.tools[call.name](**call.args)
        self.hooks.fire("post_tool_use", agent=self.name, call=call)
        self.remember(f"{call.name}({call.args}) -> {result}")
        return result

    def remember(self, entry: str) -> None:
        self.context.append(entry)
        self.store.append(self.name, entry)
        if self.size() > self.context_budget:
            self.hooks.fire("pre_compact", agent=self.name)
            kept = self.context[-2:]
            self.context = [f"summary of {len(self.context) - 2} earlier entries"] + kept

    def size(self) -> int:
        return sum(len(entry) for entry in self.context)


def subagent_task(parent: Harness, module: str) -> tuple[str, str, int]:
    child = Harness(
        name=f"{parent.name}/find-tests-{module}",
        registry=parent.registry,
        policy=PermissionPolicy(allow={"read_file", "list_dir", "grep"}, ask=set()),
        hooks=parent.hooks,
        store=parent.store,
        trace_id=parent.trace_id,
    )
    child.remember(f"traceparent={traceparent(parent.trace_id, child.name)}")
    child.call(ToolCall("read_file", {"path": f"src/{module}.py"}))
    hits = child.call(ToolCall("list_dir", {"path": f"tests/test_{module}"}))
    child.call(ToolCall("write_file", {"path": f"tests/test_{module}.py", "content": "x"}))
    summary = f"{module}: {'has tests' if hits else 'NO TESTS'}"
    parent.hooks.fire("subagent_stop", agent=child.name)
    return module, summary, child.size()


def block_outside_workspace(agent: str, call: ToolCall) -> str | None:
    path = call.args.get("path", "")
    return "path outside workspace" if call.name == "write_file" and not path.startswith(("src/", "tests/")) else None


def main() -> None:
    hooks = Hooks()
    hooks.on("pre_tool_use", block_outside_workspace)
    hooks.on("user_prompt_submit", lambda prompt: "secrets in prompt" if "API_KEY=" in prompt else None)
    store = SessionStore()
    fs = dict(FILES)
    lead = Harness("sess-1", ToolRegistry(fs), PermissionPolicy({"read_file", "list_dir", "grep"}, {"write_file"}), hooks, store, trace_id="4bf92f3577b34da6a3ce929d0e0e4736")

    hooks.fire("session_start", agent=lead.name)
    prompt = "Which modules lack tests?"
    print(f"1. prompt check: {hooks.fire('user_prompt_submit', prompt=prompt) or 'ok'}; blocked variant: {hooks.fire('user_prompt_submit', prompt='use API_KEY=sk-1')}")

    modules = ["auth", "billing", "search"]
    with ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(lambda m: subagent_task(lead, m), modules))
    for module, summary, child_size in results:
        lead.remember(summary)
        print(f"2. subagent {module:<8} child context={child_size:>4} chars, returned {summary!r}")
    print(f"   lead context with isolation = {lead.size()} chars")

    inline = Harness("inline", ToolRegistry(dict(FILES)), lead.policy, Hooks(), SessionStore(), lead.trace_id, context_budget=10_000)
    for module in modules:
        inline.call(ToolCall("read_file", {"path": f"src/{module}.py"}))
        inline.call(ToolCall("list_dir", {"path": f"tests/test_{module}"}))
    print(f"   lead context doing it inline = {inline.size()} chars")

    print("\n3. permissions and hooks")
    print(f"   write without approval: {lead.call(ToolCall('write_file', {'path': 'tests/test_billing.py', 'content': 'def test_charge(): ...'}))}")
    lead.policy.approvals["write_file"] = True
    print(f"   write after approval:    {lead.call(ToolCall('write_file', {'path': 'tests/test_billing.py', 'content': 'def test_charge(): ...'}))}")
    print(f"   write outside workspace: {lead.call(ToolCall('write_file', {'path': '/etc/hosts', 'content': 'x'}))}")
    print(f"   subagent write attempts were denied by its read-only policy: {fs['tests/test_auth.py'] == FILES['tests/test_auth.py']}")

    print("\n4. compaction keeps the lead under budget")
    for _ in range(6):
        lead.call(ToolCall("read_file", {"path": "src/billing.py"}))
    print(f"   lead context={lead.size()} chars, first entry={lead.context[0]!r}")

    hooks.fire("stop", agent=lead.name)
    hooks.fire("session_end", agent=lead.name)
    print("\n5. session store")
    print(f"   sessions={store.list_sessions()} subkeys={len(store.list_subkeys('sess-1'))}")
    store.fork("sess-1", "sess-1-fork", at_entry=3)
    print(f"   fork at entry 3 -> {len(store.load('sess-1-fork'))} entries, original keeps {len(store.load('sess-1'))}")
    print(f"   delete sess-1 removed {store.delete('sess-1')} keys (cascade); left={store.list_sessions()}")
    child_tp = traceparent(lead.trace_id, "sess-1/find-tests-auth")
    print(f"\n6. one trace across processes: child traceparent {child_tp}")
    counts = {e: hooks.log.count(e) for e in dict.fromkeys(hooks.log)}
    print(f"   hook events: {counts}")
    print("\nthe harness, not the model, owns tools, permissions, isolation, compaction and persistence.")


if __name__ == "__main__":
    main()
