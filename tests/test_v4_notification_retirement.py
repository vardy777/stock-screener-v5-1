from pathlib import Path
def test_v4_scheduled_adapter_permanently_rejects_every_business_task():
    text=(Path(__file__).resolve().parents[1]/"v4/scripts/p4_task_adapter.py").read_text(encoding="utf-8")
    assert "V4_PRODUCTION_RETIRED_V5_ONLY" in text
    assert "production_task_runner" not in text and "result=run(" not in text

def test_v4_dashboard_runner_is_code_retired_even_if_elevated_task_remains():
    text=(Path(__file__).resolve().parents[1]/"phase1/scripts/run_p5_dashboard.ps1").read_text(encoding="utf-8")
    assert text.index("V4_DASHBOARD_RETIRED_V5_ONLY") < text.index("v4.p5_dashboard")
