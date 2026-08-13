from pathlib import Path


def test_shadow_horizon_is_bounded_calendar_driven_and_never_adds_paper_or_broker():
    text=(Path(__file__).resolve().parents[1]/"v5/scripts/register_shadow_horizon.ps1").read_text(encoding="utf-8")
    assert "TradingDays -gt 10" in text and "trading_calendar_cn.csv" in text and "register_safe_shadow_tasks.ps1" in text
    assert "paper_buy" not in text and "paper_sell" not in text and "Register-ScheduledTask" not in text
    assert 'paper_tasks=0' in text and 'broker_tasks=0' in text
