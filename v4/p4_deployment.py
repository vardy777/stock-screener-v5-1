"""Read-only deployment manifest and static audit; never registers tasks."""

from pathlib import Path


def offline_notification_manifest(project_root: Path):
    root = Path(project_root).resolve()
    runner = root / "phase1" / "scripts" / "run_scheduled_push.ps1"
    return {"schema_version": "offline-windows-task-manifest-v1", "apply_allowed": False,
            "tasks": [
                {"name": "AStock-V4-Push-Morning-0925", "at": "09:25:00", "mode": "morning", "runner": str(runner)},
                {"name": "AStock-V4-Push-Confirm-145020", "at": "14:50:20", "mode": "afternoon", "runner": str(runner)},
            ]}


def full_offline_task_manifest(project_root: Path):
    root = Path(project_root).resolve()
    tasks = [
        ("morning_decision", "AStock-V4-Morning-Decision-0925", "09:25:00", (), "decision_job.py morning"),
        ("morning_push", "AStock-V4-Morning-Push-092520", "09:25:20", ("morning_decision",), "morning_push.py"),
        ("paper_sell", "AStock-V4-Paper-Sell-093020", "09:30:20", (), "paper_trade.py sell"),
        ("feature_freeze", "AStock-V4-Feature-1449", "14:49:00", (), "capture signal"),
        ("confirmation_decision", "AStock-V4-Confirmation-Decision-145020", "14:50:20", ("feature_freeze", "morning_decision"), "decision_job.py confirmation"),
        ("confirmation_push", "AStock-V4-Confirmation-Push-145030", "14:50:30", ("confirmation_decision",), "afternoon_push.py"),
        ("paper_buy", "AStock-V4-Paper-Buy-145040", "14:50:40", ("confirmation_decision",), "paper_trade.py buy"),
        ("health_check", "AStock-V4-Health-1453", "14:53:00", ("confirmation_decision",), "health audit"),
        ("maintenance", "AStock-V4-Maintenance-1510", "15:10:00", ("health_check",), "maintenance"),
    ]
    return {"schema_version": "full-offline-task-manifest-v1", "apply_allowed": False,
            "project_root": str(root), "tasks": [
                {"task_name": name, "windows_task_name": windows_name, "at": at, "dependencies": list(deps), "command": command,
                 "working_directory": str(root), "run_level": "Limited", "enabled": False,
                 "gate": "offline_manifest_only"} for name, windows_name, at, deps, command in tasks]}


def audit_existing_windows_scripts(project_root: Path):
    root = Path(project_root).resolve()
    register = (root / "phase1" / "scripts" / "register_v4_snapshot_tasks.ps1").read_text(encoding="utf-8")
    runner = (root / "phase1" / "scripts" / "run_scheduled_push.ps1").read_text(encoding="utf-8")
    checks = {
        "morning_task_declared": "AStock-V4-Push-Morning-0925" in register,
        "confirmation_task_declared": "AStock-V4-Push-Confirm-145020" in register,
        "limited_principal": "-RunLevel Limited" in register,
        "push_runner_separate_from_dashboard": "run_scheduled_push.ps1" in register and "dashboard.py" not in runner,
        "decision_before_projection": "decision_job.py" in runner and "morning_push.py" in runner and "afternoon_push.py" in runner,
        "hidden_process": "CreateNoWindow = $true" in runner,
        "uses_project_venv": '.venv\\Scripts\\python.exe' in runner,
    }
    return {"schema_version": "windows-task-static-audit-v1", "read_only": True,
            "checks": checks, "passed": all(checks.values()), "registration_performed": False}
