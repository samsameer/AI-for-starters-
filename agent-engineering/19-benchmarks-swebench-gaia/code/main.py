from __future__ import annotations

import math
import random
from dataclasses import dataclass, field

Repo = dict[str, str]

BASE_REPO: Repo = {
    "app.py": "def inc(n):\n    return n\n\ndef label(n):\n    return f'item-{n}'\n",
    "tests/test_app.py": (
        "def test_inc_adds_one():\n    assert inc(1) == 2\n\n"
        "def test_inc_returns_int():\n    assert isinstance(inc(1), int)\n\n"
        "def test_label_format():\n    assert label(3) == 'item-3'\n"
    ),
}

FAIL_TO_PASS = ("test_inc_adds_one",)
PASS_TO_PASS = ("test_inc_returns_int", "test_label_format")


@dataclass(frozen=True)
class Candidate:
    name: str
    issue: str
    patch: Repo


@dataclass
class Verdict:
    name: str
    f2p: int
    p2p: int
    resolved: bool
    flags: list[str] = field(default_factory=list)

    @property
    def audited(self) -> bool:
        return self.resolved and not self.flags


def run_tests(repo: Repo) -> dict[str, bool]:
    namespace: dict[str, object] = {}
    for path, source in repo.items():
        if not path.startswith("tests/"):
            exec(source, namespace)
    results: dict[str, bool] = {}
    for path, source in repo.items():
        if not path.startswith("tests/"):
            continue
        exec(source, namespace)
        for test_name in [k for k in namespace if k.startswith("test_")]:
            try:
                namespace[test_name]()
                results[test_name] = True
            except Exception:
                results[test_name] = False
    return results


def leaked_lines(issue: str, patch: Repo) -> list[str]:
    hits = []
    for source in patch.values():
        for line in source.splitlines():
            stripped = line.strip()
            if len(stripped) > 10 and stripped in issue:
                hits.append(stripped)
    return hits


def evaluate(candidate: Candidate) -> Verdict:
    repo = {**BASE_REPO, **candidate.patch}
    results = run_tests(repo)
    f2p = sum(results.get(t, False) for t in FAIL_TO_PASS)
    p2p = sum(results.get(t, False) for t in PASS_TO_PASS)
    resolved = f2p == len(FAIL_TO_PASS) and p2p == len(PASS_TO_PASS)
    flags = []
    if any(path.startswith("tests/") for path in candidate.patch):
        flags.append("test_tampering")
    if leaked_lines(candidate.issue, candidate.patch):
        flags.append("solution_leak_in_issue")
    return Verdict(candidate.name, f2p, p2p, resolved, flags)


CLEAN_ISSUE = "inc(1) returns 1 but the docs say it should add one."
LEAKY_ISSUE = "inc is wrong. Fix: change the body to `return n + 1` please."

CANDIDATES = [
    Candidate("honest_fix", CLEAN_ISSUE, {"app.py": BASE_REPO["app.py"].replace("return n\n", "return n + 1\n", 1)}),
    Candidate("overreach", CLEAN_ISSUE, {"app.py": "def inc(n):\n    return n + 1\n\ndef label(n):\n    return str(n)\n"}),
    Candidate("float_regression", CLEAN_ISSUE, {"app.py": BASE_REPO["app.py"].replace("return n\n", "return n + 1.0\n", 1)}),
    Candidate("test_rewriter", CLEAN_ISSUE, {"tests/test_app.py": "def test_inc_adds_one():\n    assert True\n\ndef test_inc_returns_int():\n    assert True\n\ndef test_label_format():\n    assert True\n"}),
    Candidate("copied_from_issue", LEAKY_ISSUE, {"app.py": BASE_REPO["app.py"].replace("return n\n", "return n + 1\n", 1)}),
]


def pass_at_k(n: int, c: int, k: int) -> float:
    if n - c < k:
        return 1.0
    return 1.0 - math.comb(n - c, k) / math.comb(n, k)


def pass_hat_k(n: int, c: int, k: int) -> float:
    return math.comb(c, k) / math.comb(n, k) if c >= k else 0.0


def reliability_table(seed: int = 7, trials: int = 10) -> list[tuple[str, int, float, float, float]]:
    rng = random.Random(seed)
    rows = []
    for tid, p_success in (("easy_fix", 0.9), ("multi_file", 0.6), ("long_horizon", 0.3)):
        successes = sum(rng.random() < p_success for _ in range(trials))
        rows.append((tid, successes, pass_at_k(trials, successes, 1), pass_at_k(trials, successes, 5), pass_hat_k(trials, successes, 5)))
    return rows


GAIA_STEP_WORDS = {"then", "after", "finally", "next", "and"}
GAIA_MODALITIES = ("image", "video", "audio", "pdf", "chart", "spreadsheet")
GAIA_TOOLS = ("search", "visit", "find", "extract", "count", "download")


def gaia_level(question: str) -> int:
    words = question.lower().replace(",", " ").split()
    text = " ".join(words)
    hops = 1 + sum(w in GAIA_STEP_WORDS for w in words)
    signal = hops + sum(m in text for m in GAIA_MODALITIES) + sum(t in text for t in GAIA_TOOLS)
    return 1 if signal <= 2 else 2 if signal <= 5 else 3


def main() -> None:
    print("SWE-bench-style harness: FAIL_TO_PASS + PASS_TO_PASS + integrity audit")
    raw = audited = 0
    for candidate in CANDIDATES:
        v = evaluate(candidate)
        raw += v.resolved
        audited += v.audited
        print(f"  {v.name:18} f2p={v.f2p}/{len(FAIL_TO_PASS)} p2p={v.p2p}/{len(PASS_TO_PASS)} resolved={str(v.resolved):5} flags={v.flags or '-'}")
    print(f"  raw resolve rate     {raw}/{len(CANDIDATES)}")
    print(f"  audited resolve rate {audited}/{len(CANDIDATES)}")

    print("\nreliability: pass@k (any of k) vs pass^k (all of k), n=10 trials per task")
    for tid, c, p1, p5, ph5 in reliability_table():
        print(f"  {tid:13} successes={c:2}/10  pass@1={p1:.2f}  pass@5={p5:.2f}  pass^5={ph5:.2f}")

    print("\nGAIA-style difficulty estimate")
    for q in (
        "What is the capital of Portugal?",
        "Search Wikipedia for the ReAct paper and extract the first author.",
        "Visit the arXiv page for ReAct, download the PDF, find the GitHub link, then count open issues labelled bug and finally return the ratio to all issues.",
    ):
        print(f"  L{gaia_level(q)}  {q[:72]}")

    print("\nreport a score with: benchmark version, harness, trials, pass^k, cost, and audit flags")


if __name__ == "__main__":
    main()
