from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def test_safe_shadow_registration_is_admin_gated_and_never_registers_paper_or_broker_tasks():
    text=(ROOT/"v5/scripts/register_safe_shadow_tasks.ps1").read_text(encoding="utf-8")
    assert "Administrator token required" in text and "Register-ScheduledTask" in text and "$installed.Count -ne 8" in text and "08:55:00" in text
    assert "paper_buy" not in text and "paper_sell" not in text and "broker" in text
