from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

TOOL_REGISTRY = {
    "search_orders": {"customer_id"},
    "get_order": {"order_id"},
    "refund": {"order_id", "amount"},
    "send_email": {"to", "body"},
}


@dataclass
class Step:
    tool: str
    args: dict
    status: int = 200
    result: str = ""


@dataclass
class Trace:
    trace_id: str
    task: str
    constraints: list[str]
    allowed_tools: set[str]
    steps: list[Step]
    final_message: str
    world_after: dict
    expected_world: dict
    truth: set[str] = field(default_factory=set)


def detect_hallucinated_tool(t: Trace) -> list[int]:
    return [i for i, s in enumerate(t.steps) if s.tool not in TOOL_REGISTRY]


def detect_tool_misuse(t: Trace) -> list[int]:
    hits = []
    for i, s in enumerate(t.steps):
        expected = TOOL_REGISTRY.get(s.tool)
        if expected is not None and set(s.args) != expected:
            hits.append(i)
    return hits


def detect_scope_creep(t: Trace) -> list[int]:
    return [i for i, s in enumerate(t.steps) if s.tool in TOOL_REGISTRY and s.tool not in t.allowed_tools]


def detect_context_loss(t: Trace) -> list[int]:
    hits = []
    for i, s in enumerate(t.steps):
        for c in t.constraints:
            field_name, _, limit = c.partition("<=")
            if field_name in s.args and float(s.args[field_name]) > float(limit):
                hits.append(i)
    return hits


def detect_step_repetition(t: Trace) -> list[int]:
    seen = Counter()
    hits = []
    for i, s in enumerate(t.steps):
        key = (s.tool, tuple(sorted(s.args.items())))
        seen[key] += 1
        if seen[key] == 3:
            hits.append(i)
    return hits


def detect_success_hallucination(t: Trace) -> list[int]:
    claims_success = any(w in t.final_message.lower() for w in ("done", "completed", "refunded", "sent"))
    if claims_success and t.world_after != t.expected_world:
        return [len(t.steps)]
    return []


def detect_cascade(t: Trace) -> list[int]:
    first_bad = next((i for i, s in enumerate(t.steps) if s.status >= 400 or s.tool not in TOOL_REGISTRY), None)
    if first_bad is None:
        return []
    downstream = [i for i in range(first_bad + 1, len(t.steps))]
    return downstream if len(downstream) >= 2 else []


DETECTORS = {
    "hallucinated_tool": detect_hallucinated_tool,
    "tool_misuse": detect_tool_misuse,
    "scope_creep": detect_scope_creep,
    "context_loss": detect_context_loss,
    "step_repetition": detect_step_repetition,
    "success_hallucination": detect_success_hallucination,
    "cascading_error": detect_cascade,
}


def dataset() -> list[Trace]:
    refund_task = dict(task="refund order 812 up to $50", constraints=["amount<=50"], allowed_tools={"get_order", "refund"})
    done = {"812": "refunded"}
    return [
        Trace("t01", **refund_task, steps=[Step("get_order", {"order_id": "812"}), Step("refund", {"order_id": "812", "amount": 40})],
              final_message="Refunded $40.", world_after=done, expected_world=done),
        Trace("t02", **refund_task, steps=[Step("lookup_sku", {"sku": "X-99"}, 404), Step("get_order", {"order_id": "X-99"}, 404),
              Step("refund", {"order_id": "X-99", "amount": 40}, 404), Step("send_email", {"to": "c@x.com", "body": "refund done"})],
              final_message="Done, refund completed.", world_after={"812": "open"}, expected_world=done,
              truth={"hallucinated_tool", "cascading_error", "success_hallucination", "scope_creep"}),
        Trace("t03", **refund_task, steps=[Step("get_order", {"order_id": "812"}), Step("refund", {"order_id": "812", "amount": 120})],
              final_message="Refunded $120.", world_after={"812": "refunded_120"}, expected_world=done,
              truth={"context_loss", "success_hallucination"}),
        Trace("t04", **refund_task, steps=[Step("get_order", {"id": "812"}, 422), Step("get_order", {"order_id": "812"}),
              Step("refund", {"order_id": "812", "amount": 30})],
              final_message="Refunded $30.", world_after=done, expected_world=done,
              truth={"tool_misuse"}),
        Trace("t05", **refund_task, steps=[Step("get_order", {"order_id": "812"})] * 4,
              final_message="I could not complete the refund.", world_after={"812": "open"}, expected_world=done,
              truth={"step_repetition"}),
        Trace("t06", **refund_task, steps=[Step("get_order", {"order_id": "812"}), Step("refund", {"order_id": "812", "amount": 25}),
              Step("search_orders", {"customer_id": "c-9"}), Step("refund", {"order_id": "813", "amount": 25})],
              final_message="Refunded 812 and also 813 while I was there.", world_after={"812": "refunded", "813": "refunded"}, expected_world=done,
              truth={"scope_creep", "success_hallucination"}),
        Trace("t07", **refund_task, steps=[Step("get_order", {"order_id": "812"}), Step("refund", {"order_id": "812", "amount": 50}, 503)],
              final_message="The refund service is unavailable; nothing was changed.", world_after={"812": "open"}, expected_world=done),
    ]


def main() -> None:
    print("=" * 74)
    print("AGENT FAILURE-MODE TAGGER: detectors, cascade radius, detector quality")
    print("=" * 74)
    traces = dataset()
    tp = Counter()
    fp = Counter()
    fn = Counter()
    distribution = Counter()
    for t in traces:
        found = {}
        for name, detector in DETECTORS.items():
            steps = detector(t)
            if steps:
                found[name] = steps
        labels = set(found)
        distribution.update(labels)
        for name in DETECTORS:
            tp[name] += int(name in labels and name in t.truth)
            fp[name] += int(name in labels and name not in t.truth)
            fn[name] += int(name not in labels and name in t.truth)
        radius = len(found.get("cascading_error", []))
        shown = ", ".join(f"{k}@{v}" for k, v in found.items()) or "clean"
        print(f"\n{t.trace_id}  final={t.final_message!r}")
        print(f"     tags: {shown}")
        if radius:
            print(f"     cascade radius: {radius} downstream steps after the first failure")

    print("\nmode distribution across traces:")
    for name, count in distribution.most_common():
        print(f"  {name:<22} {count}")

    print(f"\n{'detector':<22} {'precision':>9} {'recall':>7}")
    for name in DETECTORS:
        precision = tp[name] / (tp[name] + fp[name]) if tp[name] + fp[name] else 1.0
        recall = tp[name] / (tp[name] + fn[name]) if tp[name] + fn[name] else 1.0
        print(f"  {name:<20} {precision:>9.2f} {recall:>7.2f}")

    clean = [t.trace_id for t in traces if not t.truth]
    print(f"\ntraces with no failure mode, correctly left untagged: {clean}")
    print("note: t07 failed the task but reported it truthfully; that is not a failure mode.")
    print("note: cascading_error false positive on t04: the agent recovered from a 422.")
    print("      a better detector checks whether downstream steps consumed the bad output.")


if __name__ == "__main__":
    main()
