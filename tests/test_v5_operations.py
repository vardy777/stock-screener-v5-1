from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from v5.core import CHINA_TZ
from v5.operations import health,maintenance
def test_health_fails_closed_when_required_facts_missing_and_maintenance_detects_corruption():
 with TemporaryDirectory() as d:
  root=Path(d);now=datetime(2026,8,14,15,10,tzinfo=CHINA_TZ);report=health(root,"2026-08-14",now);assert not report["passed"] and not report["checks"]["morning_fact_exists"]
  (root/"bad.json").write_text("{",encoding="utf-8");m=maintenance(root,"2026-08-14",now);assert not m["passed"] and m["invalid_files"][0]["path"]=="bad.json"
def test_health_does_not_report_itself_missing_while_it_is_running():
 with TemporaryDirectory() as d:
  root=Path(d);now=datetime(2026,8,14,14,53,tzinfo=CHINA_TZ);report=health(root,"2026-08-14",now);missing={x["task"] for x in report["recovery"]["missing_due_tasks"]};assert "health_check" not in missing and {"paper_buy","paper_sell"}.isdisjoint(missing)
