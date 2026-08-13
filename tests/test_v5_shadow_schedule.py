from datetime import datetime
from tempfile import TemporaryDirectory
from pathlib import Path
from v5.core import CHINA_TZ
from v5.shadow_schedule import ShadowScheduler,TASKS
def test_schedule_is_complete_disabled_and_has_no_external_side_effects():
    with TemporaryDirectory() as d:
        scheduler=ShadowScheduler(d);assert scheduler.validate()["passed"]
        inventory=scheduler.inventory();assert len(inventory["tasks"])==9;assert not inventory["notifications_enabled"] and not inventory["v4_writes_enabled"]
def test_missing_due_tasks_and_dependencies_are_reported():
    with TemporaryDirectory() as d:
        scheduler=ShadowScheduler(d);now=datetime(2026,8,13,14,51,0,tzinfo=CHINA_TZ)
        scheduler.record("morning_pool","2026-08-13","SUCCESS",now);report=scheduler.recovery_report("2026-08-13",now)
        names={x["task"] for x in report["missing_due_tasks"]};assert "morning_push" in names and "confirmation" in names and "paper_buy" in names
        confirmation=next(x for x in report["missing_due_tasks"] if x["task"]=="confirmation");assert "morning_pool" not in confirmation["blocked_by"] and "feature_freeze" in confirmation["blocked_by"]
def test_recovery_scope_can_explicitly_exclude_unowned_paper_tasks():
    with TemporaryDirectory() as d:
        scheduler=ShadowScheduler(d);now=datetime(2026,8,13,15,0,tzinfo=CHINA_TZ);report=scheduler.recovery_report("2026-08-13",now,excluded_tasks=("paper_sell","paper_buy"));assert report["excluded_tasks"]==["paper_buy","paper_sell"] and not ({"paper_buy","paper_sell"}&{x["task"] for x in report["missing_due_tasks"]})
def test_run_artifact_is_idempotent_and_immutable():
    with TemporaryDirectory() as d:
        scheduler=ShadowScheduler(d);now=datetime(2026,8,13,9,25,tzinfo=CHINA_TZ);first=scheduler.record("morning_pool","2026-08-13","SUCCESS",now,{"x":1});second=scheduler.record("morning_pool","2026-08-13","SUCCESS",now,{"x":1});assert first==second and len(list((Path(d)/"runs/2026-08-13").glob("*.json")))==1
