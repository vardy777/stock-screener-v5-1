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
