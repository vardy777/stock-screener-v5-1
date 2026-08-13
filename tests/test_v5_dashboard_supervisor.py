from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_dashboard_runner_rejects_foreign_port_owner_and_replaces_only_v5():
    text = (ROOT / "v5" / "scripts" / "run_v5_dashboard.ps1").read_text(encoding="utf-8")
    assert "Get-NetTCPConnection" in text
    assert "-m v5.dashboard" in text
    assert "non-V5 process" in text
    assert "Stop-Process -Id $listener.OwningProcess" in text
    assert "did not become free" in text
