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
from .push import load_notification_receipt
from .offline_storage import atomic_json_write

ROOT=Path(__file__).resolve().parents[1]
COMMANDS={
 "morning_decision":[sys.executable,"-X","utf8",str(ROOT/"v4/scripts/decision_job.py"),"morning"],
 "morning_push":[sys.executable,"-X","utf8",str(ROOT/"v4/scripts/morning_push.py")],
 "feature_freeze":[sys.executable,"-X","utf8",str(ROOT/"v4/scripts/feature_freeze_job.py")],
 "confirmation_decision":[sys.executable,"-X","utf8",str(ROOT/"v4/scripts/decision_job.py"),"confirmation"],
 "confirmation_push":[sys.executable,"-X","utf8",str(ROOT/"v4/scripts/afternoon_push.py")],
 "health_check":[sys.executable,"-X","utf8",str(ROOT/"v4/scripts/health_job.py")],
 "maintenance":[sys.executable,"-X","utf8",str(ROOT/"v4/scripts/maintenance_job.py")],
}
DEPENDENCIES={"morning_push":("morning_decision",),"confirmation_decision":("feature_freeze","morning_decision"),
 "confirmation_push":("confirmation_decision",),"paper_buy":("confirmation_decision",),
 "health_check":("confirmation_decision",),"maintenance":("health_check",)}
# Some downstream jobs must run after an upstream terminal result even when
# that result failed.  Confirmation must publish an auditable empty/paper-only
# decision when the strict 14:49 capture fails, and maintenance must prepare
# the next session even when today's health report failed.
TERMINAL_DEPENDENCIES={
 ("confirmation_decision","feature_freeze"),
 ("maintenance","health_check"),
}

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
        key=(f"v4-morning:{day}" if task=="morning_push" else f"v4-afternoon:{day}")
        parent=(chain.get("morning",{}).get("pool_id","") if task=="morning_push" else chain.get("confirmation",{}).get("decision_id",""))
        receipt=load_notification_receipt(key)
        if receipt is None or receipt.parent_entity_id!=parent or receipt.outcome!="ACCEPTED": raise RuntimeError("CURRENT_NOTIFICATION_RECEIPT_MISSING")
        value=receipt.to_dict(); return receipt.notification_id,value,(parent,)
    report_path=(ROOT/"phase1/data/execution_snapshots/health"/f"{day}_signal_buy.json" if task=="health_check"
                 else ROOT/"phase1/data/overnight/daily_maintenance_report.json")
    value=json.loads(report_path.read_text(encoding="utf-8"))
    if value.get("passed") is not True: raise RuntimeError(f"{task.upper()}_REPORT_FAILED")
    value={**value,"source_report_sha256":hashlib.sha256(report_path.read_bytes()).hexdigest()}
    return ("health1-" if task=="health_check" else "maintenance1-")+_digest(value)[:24],value,()

def _paths(task,day):
    root=ROOT/"v4/data/p4/outputs"/day
    return root/task,root/f"{task}.json"

def _latest(task,day):
    _,path=_paths(task,day)
    try: return TaskOutputV1.from_mapping(json.loads(path.read_text(encoding="utf-8"))).to_dict()
    except (OSError,ValueError,TypeError): return {}

def _next_attempt(task,day):
    directory,_=_paths(task,day)
    return len(list(directory.glob("attempt-*.json")))+1 if directory.is_dir() else 1

def _persist(output):
    directory,latest=_paths(output.task_name,output.trade_date); directory.mkdir(parents=True,exist_ok=True)
    target=directory/f"attempt-{output.attempt:04d}.json"
    if target.exists():
        existing=TaskOutputV1.from_mapping(json.loads(target.read_text(encoding="utf-8")))
        if existing.output_id!=output.output_id: raise RuntimeError("TASK_ATTEMPT_IMMUTABLE_COLLISION")
    else: atomic_json_write(target,output.to_dict())
    atomic_json_write(latest,output.to_dict()); return output.to_dict()

