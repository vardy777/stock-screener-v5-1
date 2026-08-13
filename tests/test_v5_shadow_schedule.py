from datetime import datetime
from tempfile import TemporaryDirectory
from v5.core import CHINA_TZ
from v5.shadow_schedule import ShadowScheduler,TASKS
def test_schedule_is_complete_disabled_and_has_no_external_side_effects():
    with TemporaryDirectory() as d:
        scheduler=ShadowScheduler(d);assert scheduler.validate()["passed"]
        inventory=scheduler.inventory();assert len(inventory["tasks"])==9;assert not inventory["notifications_enabled"] and not inventory["v4_writes_enabled"]
def test_missing_due_tasks_and_dependencies_are_reported():
    with TemporaryDirectory() as d:
        scheduler=ShadowScheduler(d);now=datetime(2026,8,13,14,50,30,tzinfo=CHINA_TZ)
        scheduler.record("morning_warmup","2026-08-13","SUCCESS",now);report=scheduler.recovery_report("2026-08-13",now)
        names={x["task"] for x in report["missing_due_tasks"]};assert "morning_pool" in names and "confirmation" in names and "paper_buy" in names
        confirmation=next(x for x in report["missing_due_tasks"] if x["task"]=="confirmation");assert "morning_pool" in confirmation["blocked_by"]
