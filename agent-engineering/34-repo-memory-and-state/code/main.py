from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any


STATE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["schema_version", "active_task_id", "touched_files", "risks", "next_action"],
    "properties": {
        "schema_version": {"type": "integer", "enum": [2]},
        "active_task_id": {"type": "string", "pattern": r"^(T-\d{3,})?$"},
        "touched_files": {"type": "array", "items": {"type": "string"}},
        "assumptions": {"type": "array", "items": {"type": "string"}},
        "risks": {"type": "array", "items": {"type": "string"}},
        "artifacts": {"type": "array", "items": {"type": "string", "pattern": r"^artifacts/"}},
        "next_action": {"type": "string"},
        "last_seq": {"type": "integer"},
    },
}

TYPE_CHECKS = {
    "object": lambda v: isinstance(v, dict),
    "array": lambda v: isinstance(v, list),
    "string": lambda v: isinstance(v, str),
    "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
}


class SchemaError(Exception):
    pass


def validate(value: Any, schema: dict[str, Any], path: str = "$") -> None:
    expected = schema.get("type")
    if expected and not TYPE_CHECKS[expected](value):
        raise SchemaError(f"{path}: expected {expected}, got {type(value).__name__}")
    if "enum" in schema and value not in schema["enum"]:
        raise SchemaError(f"{path}: {value!r} not in {schema['enum']}")
    if "pattern" in schema and not re.match(schema["pattern"], value):
        raise SchemaError(f"{path}: {value!r} does not match {schema['pattern']}")
    if isinstance(value, dict):
        for key in schema.get("required", []):
            if key not in value:
                raise SchemaError(f"{path}: missing {key!r}")
        extra = sorted(set(value) - set(schema.get("properties", {})))
        if extra:
            raise SchemaError(f"{path}: unexpected fields {extra}")
        for key, sub in schema.get("properties", {}).items():
            if key in value:
                validate(value[key], sub, f"{path}.{key}")
    if isinstance(value, list):
        for index, item in enumerate(value):
            validate(item, schema.get("items", {}), f"{path}[{index}]")


def migrate(raw: dict[str, Any]) -> dict[str, Any]:
    version = raw.get("schema_version")
    if version == 2:
        return raw
    if version == 1:
        upgraded = dict(raw)
        upgraded["risks"] = upgraded.pop("blockers", [])
        upgraded["active_task_id"] = upgraded.get("active_task_id") or ""
        upgraded["schema_version"] = 2
        upgraded["last_seq"] = 0
        return upgraded
    raise SchemaError(f"unknown schema_version {version!r}; refusing to load")


def atomic_write(path: Path, content: str, crash_before_rename: bool = False) -> None:
    fd, tmp_name = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        if crash_before_rename:
            raise OSError("simulated crash before rename")
        os.replace(tmp_name, path)
    finally:
        Path(tmp_name).unlink(missing_ok=True)


class StateStore:
    def __init__(self, root: Path):
        self.snapshot_path = root / "agent_state.json"
        self.events_path = root / "state.events.jsonl"

    def load(self) -> dict[str, Any]:
        state = migrate(json.loads(self.snapshot_path.read_text()))
        validate(state, STATE_SCHEMA)
        return state

    def apply(self, state: dict[str, Any], event: dict[str, Any]) -> dict[str, Any]:
        updated = json.loads(json.dumps(state))
        if event["op"] == "set":
            updated[event["key"]] = event["value"]
        elif event["op"] == "append":
            updated[event["key"]] = updated.get(event["key"], []) + [event["value"]]
        updated["last_seq"] = event["seq"]
        validate(updated, STATE_SCHEMA)
        return updated

    def record(self, state: dict[str, Any], event: dict[str, Any]) -> dict[str, Any]:
        updated = self.apply(state, event)
        with self.events_path.open("a") as log:
            log.write(json.dumps(event, sort_keys=True) + "\n")
        return updated

    def snapshot(self, state: dict[str, Any], crash: bool = False) -> None:
        validate(state, STATE_SCHEMA)
        atomic_write(self.snapshot_path, json.dumps(state, indent=2, sort_keys=True) + "\n", crash)

    def replay(self) -> dict[str, Any]:
        state = self.load()
        for line in self.events_path.read_text().splitlines():
            event = json.loads(line)
            if event["seq"] > state["last_seq"]:
                state = self.apply(state, event)
        return state


