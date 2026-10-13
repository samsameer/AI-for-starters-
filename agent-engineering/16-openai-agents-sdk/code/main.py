from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable


class InputGuardrailTripwireTriggered(Exception):
    pass


class OutputGuardrailTripwireTriggered(Exception):
    pass


class MaxHandoffsExceeded(Exception):
    pass


@dataclass
class FunctionTool:
    name: str
    fn: Callable[..., str]
    needs_approval: bool = False
    guardrail: Callable[[dict[str, Any]], str | None] | None = None


@dataclass
class Agent:
    name: str
    instructions: str
    tools: list[FunctionTool] = field(default_factory=list)
    handoffs: list["Agent"] = field(default_factory=list)
    input_guardrails: list[Callable[[str], str | None]] = field(default_factory=list)
    output_guardrails: list[Callable[[str], str | None]] = field(default_factory=list)

    def tool_names(self) -> list[str]:
        return [t.name for t in self.tools] + [f"transfer_to_{h.name}" for h in self.handoffs]


@dataclass
class Span:
    kind: str
    name: str
    children: list["Span"] = field(default_factory=list)

    def render(self, depth: int = 0) -> list[str]:
        lines = [f"{'  ' * depth}{self.kind}:{self.name}"]
        for child in self.children:
            lines.extend(child.render(depth + 1))
        return lines


@dataclass
class Session:
    items: dict[str, list[str]] = field(default_factory=dict)

    def get(self, session_id: str) -> list[str]:
        return self.items.setdefault(session_id, [])


@dataclass
class RunState:
    agent: Agent
    history: list[str]
    pending_tool: FunctionTool
    pending_args: dict[str, Any]
    hops: int
    trace: Span
    approved: bool | None = None


@dataclass
class RunResult:
    final_output: str | None
    last_agent: str
    trace: Span
    interruption: RunState | None = None
    tokens_spent: int = 0


def fake_model(agent: Agent, history: list[str]) -> tuple[str, str, dict[str, Any]]:
    last = history[-1].lower()
    if agent.name == "triage":
        if "refund" in last or "invoice" in last:
            return "call", "transfer_to_billing", {}
        if "error" in last or "crash" in last:
            return "call", "transfer_to_support", {}
        return "final", "I can help with billing or support questions.", {}
    if agent.name == "billing":
        if not any(item.startswith("tool:") for item in history):
            amount = int(re.search(r"\$(\d+)", last).group(1)) if "$" in last else 20
            return "call", "issue_refund", {"amount": amount}
        return "final", f"Done. {history[-1].removeprefix('tool:')}", {}
    if agent.name == "support":
        if "billing" in last:
            return "call", "transfer_to_triage", {}
        return "final", "Please update to 4.2; the crash is fixed there.", {}
    return "final", "ok", {}


class Runner:
    def __init__(self, max_handoffs: int = 3, blocking_guardrails: bool = True) -> None:
        self.max_handoffs = max_handoffs
        self.blocking_guardrails = blocking_guardrails

    def run(self, agent: Agent, text: str, session: Session | None = None, session_id: str = "default") -> RunResult:
        history = session.get(session_id) if session else []
        history.append(f"user:{text}")
        trace = Span("trace", "agent_run")
        tokens = 0
        for check in agent.input_guardrails:
            reason = check(text)
            trace.children.append(Span("guardrail", f"input:{check.__name__}"))
            if reason:
                tokens += 0 if self.blocking_guardrails else 400
                raise InputGuardrailTripwireTriggered(f"{reason} (wasted tokens={tokens})")
        return self._loop(agent, history, 0, trace, tokens)

    def resume(self, state: RunState) -> RunResult:
        tool_span = Span("function", state.pending_tool.name)
        state.trace.children[-1].children.append(tool_span)
        if state.approved:
            state.history.append("tool:" + state.pending_tool.fn(**state.pending_args))
        else:
            state.history.append("tool:refund rejected by a human reviewer")
        return self._loop(state.agent, state.history, state.hops, state.trace, 0)

    def _loop(self, agent: Agent, history: list[str], hops: int, trace: Span, tokens: int) -> RunResult:
        agent_span = Span("agent", agent.name)
        trace.children.append(agent_span)
        for _ in range(8):
            agent_span.children.append(Span("generation", f"tools={agent.tool_names()}"))
            tokens += 100
            kind, value, args = fake_model(agent, history)
            if kind == "final":
                for check in agent.output_guardrails:
                    agent_span.children.append(Span("guardrail", f"output:{check.__name__}"))
                    if reason := check(value):
                        raise OutputGuardrailTripwireTriggered(reason)
                history.append(f"{agent.name}:{value}")
                return RunResult(value, agent.name, trace, tokens_spent=tokens)
            if value.startswith("transfer_to_"):
                hops += 1
                if hops > self.max_handoffs:
                    raise MaxHandoffsExceeded(f"{hops} handoffs, last {agent.name} -> {value}")
                target = next(h for h in agent.handoffs if f"transfer_to_{h.name}" == value)
                agent_span.children.append(Span("handoff", f"{agent.name}->{target.name}"))
                agent = target
                agent_span = Span("agent", agent.name)
                trace.children.append(agent_span)
                continue
            selected = next(t for t in agent.tools if t.name == value)
            if selected.guardrail and (reason := selected.guardrail(args)):
                agent_span.children.append(Span("guardrail", f"tool:{selected.name} rejected"))
                history.append(f"tool:blocked: {reason}")
                continue
            if selected.needs_approval:
                state = RunState(agent, history, selected, args, hops, trace)
                return RunResult(None, agent.name, trace, interruption=state, tokens_spent=tokens)
            agent_span.children.append(Span("function", selected.name))
            history.append("tool:" + selected.fn(**args))
        raise RuntimeError("max turns exceeded")


