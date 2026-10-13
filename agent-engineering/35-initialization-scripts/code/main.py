from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path


NOW = 1_791_849_600.0
HOUR = 3600.0


@dataclass
class InitConfig:
    min_python: tuple[int, int] = (3, 11)
    modules: list[str] = field(default_factory=lambda: ["json", "sqlite3", "tomllib"])
    test_command: list[str] = field(default_factory=lambda: ["python3", "-m", "unittest", "discover", "tests"])
    required_env: list[str] = field(default_factory=lambda: ["PROVIDER_API_KEY", "APP_ENV"])
    secret_env: list[str] = field(default_factory=lambda: ["PROVIDER_API_KEY"])
    state_max_age_hours: float = 24.0
    lkg_file_budget: int = 50
    probe_budget_ms: int = 3000
    lock_ttl_hours: float = 24.0


@dataclass
class Probe:
    name: str
    status: str
    detail: str
    severity: str = "block"
    duration_ms: int = 0


def probe_runtime(cfg: InitConfig) -> Probe:
    have = sys.version_info[:2]
    ok = have >= cfg.min_python
    return Probe("runtime", "pass" if ok else "fail", f"python {have[0]}.{have[1]} (need >= {cfg.min_python[0]}.{cfg.min_python[1]})")


def probe_modules(cfg: InitConfig) -> Probe:
    missing = [m for m in cfg.modules if importlib.util.find_spec(m) is None]
    return Probe("dependencies", "fail" if missing else "pass", f"missing {missing}" if missing else f"{len(cfg.modules)} importable")


def probe_test_command(cfg: InitConfig, repo: Path) -> Probe:
    target = repo / cfg.test_command[-1]
    if not target.exists():
        return Probe("test_command", "fail", f"{' '.join(cfg.test_command)} has no {target.name}/ directory")
    return Probe("test_command", "pass", " ".join(cfg.test_command))


def probe_env(cfg: InitConfig, env: dict[str, str]) -> Probe:
    missing = [k for k in cfg.required_env if not env.get(k)]
    shown = {k: ("set, redacted" if k in cfg.secret_env else env[k]) for k in cfg.required_env if env.get(k)}
    if missing:
        return Probe("env", "fail", f"missing {missing}; present {shown}")
    return Probe("env", "pass", f"present {shown}")


def probe_state(cfg: InitConfig, repo: Path, now: float) -> Probe:
    path = repo / "agent_state.json"
    if not path.exists():
        return Probe("state_freshness", "warn", "no state yet, first session", severity="warn")
    age_h = (now - json.loads(path.read_text())["updated_at"]) / HOUR
    if age_h > cfg.state_max_age_hours:
        return Probe("state_freshness", "warn", f"state older than {cfg.state_max_age_hours:.0f}h ({int(age_h // 24)}d), confirm before resuming", severity="warn")
    return Probe("state_freshness", "pass", f"state younger than {cfg.state_max_age_hours:.0f}h", severity="warn")


def probe_board(repo: Path) -> Probe:
    board = json.loads((repo / "task_board.json").read_text())
    active = [t["id"] for t in board if t["status"] == "in_progress"]
    if len(active) > 1:
        return Probe("one_in_progress", "fail", f"{active} are all in_progress; a human must pick one")
    return Probe("one_in_progress", "pass", f"active={active or 'none'}")


def probe_lkg(cfg: InitConfig, changed_since_lkg: list[str]) -> Probe:
    count = len(changed_since_lkg)
    if count > cfg.lkg_file_budget:
        return Probe("lkg_drift", "fail", f"{count} files changed since last-known-good (budget {cfg.lkg_file_budget})")
    return Probe("lkg_drift", "pass", f"{count} files changed since last-known-good")


def timed(probe: Probe, simulated_ms: int, cfg: InitConfig) -> Probe:
    probe.duration_ms = simulated_ms
    if simulated_ms > cfg.probe_budget_ms and probe.status == "pass":
        probe.status = "warn"
        probe.detail += f" (slow {simulated_ms}ms, move out of init or cache it)"
    return probe


def fingerprint(cfg: InitConfig, repo: Path) -> str:
    material = json.dumps(asdict(cfg), sort_keys=True) + (repo / "requirements.txt").read_text()
    return hashlib.sha256(material.encode()).hexdigest()[:16]


