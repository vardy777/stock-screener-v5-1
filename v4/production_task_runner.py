"""Authorized P4 scheduler leaf runner with immutable final output projection."""
from __future__ import annotations
from datetime import datetime
import hashlib,json,subprocess,sys,time
from pathlib import Path
from .candidate_journal import CandidateJournal
from .execution import CHINA_TZ
from .p3_production import execute as execute_p3
from .production_gate import require_authorized_owner
from .replay_contracts import FeatureContextV1
from .task_output_contract import OUTPUT_KINDS,TaskOutputV1

ROOT=Path(__file__).resolve().parents[1]
COMMANDS={
 "morning_decision":[sys.executable,"-X","utf8",str(ROOT/"v4/scripts/decision_job.py"),"morning"],
 "morning_push":[sys.executable,"-X","utf8",str(ROOT/"v4/scripts/morning_push.py")],
 "feature_freeze":[sys.executable,"-X","utf8",str(ROOT/"phase1/scripts/capture_signal_features.py")],
 "confirmation_decision":[sys.executable,"-X","utf8",str(ROOT/"v4/scripts/decision_job.py"),"confirmation"],
 "confirmation_push":[sys.executable,"-X","utf8",str(ROOT/"v4/scripts/afternoon_push.py")],
 "health_check":["powershell.exe","-NoProfile","-NonInteractive","-ExecutionPolicy","Bypass","-File",str(ROOT/"phase1/scripts/run_scheduled_health.ps1"),"-Mode","close"],
 "maintenance":["powershell.exe","-NoProfile","-NonInteractive","-ExecutionPolicy","Bypass","-File",str(ROOT/"phase1/scripts/run_daily_maintenance.ps1")],
}
DEPENDENCIES={"morning_push":("morning_decision",),"confirmation_decision":("feature_freeze","morning_decision"),
 "confirmation_push":("confirmation_decision",),"paper_buy":("confirmation_decision",),
 "health_check":("confirmation_decision",),"maintenance":("health_check",)}

def _digest(value): return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode()).hexdigest()

def _entity(task,day,process=None,authorization_file=None,now=None):
    chain=CandidateJournal().load(day)
    if task=="morning_decision":
        value=chain.get("morning",{}); return value.get("pool_id",""),value,()
    if task=="confirmation_decision":
        value=chain.get("confirmation",{}); inputs=(value.get("morning_pool_id",""),value.get("lineage",{}).get("feature_context_id","")); return value.get("decision_id",""),value,inputs
    if task=="feature_freeze":
        value=FeatureContextV1.load(ROOT/"v4/data/replay_context"/f"{day}.json").to_dict(); return value["context_id"],value,()
    if task in {"paper_buy","paper_sell"}:
        value=execute_p3("buy" if task=="paper_buy" else "sell",authorization_file=authorization_file,now=now); return value["batch_id"],value,tuple(x for x in (value.get("decision_id"),) if x)
    if task in {"morning_push","confirmation_push"}:
        source=ROOT/"v4/data/push_receipts.json"; value=json.loads(source.read_text(encoding="utf-8")); entity="notification1-"+_digest(value)[:24]
        parent=(chain.get("morning",{}).get("pool_id","") if task=="morning_push" else chain.get("confirmation",{}).get("decision_id","")); return entity,value,(parent,)
    value={"task_name":task,"trade_date":day,"exit_code":process.returncode,"stdout_sha256":hashlib.sha256(process.stdout.encode()).hexdigest(),"stderr_sha256":hashlib.sha256(process.stderr.encode()).hexdigest()}
    return ("health1-" if task=="health_check" else "maintenance1-")+_digest(value)[:24],value,()

def run(task,*,authorization_file,now=None,preflight=False):
    require_authorized_owner(authorization_file,resource="task_receipts",owner="P4")
    current=(now or datetime.now(CHINA_TZ)).astimezone(CHINA_TZ); day=current.date().isoformat()
    if preflight: return {"passed":True,"task":task,"command_bound":task in COMMANDS or task in {"paper_buy","paper_sell"},"production_mutated":False}
    output_path=ROOT/"v4/data/p4/outputs"/day/f"{task}.json"
    if output_path.exists(): return json.loads(output_path.read_text(encoding="utf-8"))
    deadline=time.monotonic()+85
    for dependency in DEPENDENCIES.get(task,()):
        source=output_path.parent/f"{dependency}.json"
        while not source.exists() and time.monotonic()<deadline: time.sleep(1)
        if not source.exists() or json.loads(source.read_text(encoding="utf-8")).get("status")!="SUCCEEDED":
            blocked=TaskOutputV1.build(task_name=task,trade_date=day,status="BLOCKED",
                reason_code=f"DEPENDENCY_NOT_SUCCEEDED:{dependency}",recorded_at=current)
            output_path.parent.mkdir(parents=True,exist_ok=True); output_path.write_text(json.dumps(blocked.to_dict(),ensure_ascii=False,indent=2),encoding="utf-8")
            return blocked.to_dict()
    process=None
    if task not in {"paper_buy","paper_sell"}:
        process=subprocess.run(COMMANDS[task],cwd=ROOT,capture_output=True,text=True,encoding="utf-8",errors="replace",timeout=2700)
        if process.returncode:
            output=TaskOutputV1.build(task_name=task,trade_date=day,status="FAILED",reason_code=f"EXIT_{process.returncode}",recorded_at=current)
            output_path.parent.mkdir(parents=True,exist_ok=True); output_path.write_text(json.dumps(output.to_dict(),ensure_ascii=False,indent=2),encoding="utf-8"); return output.to_dict()
    try:
        entity_id,payload,inputs=_entity(task,day,process,authorization_file,current)
    except Exception as exc:
        failed=TaskOutputV1.build(task_name=task,trade_date=day,status="FAILED",
            reason_code=f"ENTITY_PROJECTION_FAILED:{type(exc).__name__}",recorded_at=current)
        output_path.parent.mkdir(parents=True,exist_ok=True); output_path.write_text(json.dumps(failed.to_dict(),ensure_ascii=False,indent=2),encoding="utf-8")
        return failed.to_dict()
    output=TaskOutputV1.build(task_name=task,trade_date=day,status="SUCCEEDED",reason_code="OK",recorded_at=current,
        entity_kind=OUTPUT_KINDS[task],entity_id=entity_id,entity_payload=payload,input_ids=inputs)
    output_path.parent.mkdir(parents=True,exist_ok=True); temporary=output_path.with_suffix(".tmp"); temporary.write_text(json.dumps(output.to_dict(),ensure_ascii=False,indent=2),encoding="utf-8"); temporary.replace(output_path)
    return output.to_dict()
