from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]

def test_compatibility_clis_cannot_bypass_task_windows_or_dependencies():
    fact=(ROOT/"v5/scripts/v5_fact_job.py").read_text(encoding="utf-8")
    push=(ROOT/"v5/scripts/v5_push_job.py").read_text(encoding="utf-8")
    universe=(ROOT/"v5/scripts/v5_universe_job.py").read_text(encoding="utf-8")
    assert "from v5.task_runner import run" in fact and "from v5.jobs import produce" not in fact
    assert "from v5.task_runner import run" in push and "from v5.notification import send" not in push
    assert "from v5.preflight import run" in universe and "from v5.universe_refresh import refresh" not in universe
