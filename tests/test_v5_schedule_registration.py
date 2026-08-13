from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def test_safe_shadow_registration_is_admin_gated_and_never_registers_paper_or_broker_tasks():
    text=(ROOT/"v5/scripts/register_safe_shadow_tasks.ps1").read_text(encoding="utf-8")
    assert "Register-ScheduledTask" in text and "$installed.Count -ne 7" in text and "AStock-V5-Readiness-$suffix" in text and "-WakeToRun" in text
    assert '-m v5.preflight --trade-date {0}' in text and '08:30:00' in text
    assert "Live-Acceptance-$suffix" in text and "15:20:00" in text and "--save" in text
    assert "RestartCount 3" in text and "RestartInterval (New-TimeSpan -Minutes 2)" in text
    assert "Administrator token required" not in text and "Universe-Refresh" not in text
    assert "paper_buy" not in text and "paper_sell" not in text and "broker" in text

def test_v5_dashboard_registration_is_persistent_read_only_and_supervised():
    text=(ROOT/"v5/scripts/register_dashboard_task.ps1").read_text(encoding="utf-8")
    assert "AStock-V5-Dashboard-Logon" in text and "run_v5_dashboard.ps1" in text
    assert "ExecutionTimeLimit ([TimeSpan]::Zero)" in text and "RestartCount 3" in text
    assert "paper" not in text.lower() and "broker" not in text.lower()