def prefix_cache_hits(previous: list[str], current: list[str]) -> int:
    hits = 0
    for old, new in zip(previous, current):
        if hashlib.sha256(old.encode()).digest() != hashlib.sha256(new.encode()).digest():
            break
        hits += 1
    return hits


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        store = StateStore(root)
        legacy_v1 = {"schema_version": 1, "active_task_id": None, "touched_files": [],
                     "blockers": ["CI flaky on macOS"], "next_action": "pick next task"}
        store.snapshot_path.write_text(json.dumps(legacy_v1) + "\n")
        store.events_path.write_text("")

        state = store.load()
        print("loaded v1 file, migrated to v2:", {k: state[k] for k in ("schema_version", "active_task_id", "risks")})
        store.snapshot(state)

        events = [
            {"seq": 1, "op": "set", "key": "active_task_id", "value": "T-001"},
            {"seq": 2, "op": "append", "key": "touched_files", "value": "app.py"},
            {"seq": 3, "op": "append", "key": "assumptions", "value": "min password length is 8"},
            {"seq": 4, "op": "append", "key": "artifacts", "value": "artifacts/test-run-0004.log"},
            {"seq": 5, "op": "set", "key": "next_action", "value": "write test_app.py"},
        ]
        for event in events:
            state = store.record(state, event)
        print(f"recorded {len(events)} events to the append-only log")

        before = store.snapshot_path.read_text()
        try:
            store.snapshot(state, crash=True)
        except OSError as exc:
            print(f"snapshot crashed ({exc}); file unchanged: {store.snapshot_path.read_text() == before}")
            print("leftover temp files:", sorted(p.name for p in root.iterdir() if p.name.startswith("agent_state.json.")))

        print(f"snapshot is at last_seq={store.load()['last_seq']}, log is at seq={state['last_seq']}")
        recovered = store.replay()
        print("recovered by snapshot + replay:", {k: recovered[k] for k in ("active_task_id", "touched_files", "next_action")})
        print("recovered equals in-memory state:", recovered == state)

        for label, bad_event in [
            ("bad task id", {"seq": 6, "op": "set", "key": "active_task_id", "value": "T-bogus"}),
            ("null for array", {"seq": 6, "op": "set", "key": "touched_files", "value": None}),
            ("transcript in state", {"seq": 6, "op": "set", "key": "chat_transcript", "value": "..."}),
            ("inline blob", {"seq": 6, "op": "append", "key": "artifacts", "value": "id,email\n1,a@b.c"}),
        ]:
            try:
                store.record(state, bad_event)
                print(f"  accepted {label} (should not happen)")
            except SchemaError as exc:
                print(f"  refused {label}: {exc}")

        try:
            migrate({"schema_version": 9})
        except SchemaError as exc:
            print("future file:", exc)

        transcript = ["system: rules", "user: add validation", "assistant: reading app.py", "tool: app.py contents"]
        appended = transcript + ["assistant: wrote check", "tool: tests pass"]
        edited = ["system: rules", "user: add validation (edited)"] + transcript[2:] + ["assistant: wrote check"]
        print("\ntranscript discipline (cached prefix messages reused on the next call):")
        print(f"  append-only next turn : {prefix_cache_hits(transcript, appended)}/{len(transcript)} prefix messages reused")
        print(f"  history edited        : {prefix_cache_hits(transcript, edited)}/{len(transcript)} prefix messages reused")


if __name__ == "__main__":
    main()