def no_card_numbers(text: str) -> str | None:
    return "card number in input" if re.search(r"\b\d{4}[ -]?\d{4}[ -]?\d{4}[ -]?\d{4}\b", text) else None


def no_internal_urls(text: str) -> str | None:
    return "internal URL in output" if "intranet." in text else None


def refund_cap(args: dict[str, Any]) -> str | None:
    return "refund above $500 cap" if args.get("amount", 0) > 500 else None


def build_agents() -> Agent:
    refund = FunctionTool("issue_refund", lambda amount: f"refunded ${amount}", needs_approval=True, guardrail=refund_cap)
    triage = Agent("triage", "Route the user.", input_guardrails=[no_card_numbers])
    billing = Agent("billing", "Handle money.", tools=[refund], output_guardrails=[no_internal_urls])
    support = Agent("support", "Fix product issues.", output_guardrails=[no_internal_urls])
    triage.handoffs = [billing, support]
    support.handoffs = [triage]
    billing.handoffs = [triage]
    return triage


def main() -> None:
    triage = build_agents()
    session = Session()
    runner = Runner()

    print("1. handoff to support, answered directly")
    result = runner.run(triage, "The app shows an error on launch", session, "u1")
    print(f"  final={result.final_output!r} last_agent={result.last_agent}")

    print("\n2. handoff to billing, tool needs approval: run pauses with a resumable RunState")
    result = runner.run(triage, "Please refund $40 for invoice 118", session, "u2")
    print(f"  interrupted={result.interruption is not None} pending={result.interruption.pending_tool.name} args={result.interruption.pending_args}")
    result.interruption.approved = True
    resumed = runner.resume(result.interruption)
    print(f"  after approval final={resumed.final_output!r}")
    print("  trace:")
    for line in resumed.trace.render(2):
        print(line)

    print("\n3. tool guardrail blocks an oversized refund before anyone is asked")
    blocked = runner.run(triage, "refund $900 on invoice 7", session, "u3")
    print(f"  final={blocked.final_output!r}")

    print("\n4. input guardrail: blocking vs parallel")
    for blocking in (True, False):
        try:
            Runner(blocking_guardrails=blocking).run(triage, "refund 4111 1111 1111 1111 please")
        except InputGuardrailTripwireTriggered as trip:
            print(f"  blocking={blocking!s:<5} tripwire: {trip}")

    print("\n5. handoff loop guard")
    try:
        Runner(max_handoffs=2).run(triage, "crash after billing change")
    except MaxHandoffsExceeded as stop:
        print(f"  stopped: {stop}")

    print(f"\n6. session memory: u2 has {len(session.get('u2'))} items -> {session.get('u2')}")
    print("\nhandoffs are tools, guardrails are tripwires, approvals are resumable state.")


if __name__ == "__main__":
    main()