def run_init(cfg: InitConfig, repo: Path, env: dict[str, str], now: float, changed: list[str], use_lock: bool = True) -> tuple[int, dict[str, object]]:
    lock_path = repo / ".agent" / "prereqs.lock"
    fp = fingerprint(cfg, repo)
    if use_lock and lock_path.exists():
        lock = json.loads(lock_path.read_text())
        if lock["fingerprint"] == fp and now - lock["written_at"] < cfg.lock_ttl_hours * HOUR:
            return 0, {"cached": True, "fingerprint": fp}
    probes = [
        timed(probe_runtime(cfg), 1, cfg),
        timed(probe_modules(cfg), 4, cfg),
        timed(probe_test_command(cfg, repo), 2, cfg),
        timed(probe_env(cfg, env), 0, cfg),
        timed(probe_state(cfg, repo, now), 1, cfg),
        timed(probe_board(repo), 1, cfg),
        timed(probe_lkg(cfg, changed), 4200, cfg),
    ]
    failed = [p.name for p in probes if p.status == "fail" and p.severity == "block"]
    report = {"cached": False, "generated_at": now, "fingerprint": fp, "ok": not failed,
              "failed": failed, "probes": [asdict(p) for p in probes]}
    (repo / ".agent").mkdir(exist_ok=True)
    (repo / ".agent" / "init_report.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    if failed:
        return 1, report
    lock_path.write_text(json.dumps({"fingerprint": fp, "written_at": now}) + "\n")
    return 0, report


def session_context(report: dict[str, object]) -> str:
    lines = ["[init] workbench ready" if report.get("ok", True) else "[init] workbench BROKEN"]
    for probe in report.get("probes", []):
        if probe["status"] != "pass":
            lines.append(f"[init] {probe['status']}: {probe['name']}: {probe['detail']}")
    return "\n".join(lines)


def show(label: str, code: int, report: dict[str, object]) -> None:
    print(f"\n{label}: exit {code}")
    if report.get("cached"):
        print(f"  prereqs.lock fresh for fingerprint {report['fingerprint']}, probes skipped")
        return
    for probe in report["probes"]:
        print(f"  {probe['name']:<16} {probe['status']:<4} {probe['duration_ms']:>5}ms  {probe['detail']}")


def strip_volatile(report: dict[str, object]) -> dict[str, object]:
    return {k: v for k, v in report.items() if k != "generated_at"}


def main() -> None:
    cfg = InitConfig()
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        (repo / "tests").mkdir()
        (repo / "requirements.txt").write_text("fastapi==0.120.0\n")
        (repo / "agent_state.json").write_text(json.dumps({"updated_at": NOW - 30 * HOUR}) + "\n")
        (repo / "task_board.json").write_text(json.dumps([
            {"id": "T-001", "status": "in_progress"}, {"id": "T-002", "status": "in_progress"}]) + "\n")
        changed = [f"src/module_{i}.py" for i in range(12)]

        code, report = run_init(cfg, repo, {"APP_ENV": "dev"}, NOW, changed)
        show("run 1 (cold container, missing key, two tasks in progress)", code, report)
        print("  session-start context injected into the agent:")
        print("    " + session_context(report).replace("\n", "\n    "))

        (repo / "task_board.json").write_text(json.dumps([
            {"id": "T-001", "status": "in_progress"}, {"id": "T-002", "status": "todo"}]) + "\n")
        env = {"APP_ENV": "dev", "PROVIDER_API_KEY": "sk-test-not-a-real-key"}
        code, first_ok = run_init(cfg, repo, env, NOW + 60, changed)
        show("run 2 (operator fixed env and board)", code, first_ok)
        print("  secret printed anywhere in report?", "sk-test" in json.dumps(first_ok))

        code, cached = run_init(cfg, repo, env, NOW + 2 * HOUR, changed)
        show("run 3 (two hours later, nothing changed)", code, cached)

        code, again = run_init(cfg, repo, env, NOW + 3 * HOUR, changed, use_lock=False)
        print(f"\nrun 4 (--no-cache): exit {code}, idempotent modulo timestamp: {strip_volatile(again) == strip_volatile(first_ok)}")

        (repo / "requirements.txt").write_text("fastapi==0.120.0\nhttpx==0.28.1\n")
        code, report = run_init(cfg, repo, env, NOW + 4 * HOUR, [f"src/f{i}.py" for i in range(61)])
        show("run 5 (manifest changed, big drift since last-known-good)", code, report)
        print(f"\nlaunch agent? {'no, fail loud and surface to a human' if code else 'yes'}")


if __name__ == "__main__":
    main()