def _heartbeat(task,day,attempt,task_status,*,output_id="",reason_code="",now=None):
    current=(now or datetime.now(CHINA_TZ)).astimezone(CHINA_TZ)
    value={"schema_version":"p4-production-heartbeat-v1","status":"ALIVE" if task_status in {"STARTED","SUCCEEDED"} else "DEGRADED",
      "task_name":task,"trade_date":day,"attempt":attempt,"task_status":task_status,"output_id":output_id,
      "reason_code":reason_code,"recorded_at":current.isoformat(timespec="seconds")}
    atomic_json_write(ROOT/"v4/data/p4/heartbeat.json",value); return value

def run(task,*,authorization_file,now=None,preflight=False):
    require_authorized_owner(authorization_file,resource="task_receipts",owner="P4")
    current=(now or datetime.now(CHINA_TZ)).astimezone(CHINA_TZ); day=current.date().isoformat()
    if preflight: return {"passed":True,"task":task,"command_bound":task in COMMANDS or task in {"paper_buy","paper_sell"},"production_mutated":False}
    existing=_latest(task,day)
    if existing.get("status")=="SUCCEEDED":
        _heartbeat(task,day,existing.get("attempt",1),"SUCCEEDED",output_id=existing["output_id"],now=current); return existing
    attempt=_next_attempt(task,day); _heartbeat(task,day,attempt,"STARTED",now=current)
    deadline=time.monotonic()+85
    for dependency in DEPENDENCIES.get(task,()):
        dependency_output=_latest(dependency,day)
        acceptable=(
            {"SUCCEEDED","FAILED","BLOCKED"}
            if (task,dependency) in TERMINAL_DEPENDENCIES else {"SUCCEEDED"}
        )
        while dependency_output.get("status") not in acceptable and time.monotonic()<deadline:
            time.sleep(1); dependency_output=_latest(dependency,day)
        if dependency_output.get("status") not in acceptable:
            blocked=TaskOutputV1.build(task_name=task,trade_date=day,status="BLOCKED",
                reason_code=f"DEPENDENCY_NOT_SUCCEEDED:{dependency}",recorded_at=current,attempt=attempt)
            result=_persist(blocked); _heartbeat(task,day,attempt,"BLOCKED",output_id=blocked.output_id,reason_code=blocked.reason_code,now=current); return result
    process=None
    if task not in {"paper_buy","paper_sell"}:
      try:
        process=subprocess.run(COMMANDS[task],cwd=ROOT,capture_output=True,text=True,encoding="utf-8",errors="replace",timeout=2700)
      except Exception as exc:
        output=TaskOutputV1.build(task_name=task,trade_date=day,status="FAILED",
            reason_code=f"PROCESS_FAILED:{type(exc).__name__}",recorded_at=current,attempt=attempt)
        result=_persist(output); _heartbeat(task,day,attempt,"FAILED",output_id=output.output_id,reason_code=output.reason_code,now=current); return result
      else:
        if process.returncode:
            output=TaskOutputV1.build(task_name=task,trade_date=day,status="FAILED",reason_code=f"EXIT_{process.returncode}",recorded_at=current,attempt=attempt)
            result=_persist(output); _heartbeat(task,day,attempt,"FAILED",output_id=output.output_id,reason_code=output.reason_code,now=current); return result
    try:
        entity_id,payload,inputs=_entity(task,day,process,authorization_file,current)
    except Exception as exc:
        failed=TaskOutputV1.build(task_name=task,trade_date=day,status="FAILED",
            reason_code=f"ENTITY_PROJECTION_FAILED:{type(exc).__name__}",recorded_at=current,attempt=attempt)
        result=_persist(failed); _heartbeat(task,day,attempt,"FAILED",output_id=failed.output_id,reason_code=failed.reason_code,now=current); return result
    output=TaskOutputV1.build(task_name=task,trade_date=day,status="SUCCEEDED",reason_code="OK",recorded_at=current,
        entity_kind=OUTPUT_KINDS[task],entity_id=entity_id,entity_payload=payload,input_ids=inputs,attempt=attempt)
    result=_persist(output); _heartbeat(task,day,attempt,"SUCCEEDED",output_id=output.output_id,now=current); return result
