from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass, field

DIMENSIONS = 256
FUNCTIONAL = {"lives_in", "works_at", "manager_is"}
PATTERNS = [
    (re.compile(r"\b([A-Z][a-z]+) (?:lives|moved) (?:in|to) ([A-Z][a-z]+)"), "lives_in", 0.6),
    (re.compile(r"\b([A-Z][a-z]+) (?:works|started) at ([A-Z][a-z]+)"), "works_at", 0.7),
    (re.compile(r"\b([A-Z][a-z]+)'s manager is ([A-Z][a-z]+)"), "manager_is", 0.8),
    (re.compile(r"\b([A-Z][a-z]+) is allergic to (\w+)"), "allergic_to", 1.0),
]


def words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


def embed(text: str) -> list[float]:
    vector = [0.0] * DIMENSIONS
    grams = words(text) + [w[i:i + 3] for w in words(text) for i in range(max(1, len(w) - 2))]
    for gram in grams:
        digest = hashlib.blake2b(gram.encode(), digest_size=4).digest()
        index = int.from_bytes(digest, "big") % DIMENSIONS
        vector[index] += 1.0 if len(gram) > 3 else 0.5
    norm = math.sqrt(sum(v * v for v in vector)) or 1.0
    return [v / norm for v in vector]


def cosine(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


@dataclass
class Memory:
    memory_id: str
    text: str
    user: str
    scope: str
    day: int
    importance: float
    vector: list[float] = field(repr=False, default_factory=list)


@dataclass
class Edge:
    subject: str
    relation: str
    obj: str
    valid_from: int
    valid_to: int | None
    source: str


class HybridMemory:
    def __init__(self) -> None:
        self.memories: list[Memory] = []
        self.kv: dict[tuple[str, str, str], str] = {}
        self.edges: list[Edge] = []
        self.log: list[str] = []

    def add(self, text: str, user: str, day: int, scope: str = "user") -> None:
        memory_id = f"m{len(self.memories) + 1:02d}"
        facts = [(m.group(1), rel, m.group(2), imp) for pattern, rel, imp in PATTERNS for m in pattern.finditer(text)]
        importance = max([imp for *_, imp in facts], default=0.3)
        self.memories.append(Memory(memory_id, text, user, scope, day, importance, embed(text)))
        for subject, relation, obj, _ in facts:
            subject, obj = subject.lower(), obj.lower()
            if relation in FUNCTIONAL:
                for edge in self.edges:
                    if edge.subject == subject and edge.relation == relation and edge.valid_to is None and edge.obj != obj:
                        edge.valid_to = day
                        self.log.append(f"  day {day}: closed ({subject} {relation} {edge.obj}) valid {edge.valid_from}..{day}, kept for history")
            self.edges.append(Edge(subject, relation, obj, day, None, memory_id))
            self.kv[(user, subject, relation)] = obj

    def visible(self, user: str, scopes: set[str]) -> list[Memory]:
        return [m for m in self.memories if m.user == user and m.scope in scopes]

    def vector_search(self, query: str, user: str, scopes: set[str], k: int = 3) -> list[tuple[float, Memory]]:
        q = embed(query)
        scored = [(round(cosine(q, m.vector), 3), m) for m in self.visible(user, scopes)]
        return sorted(scored, key=lambda pair: (-pair[0], pair[1].memory_id))[:k]

    def kv_lookup(self, user: str, subject: str, relation: str) -> str | None:
        return self.kv.get((user, subject, relation))

    def graph_neighbors(self, entity: str, as_of: int | None = None) -> list[Edge]:
        def live(edge: Edge) -> bool:
            if as_of is None:
                return edge.valid_to is None
            return edge.valid_from <= as_of and (edge.valid_to is None or as_of < edge.valid_to)
        return [e for e in self.edges if live(e) and entity in (e.subject, e.obj)]

    def coworkers(self, person: str) -> list[str]:
        companies = [e.obj for e in self.graph_neighbors(person) if e.subject == person and e.relation == "works_at"]
        return sorted({e.subject for c in companies for e in self.graph_neighbors(c) if e.relation == "works_at" and e.subject != person})

    def fused(self, query: str, user: str, today: int, weights: dict[str, float], scopes: set[str]) -> list[tuple[float, Memory, str]]:
        ranked = []
        for relevance, memory in self.vector_search(query, user, scopes, k=10):
            recency = 0.5 ** ((today - memory.day) / 14)
            score = weights["relevance"] * relevance + weights["importance"] * memory.importance + weights["recency"] * recency
            parts = f"rel={relevance:.2f} imp={memory.importance:.1f} rec={recency:.2f}"
            ranked.append((round(score, 3), memory, parts))
        return sorted(ranked, key=lambda t: (-t[0], t[1].memory_id))[:3]


CONVERSATION = [
    (1, "alice", "session", "Alice lives in Berlin. Alice works at Acme on the payments team."),
    (2, "alice", "user", "Alice's manager is Omar, and Alice is allergic to shellfish."),
    (3, "alice", "user", "Bea started at Acme this week; she sits next to Alice."),
    (4, "alice", "user", "We discussed the checkout latency regression after the cache rollout."),
    (6, "alice", "user", "Alice moved to Lisbon last weekend, still remote for Acme."),
    (20, "alice", "user", "Alice's manager is Priya after the reorg."),
    (21, "alice", "user", "Quick note: lunch order for the offsite is pizza for everyone."),
    (3, "bob", "user", "Bob lives in Austin and works at Initech."),
]


def main() -> None:
    print("=" * 78)
    print("LESSON 09 - Hybrid memory: vector + KV + temporal graph, fused on read")
    print("=" * 78)
    memory = HybridMemory()
    for day, user, scope, text in CONVERSATION:
        memory.add(text, user, day, scope)
    print(f"\nWRITE PATH (ADD-only; {len(memory.memories)} memories, {len(memory.kv)} KV keys, {len(memory.edges)} edges)")
    print("\n".join(memory.log))

    today, scopes = 22, {"user", "session"}
    print("\nFOUR QUERY CLASSES, THREE STORES")
    semantic = memory.vector_search("what did we talk about regarding slow checkout performance", "alice", scopes, 1)[0]
    print(f"  semantic   'slow checkout performance'     vector -> {semantic[1].text} (cos={semantic[0]})")
    print(f"  lookup     'who is Alice's manager now?'   kv     -> {memory.kv_lookup('alice', 'alice', 'manager_is')}")
    print(f"  relation   'who else works at Alice's co?' graph  -> {memory.coworkers('alice')}")
    city_then = [e.obj for e in memory.graph_neighbors("alice", as_of=4) if e.relation == "lives_in"]
    city_now = [e.obj for e in memory.graph_neighbors("alice") if e.relation == "lives_in"]
    print(f"  temporal   'where did Alice live on day 4?' graph -> {city_then} (now: {city_now})")
    vector_only = memory.vector_search("who else works at Acme", "alice", scopes, 2)
    print(f"  vector-only answer to the relation query returns text, not a list: {[m.memory_id for _, m in vector_only]}")

    query = "what should I know about Alice before booking the team lunch"
    profiles = {
        "chat (recency heavy)": {"relevance": 0.4, "importance": 0.1, "recency": 0.5},
        "safety (importance heavy)": {"relevance": 0.3, "importance": 0.6, "recency": 0.1},
    }
    print(f"\nFUSION for: {query!r}")
    for name, weights in profiles.items():
        print(f"  profile {name}: {weights}")
        for score, item, parts in memory.fused(query, "alice", today, weights, scopes):
            print(f"    {score:.3f} {item.memory_id} [{parts}] {item.text[:58]}")

    print("\nSCOPE ISOLATION")
    leak = [m.memory_id for m in memory.visible("bob", {"user", "session"}) if "alice" in m.text.lower()]
    print(f"  bob's view contains Alice facts: {leak or 'none'}")
    session_only = [m.memory_id for m in memory.visible("alice", {"user"})]
    print(f"  alice user-scope only (session note m01 excluded): {session_only}")
    print(f"  kv for bob's city: {memory.kv_lookup('bob', 'bob', 'lives_in')}; for alice via bob's key space: {memory.kv_lookup('bob', 'alice', 'lives_in')}")

    print("\ntakeaways:")
    print("  - each store answers a different question class; none answers all four")
    print("  - ADD-only writes plus validity intervals keep history: Berlin is closed, not deleted")
    print("  - the chat profile drops the shellfish allergy from the top 3; the safety profile ranks it first")
    print("  - m02 mixes a stale fact (manager Omar) with a live one (allergy): store atomic facts, not messages")


if __name__ == "__main__":
    main()
