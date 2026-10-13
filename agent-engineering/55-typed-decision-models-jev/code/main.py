from __future__ import annotations

import json
import math
import os
import re
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Union


@dataclass(frozen=True)
class Noul:
    instructions: str
    criteria: dict[str, str] | None = None
    type: str = "noul"


@dataclass(frozen=True)
class Choice:
    instructions: str
    criteria: dict[str, str | None]
    type: str = "choice"


@dataclass(frozen=True)
class Score:
    instructions: str
    criteria: list[str | None]
    type: str = "score"


Question = Union[Noul, Choice, Score]
ID_PATTERN = re.compile(r"^[A-Za-z0-9_.\-]{1,100}$")


def validate(questions: dict[str, Question]) -> None:
    if not 1 <= len(questions) <= 64:
        raise ValueError("system one needs 1..64 questions")
    for qid, q in questions.items():
        if not ID_PATTERN.match(qid):
            raise ValueError(f"bad question id {qid!r}")
        if isinstance(q, Choice) and (not isinstance(q.criteria, dict) or len(q.criteria) < 2):
            raise ValueError(f"choice {qid!r} needs a map of at least two labels")
        if isinstance(q, Score) and (not isinstance(q.criteria, list) or len(q.criteria) < 2):
            raise ValueError(f"score {qid!r} needs an ordered list of at least two levels")


def to_payload(state: Any, questions: dict[str, Question], model: str) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for qid, q in questions.items():
        body: dict[str, Any] = {"type": q.type, "instructions": q.instructions}
        if q.criteria is not None:
            body["criteria"] = q.criteria
        out[qid] = body
    return {"model": model, "state": state, "questions": out}


def softmax(logits: dict[str, float]) -> dict[str, float]:
    top = max(logits.values())
    exp = {k: math.exp(v - top) for k, v in logits.items()}
    total = sum(exp.values())
    return {k: round(v / total, 4) for k, v in exp.items()}


def tokens(text: Any) -> set[str]:
    raw = text if isinstance(text, str) else json.dumps(text)
    return set(re.findall(r"[a-z]+", raw.lower()))


def overlap(a: set[str], b: Any) -> float:
    words = tokens(b) if b else set()
    return float(len(a & words))


class LocalSystemOne:
    name = "toy-system-one-0.1"

    def run(self, payload: dict[str, Any]) -> dict[str, Any]:
        state = tokens(payload["state"])
        answers: dict[str, Any] = {}
        for qid, q in payload["questions"].items():
            if q["type"] == "noul":
                yes = (q.get("criteria") or {}).get("true") or q["instructions"]
                no = (q.get("criteria") or {}).get("false") or ""
                p = softmax({"y": 1.5 * overlap(state, yes) - 1.0, "n": 1.5 * overlap(state, no)})["y"]
                answers[qid] = {"type": "noul", "noul": p}
            elif q["type"] == "choice":
                probs = softmax({label: 1.5 * overlap(state, f"{label} {desc}") if desc else 0.5 for label, desc in q["criteria"].items()})
                best = max(probs, key=probs.get)
                answers[qid] = {"type": "choice", "choice": best, "confidence": probs[best], "probabilities": probs}
            else:
                levels = {str(i): 1.5 * overlap(state, d) + 0.1 * i for i, d in enumerate(q["criteria"])}
                probs = softmax(levels)
                expected = round(sum(int(k) * p for k, p in probs.items()), 3)
                answers[qid] = {
                    "type": "score",
                    "score": expected,
                    "confidence": max(probs.values()),
                    "legend": {str(i): d for i, d in enumerate(q["criteria"])},
                    "probabilities": probs,
                }
        size = len(json.dumps(payload)) // 4
        return {"model": self.name, "answers": answers, "usage": {"input_tokens": size, "output_tokens": len(answers)}}


class TypeSafeHttp:
    def __init__(self, api_key: str, base_url: str = "https://api.typesafe.ai") -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")

    def run(self, payload: dict[str, Any]) -> dict[str, Any]:
        req = urllib.request.Request(
            f"{self.base_url}/v1/systemone",
            data=json.dumps(payload).encode(),
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read())


@dataclass
class SystemOneClient:
    backend: Any
    model: str = "jev-latest"
    calls: list[dict[str, Any]] = field(default_factory=list)

    def system_one(self, state: Any, questions: dict[str, Question]) -> dict[str, Any]:
        validate(questions)
        result = self.backend.run(to_payload(state, questions, self.model))
        missing = set(questions) - set(result.get("answers", {}))
        if missing:
            raise RuntimeError(f"response missing answers {sorted(missing)}")
        self.calls.append(result["usage"])
        return result


TRIAGE = {
    "team": Choice(
        "Which team should handle this ticket?",
        {
            "billing": "payments charged refund invoice twice",
            "technical": "bug error crash outage api integration failing",
            "other": None,
        },
    ),
    "refund": Noul("Does the customer explicitly request a refund?", {"true": "refund money back", "false": "question how"}),
    "urgency": Score("How urgent is it?", ["no rush question", "soon annoyed", "asap outage failing everyone now"]),
}


def route(answers: dict[str, Any], threshold: float = 0.6) -> str:
    team = answers["team"]
    if team["choice"] == "other" or team["confidence"] < threshold:
        return "human_review"
    if answers["urgency"]["score"] >= 1.5:
        return f"page_{team['choice']}_oncall"
    return f"queue_{team['choice']}"


def main() -> None:
    key = os.environ.get("TYPESAFE_API_KEY")
    backend = TypeSafeHttp(key) if key else LocalSystemOne()
    client = SystemOneClient(backend)
    print(f"backend: {type(backend).__name__}")
    tickets = [
        "I was charged twice. Please refund the extra payment.",
        "The API is failing with 500 errors for everyone, fix asap!",
        "Do you have a dark mode?",
    ]
    for ticket in tickets:
        result = client.system_one({"ticket": ticket}, TRIAGE)
        a = result["answers"]
        print(json.dumps({
            "ticket": ticket,
            "team": a["team"]["choice"],
            "team_p": a["team"]["probabilities"],
            "refund_p": a["refund"]["noul"],
            "urgency": a["urgency"]["score"],
            "action": route(a),
        }, indent=2))
    try:
        client.system_one("x", {"bad id!": Noul("?")})
    except ValueError as e:
        print(f"rejected before network: {e}")
    print(f"calls={len(client.calls)} input_tokens={sum(u['input_tokens'] for u in client.calls)}")


if __name__ == "__main__":
    main()
