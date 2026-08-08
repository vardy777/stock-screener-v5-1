"""Advanced P4 offline runtime primitives: subprocess, monitoring and alerts."""

from __future__ import annotations

from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import subprocess

from .offline_storage import atomic_json_write, exclusive_file_lock
from .p4_contracts import TaskContractViolation


class ControlledSubprocessExecutor:
    """Run an explicit argv without shell; kill and drain on deadline."""
    def __init__(self, argv, *, timeout_seconds=5, cwd=None):
        self.argv = tuple(str(item) for item in argv)
        self.timeout_seconds = float(timeout_seconds)
        self.cwd = str(cwd) if cwd else None

    def __call__(self, task_name, trade_date, attempt):
        process = subprocess.Popen(self.argv, cwd=self.cwd, shell=False,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        try:
            stdout, stderr = process.communicate(timeout=self.timeout_seconds)
        except subprocess.TimeoutExpired:
            process.kill(); stdout, stderr = process.communicate()
            return {"status": "TIMED_OUT", "reason_code": "PROCESS_DEADLINE_EXCEEDED",
                    "exit_code": process.returncode, "stdout_sha256": _sha(stdout), "stderr_sha256": _sha(stderr)}
        return {"status": "SUCCEEDED" if process.returncode == 0 else "FAILED",
                "reason_code": "PROCESS_EXIT_0" if process.returncode == 0 else "PROCESS_NONZERO_EXIT",
                "exit_code": process.returncode, "stdout_sha256": _sha(stdout), "stderr_sha256": _sha(stderr)}


def _sha(value):
    return hashlib.sha256(str(value).encode("utf-8")).hexdigest()


class OfflineMonitorStore:
    """Atomic local heartbeat and deduplicated alert lifecycle store."""
    def __init__(self, directory: Path):
        self.directory = Path(directory); self.path = self.directory / "monitor_state.json"
        self.lock = self.directory / ".monitor_state.lock"

    def _load(self):
        if not self.path.exists(): return {"schema_version": "offline-monitor-state-v1", "heartbeats": [], "alerts": {}}
        try: return json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc: raise TaskContractViolation("monitor: invalid state") from exc

    def heartbeat(self, *, process_id, recorded_at: datetime):
        if recorded_at.tzinfo is None: raise TaskContractViolation("monitor: timezone required")
        with exclusive_file_lock(self.lock, error_type=TaskContractViolation):
            state = self._load(); row = {"process_id": str(process_id), "recorded_at": recorded_at.isoformat(timespec="seconds")}
            state["heartbeats"].append(row); state["heartbeats"] = state["heartbeats"][-100:]
            atomic_json_write(self.path, state); return row

    def reconcile_alert(self, *, key, severity, reason_code, observed_at: datetime, active=True):
        with exclusive_file_lock(self.lock, error_type=TaskContractViolation):
            state = self._load(); current = state["alerts"].get(key)
            if active:
                if current and current["status"] == "ACTIVE":
                    current["last_seen_at"] = observed_at.isoformat(timespec="seconds")
                    current["occurrences"] += 1
                    if _rank(severity) > _rank(current["severity"]): current["severity"] = severity
                else:
                    current = {"alert_id": "alert-" + _sha(key)[:24], "key": key, "severity": severity,
                        "reason_code": reason_code, "status": "ACTIVE", "first_seen_at": observed_at.isoformat(timespec="seconds"),
                        "last_seen_at": observed_at.isoformat(timespec="seconds"), "occurrences": 1}
            elif current and current["status"] == "ACTIVE":
                current["status"] = "RECOVERED"; current["recovered_at"] = observed_at.isoformat(timespec="seconds")
            if current: state["alerts"][key] = current
            atomic_json_write(self.path, state); return current

    def report(self): return self._load()

    def record_failure(self, *, key, reason_code, observed_at: datetime):
        current = self._load()["alerts"].get(key)
        occurrences = int(current.get("occurrences", 0)) + 1 if current and current.get("status") == "ACTIVE" else 1
        severity = "ERROR" if occurrences >= 3 else "WARNING"
        return self.reconcile_alert(key=key, severity=severity, reason_code=reason_code,
                                    observed_at=observed_at, active=True)


def _rank(value): return {"WARNING": 1, "ERROR": 2, "CRITICAL": 3}.get(value, 0)


class OfflineDaemonHarness:
    """One-shot daemon harness used to prove dashboard-independent restart."""
    def __init__(self, orchestrator, monitor: OfflineMonitorStore, process_id="offline-daemon"):
        self.orchestrator = orchestrator; self.monitor = monitor; self.process_id = process_id

    def run_once(self, now):
        recovery = self.orchestrator.recover_interrupted(observed_at=now)
        result = self.orchestrator.tick(now)
        heartbeat = self.monitor.heartbeat(process_id=self.process_id, recorded_at=now)
        return {"recovery": recovery, "result": result, "heartbeat": heartbeat}
