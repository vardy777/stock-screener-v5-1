from datetime import datetime
from v5.core import CHINA_TZ
from v5.live_acceptance import build,save
import json


def test_live_acceptance_is_read_only_and_incomplete_without_window_evidence(tmp_path):
    before=list(tmp_path.rglob("*"));report=build(tmp_path,"2026-08-14",now=datetime(2026,8,14,8,0,tzinfo=CHINA_TZ));after=list(tmp_path.rglob("*"))
    assert before==after and report["complete"] is False and report["research_locked"] is True and report["broker_orders"] is False

def test_live_acceptance_selects_latest_readiness_by_entity_time(tmp_path):
    directory=tmp_path/"preflight/2026-08-14";directory.mkdir(parents=True)
    (directory/"z.json").write_text(json.dumps({"recorded_at":"2026-08-14T08:00:00+08:00","passed":False}),encoding="utf-8")
    (directory/"a.json").write_text(json.dumps({"recorded_at":"2026-08-14T08:30:00+08:00","passed":True}),encoding="utf-8")
    report=build(tmp_path,"2026-08-14",now=datetime(2026,8,14,9,0,tzinfo=CHINA_TZ));assert report["readiness"]["latest_passed"] is True

def test_live_acceptance_save_is_content_addressed_and_idempotent(tmp_path):
    report=build(tmp_path,"2026-08-14",now=datetime(2026,8,14,15,20,tzinfo=CHINA_TZ));first=save(tmp_path,report);second=save(tmp_path,report)
    assert first["report_id"]==second["report_id"] and len(list((tmp_path/"live_acceptance/2026-08-14").glob("*.json")))==1
