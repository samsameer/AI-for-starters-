from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
import tempfile
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

HEAD_LINES = 3
TAIL_LINES = 6
ROTATE_BYTES = 4_000
MAX_ROTATIONS = 3
FAILURE_TEXT = re.compile(r"\bFAILED\b|Traceback \(most recent call last\)")

REDACTIONS = [
    (re.compile(r"(?i)bearer\s+[A-Za-z0-9._\-]+"), "Bearer [REDACTED]"),
    (re.compile(r"(?i)\b(password|passwd|secret|api[_-]?key|token)\s*[:=]\s*\S+"), r"\1=[REDACTED]"),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "AKIA[REDACTED]"),
    (re.compile(r"\bsk-ant-[A-Za-z0-9_\-]+"), "sk-ant-[REDACTED]"),
    (re.compile(r"\bxox[baprs]-[A-Za-z0-9\-]+"), "xox-[REDACTED]"),
]


@dataclass
class FeedbackRecord:
    command_id: str
    parent_command_id: str | None
    command: list[str]
    agent_note: str
    exit_code: int | None
    duration_ms: int
    stdout_tail: str
    stderr_tail: str
    error: str | None = None
    truncated_lines: dict[str, int] = field(default_factory=dict)
    redaction_hits: dict[str, int] = field(default_factory=dict)


def head_tail(text: str) -> tuple[str, int]:
    lines = text.splitlines()
    if len(lines) <= HEAD_LINES + TAIL_LINES:
        return text, 0
    cut = len(lines) - HEAD_LINES - TAIL_LINES
    return "\n".join(lines[:HEAD_LINES] + [f"...truncated {cut} lines..."] + lines[-TAIL_LINES:]), cut


def redact(text: str) -> tuple[str, int]:
    hits = 0
    for pattern, replacement in REDACTIONS:
        text, count = pattern.subn(replacement, text)
        hits += count
    return text, hits


def capture(text: str | bytes | None) -> tuple[str, int, int]:
    raw = text.decode(errors="replace") if isinstance(text, bytes) else (text or "")
    trimmed, cut = head_tail(raw)
    clean, hits = redact(trimmed)
    return clean, cut, hits


class FeedbackRunner:
    def __init__(self, workdir: Path) -> None:
        self.path = workdir / "feedback_record.jsonl"
        self.counter = 0

    def next_id(self, command: list[str]) -> str:
        self.counter += 1
        return hashlib.sha256(f"{self.counter}:{command}".encode()).hexdigest()[:10]

    def rotate_if_needed(self) -> None:
        if not self.path.exists() or self.path.stat().st_size < ROTATE_BYTES:
            return
        oldest = self.path.with_name(f"{self.path.name}.{MAX_ROTATIONS}")
        oldest.unlink(missing_ok=True)
        for index in range(MAX_ROTATIONS - 1, 0, -1):
            source = self.path.with_name(f"{self.path.name}.{index}")
            if source.exists():
                source.rename(self.path.with_name(f"{self.path.name}.{index + 1}"))
        self.path.rename(self.path.with_name(f"{self.path.name}.1"))

    def run(self, command: list[str], note: str, parent: str | None = None, timeout_s: float = 5.0) -> FeedbackRecord:
        started = time.monotonic()
        base = {"command_id": self.next_id(command), "parent_command_id": parent, "command": command, "agent_note": note}
        try:
            done = subprocess.run(command, capture_output=True, text=True, timeout=timeout_s)
            exit_code, error, out_raw, err_raw = done.returncode, None, done.stdout, done.stderr
        except subprocess.TimeoutExpired as exc:
            exit_code, error, out_raw, err_raw = None, f"timeout after {timeout_s}s", exc.stdout, exc.stderr
        except FileNotFoundError as exc:
            exit_code, error, out_raw, err_raw = None, f"not found: {exc.filename}", "", ""
        out, out_cut, out_hits = capture(out_raw)
        err, err_cut, err_hits = capture(err_raw)
        record = FeedbackRecord(
            exit_code=exit_code,
            duration_ms=int((time.monotonic() - started) * 1000),
            stdout_tail=out,
            stderr_tail=err,
            error=error,
            truncated_lines={"stdout": out_cut, "stderr": err_cut},
            redaction_hits={"stdout": out_hits, "stderr": err_hits},
            **base,
        )
        self.rotate_if_needed()
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(asdict(record)) + "\n")
        return record

    def load_all(self) -> list[FeedbackRecord]:
        files = sorted(self.path.parent.glob(self.path.name + "*"), reverse=True)
        records: list[FeedbackRecord] = []
        for file in files:
            for line in file.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    records.append(FeedbackRecord(**json.loads(line)))
        return records

    def retry_chain(self, command_id: str) -> list[str]:
        by_id = {r.command_id: r for r in self.load_all()}
        chain: list[str] = []
        cursor: str | None = command_id
        while cursor in by_id:
            chain.append(cursor)
            cursor = by_id[cursor].parent_command_id
        return list(reversed(chain))


def can_advance(record: FeedbackRecord) -> tuple[bool, str]:
    if record.exit_code is None:
        return False, f"no exit code ({record.error}); refuse to claim progress"
    if record.exit_code != 0:
        return False, f"exit {record.exit_code}; read stderr before the next edit"
    if FAILURE_TEXT.search(record.stdout_tail + record.stderr_tail):
        return False, "exit 0 but the tail reports a failure; investigate"
    return True, "verified by exit 0"


def main() -> None:
    py = sys.executable
    with tempfile.TemporaryDirectory() as tmp:
        runner = FeedbackRunner(Path(tmp))
        steps = [
            ("ok", [py, "-c", "print('42 tests passed')"], "expect tests to pass", None),
            ("noisy", [py, "-c", "[print(f'line {i}') for i in range(40)]; print('FAILED test_signup')"], "expect long log", None),
            ("leak", [py, "-c", "print('Authorization: Bearer abc.def'); print('api_key=sk-ant-xyz123')"], "expect redaction", None),
            ("fail", [py, "-c", "import sys; sys.stderr.write('AssertionError: 422 != 200'); sys.exit(1)"], "first attempt", None),
            ("retry", [py, "-c", "print('1 passed')"], "retry after fixing validation", "fail"),
            ("slow", [py, "-c", "import time; time.sleep(3)"], "expect timeout", None),
            ("missing", ["definitely-not-a-binary"], "probe missing tool", None),
        ]
        ids: dict[str, str] = {}
        for label, command, note, parent_label in steps:
            timeout = 0.5 if label == "slow" else 5.0
            record = runner.run(command, note, ids.get(parent_label) if parent_label else None, timeout)
            ids[label] = record.command_id
            ok, reason = can_advance(record)
            print(f"{label:8} exit={str(record.exit_code):4} advance={str(ok):5} {reason}")
            if record.truncated_lines["stdout"]:
                print(f"         truncated {record.truncated_lines['stdout']} stdout lines; tail keeps: {record.stdout_tail.splitlines()[-1]!r}")
            if sum(record.redaction_hits.values()):
                print(f"         redacted on write: {record.stdout_tail!r}")
        for _ in range(12):
            runner.run([py, "-c", "print('x' * 300)"], "fill log to force rotation")
        rotated = sorted(p.name for p in Path(tmp).glob("feedback_record.jsonl*"))
        print(f"\nretry chain (oldest -> newest): {runner.retry_chain(ids['retry'])}")
        print(f"files after rotation: {rotated}")
        print(f"records readable across rotations: {len(runner.load_all())}")


if __name__ == "__main__":
    main()
