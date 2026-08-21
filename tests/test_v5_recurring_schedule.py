from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]

def test_recurring_schedule_has_complete_weekday_safe_chain():
    text=(ROOT/"v5/scripts/register_recurring_safe_tasks.ps1").read_text(encoding="utf-8")
    assert "New-ScheduledTaskTrigger -Weekly" in text and "Monday" in text and "Friday" in text
    for value in ("08:30:00","09:25:05","09:25:50","09:30:10","14:49:00","14:50:00","14:50:30","14:50:40","14:53:00","15:10:00","15:20:00"):assert value in text
    assert "paper_buy" in text and "paper_sell" in text and "broker" in text

def test_production_audit_inventories_every_v4_task_and_distinguishes_os_from_code_retirement():
    text=(ROOT/"scripts/audit_production_tasks.ps1").read_text(encoding="utf-8")
    assert 'TaskName -Like "AStock-V4-*"' in text
    assert "v4_os_tasks_all_disabled" in text and "v4_runtime_safe" in text
    assert "production-task-static-audit-v7" in text
