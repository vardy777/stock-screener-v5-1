from datetime import datetime
from v5.core import CHINA_TZ
from v5.live_acceptance import build,save
from v5.shadow_schedule import ShadowScheduler
import json


def test_live_acceptance_is_read_only_and_incomplete_without_window_evidence(tmp_path):
    before=list(tmp_path.rglob("*"));report=build(tmp_path,"2026-08-14",now=datetime(2026,8,14,8,0,tzinfo=CHINA_TZ));after=list(tmp_path.rglob("*"))
    assert before==after and report["complete"] is False and report["research_locked"] is True and report["broker_orders"] is False
    assert set(report["required_tasks"])=={"morning_pool","morning_push","paper_sell","feature_freeze","confirmation","confirmation_push","paper_buy","health_check","maintenance"}

def test_live_acceptance_selects_latest_readiness_by_entity_time(tmp_path):
    import hashlib
    directory=tmp_path/"preflight/2026-08-14";directory.mkdir(parents=True)
    for recorded,passed in (("2026-08-14T08:00:00+08:00",False),("2026-08-14T08:30:00+08:00",True)):
        row={"schema_version":"v5-readiness-preflight-v2","recorded_at":recorded,"trade_date":"2026-08-14","diagnostic_only":True,"strict_evidence":False,"passed":passed};row["report_id"]="preflight1-"+hashlib.sha256(json.dumps(row,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode()).hexdigest()[:24];(directory/f"{row['report_id']}.json").write_text(json.dumps(row),encoding="utf-8")
    report=build(tmp_path,"2026-08-14",now=datetime(2026,8,14,9,0,tzinfo=CHINA_TZ));assert report["readiness"]["latest_passed"] is True

def test_live_acceptance_rejects_tampered_readiness_report(tmp_path):
    directory=tmp_path/"preflight/2026-08-14";directory.mkdir(parents=True);(directory/"preflight1-forged.json").write_text(json.dumps({"trade_date":"2026-08-14","passed":True,"diagnostic_only":True,"strict_evidence":False,"report_id":"preflight1-forged"}),encoding="utf-8")
    report=build(tmp_path,"2026-08-14",now=datetime(2026,8,14,15,20,tzinfo=CHINA_TZ));assert report["readiness"]["validation_errors"] and report["readiness"]["latest_passed"] is None and not report["complete"]

def test_top_level_notification_truth_requires_full_lineage_not_only_http_200(tmp_path):
    day="2026-08-14";directory=tmp_path/"notifications"/day;directory.mkdir(parents=True)
    for stage in ("morning","confirmation"):(directory/f"{stage}.json").write_text(json.dumps({"outcome":"ACCEPTED","response_code":200,"parent_entity_id":"forged","payload_sha256":"forged"}),encoding="utf-8")
    report=build(tmp_path,day,now=datetime(2026,8,14,15,20,tzinfo=CHINA_TZ));assert report["notifications"]=={"morning":False,"confirmation":False} and not report["complete"]

def test_live_acceptance_save_is_content_addressed_and_idempotent(tmp_path):
    report=build(tmp_path,"2026-08-14",now=datetime(2026,8,14,15,20,tzinfo=CHINA_TZ));first=save(tmp_path,report);second=save(tmp_path,report)
    assert first["report_id"]==second["report_id"] and len(list((tmp_path/"live_acceptance/2026-08-14").glob("*.json")))==1

def test_live_acceptance_validates_run_hash_and_exposes_latest_attempt(tmp_path):
    day="2026-08-14";scheduler=ShadowScheduler(tmp_path);at=datetime(2026,8,14,9,24,30,tzinfo=CHINA_TZ)
    scheduler.record("morning_pool",day,"SUCCESS",at,{})
    scheduler.record("morning_pool",day,"FAILED",at.replace(second=31),{"error":"late failure"})
    report=build(tmp_path,day,now=at.replace(hour=15,minute=20));summary=report["tasks"]["morning_pool"]
    assert summary["attempts"]==2 and summary["ever_succeeded"] is True and summary["latest_outcome"]=="FAILED" and not report["complete"]
    path=next((tmp_path/"runs"/day).glob("*.json"));row=json.loads(path.read_text());row["outcome"]="SUCCESS" if row["outcome"]!="SUCCESS" else "FAILED";path.write_text(json.dumps(row),encoding="utf-8")
    report=build(tmp_path,day,now=at.replace(hour=15,minute=20));assert report["run_validation_errors"] and not report["complete"]
