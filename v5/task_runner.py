"""Single V5 task entrypoint with immutable run artifacts."""
from __future__ import annotations
from datetime import datetime
import json,traceback
from pathlib import Path
from .core import CHINA_TZ
from .jobs import produce,freeze,confirm_frozen,paper_buy,paper_sell
from .notification import send
from .operations import health,maintenance
from .shadow_schedule import ShadowScheduler
from .alerts import send_failure
from .clock_gate import check as check_clock
from .ownership import load as load_ownership
from .calendar import TradingCalendar
from .challenger import (
    advance_context as advance_challenger_context,
    paper_buy as challenger_paper_buy,
    paper_sell as challenger_paper_sell,
    project_confirmation as project_challenger_confirmation,
    project_morning as project_challenger_morning,
    run_isolated as run_challenger_isolated,
)
from .paper_production import load_snapshot

WINDOWS={
    "morning_pool":((9,25,0),(9,25,39)),
    "morning_push":((9,25,0),(9,29,59)),
    "feature_freeze":((14,48,30),(14,49,59)),
    "confirmation":((14,50,0),(14,51,59)),
    "confirmation_push":((14,50,0),(14,52,59)),
    "health_check":((14,53,0),(15,9,59)),
    "maintenance":((15,10,0),(23,59,59)),
    "paper_sell":((9,30,0),(9,35,59)),
    "paper_buy":((14,50,0),(14,51,59)),
}
SAFE_DEPENDENCIES={"morning_push":("morning_pool",),"confirmation":("morning_pool","feature_freeze"),"confirmation_push":("confirmation",),"paper_buy":("confirmation",)}
HEALTH_DERIVED_CHECKS={"morning_fact_exists","morning_notification_accepted",
    "confirmation_fact_exists","confirmation_notification_accepted","lineage_accepted"}

def dependencies_for(root,task):
    dependencies=list(SAFE_DEPENDENCIES.get(task,()))
    ownership=load_ownership(Path(root)/"ownership.json")
    v5_owns_paper=ownership.get("paper_writer")=="v5" and ownership.get("authorized") is True
    return tuple(dependencies)

def inside_window(task,now):
    if task not in WINDOWS:return False
    start,end=WINDOWS[task];clock=(now.hour,now.minute,now.second)
    return start<=clock<=end

def run(root,task,*,now=None,failure_alert_env=None,clock_checker=None):
    root=Path(root);now=(now or datetime.now(CHINA_TZ)).astimezone(CHINA_TZ);day=now.date().isoformat();scheduler=ShadowScheduler(root);outcome="SUCCESS";details={};missing=[]
    try:
        if TradingCalendar().is_open(now.date()) is not True:raise ValueError(f"V5 task rejected non-trading day: {day}")
        if not inside_window(task,now):raise ValueError(f"V5 task outside allowed window: {task} at {now.isoformat()}")
        if task in {"morning_pool","feature_freeze","paper_sell"}:
            clock=(clock_checker or check_clock)()
            if not clock.get("passed"):raise ValueError(f"V5 causal clock rejected: {clock.get('reason','UNKNOWN')}")
            details["clock_gate"]=clock
        missing=[name for name in dependencies_for(root,task) if name not in scheduler.successful_tasks(day)]
        if missing:raise ValueError(f"V5 task dependencies incomplete: {', '.join(missing)}")
        if task=="morning_pool":
            details.update(produce(root,"morning",now=now))
            details["challenger"]=run_challenger_isolated(root,"morning_pool",now,lambda:project_challenger_morning(root,now))
        elif task=="morning_push":details=send(root,day,"morning",root.parent/".env",as_of=now)
        elif task=="feature_freeze":
            details.update(freeze(root,now=now))
            snapshot=load_snapshot(root/"snapshots"/day/f"{details['snapshot_id']}.json")
            details["challenger"]=run_challenger_isolated(root,"feature_freeze",now,lambda:advance_challenger_context(root,now,snapshot))
        elif task=="confirmation":
            details=confirm_frozen(root,now=now)
            details["challenger"]=run_challenger_isolated(root,"confirmation",now,lambda:project_challenger_confirmation(root,now))
        elif task=="confirmation_push":details=send(root,day,"confirmation",root.parent/".env",as_of=now)
        elif task=="paper_buy":
            details=paper_buy(root,now=now)
            if details.get("outcome") not in {"FILLED","NO_CANDIDATE"}:raise RuntimeError(f"V5 paper buy rejected: {details.get('reason',details.get('outcome'))}")
            details["challenger"]=run_challenger_isolated(root,"paper_buy",now,lambda:challenger_paper_buy(root,now))
        elif task=="paper_sell":
            details=paper_sell(root,now=now)
            if details.get("outcome") not in {"FILLED","NO_POSITIONS_OR_BASELINE"}:raise RuntimeError(f"V5 paper sell incomplete: {details.get('outcome')}")
            snapshot_id=details.get("snapshot_id","")
            details["challenger"]=run_challenger_isolated(
                root,"paper_sell",now,
                (lambda:challenger_paper_sell(root,load_snapshot(root/"snapshots"/day/f"{snapshot_id}.json"),now))
                if snapshot_id else (lambda:{"outcome":"NO_POSITIONS","events":[]}),
            )
        elif task=="health_check":details=health(root,day,now);outcome="SUCCESS" if details["passed"] else "FAILED"
        elif task=="maintenance":details=maintenance(root,day,now);outcome="SUCCESS" if details["passed"] else "FAILED"
        else:raise ValueError("unsupported V5 task")
    except Exception as exc:
        outcome="FAILED";details={"error_type":type(exc).__name__,"error":str(exc)}
        dependency_failure=str(exc).startswith("V5 task dependencies incomplete:")
        upstream_alerted=scheduler.failed_tasks_with_accepted_alerts(day) if dependency_failure else set()
        if dependency_failure and missing and set(missing)<=upstream_alerted:
            details["failure_alert_suppressed"]="UPSTREAM_ROOT_CAUSE_ALREADY_ALERTED"
        elif failure_alert_env is not None:
            try:details["failure_alert"]=send_failure(root,day,task,str(exc),failure_alert_env)
            except Exception as alert_exc:details["failure_alert_error"]=f"{type(alert_exc).__name__}: {alert_exc}"
    if outcome=="FAILED" and failure_alert_env is not None and not any(key in details for key in ("failure_alert","failure_alert_error","failure_alert_suppressed")):
        failed_checks=sorted(key for key,value in details.get("checks",{}).items() if value is not True)
        reason=details.get("error") or f"V5 {task} reported failed checks: {', '.join(failed_checks) or 'UNKNOWN'}"
        prior_alerts=scheduler.failed_tasks_with_accepted_alerts(day)
        if task=="health_check" and failed_checks and set(failed_checks)<=HEALTH_DERIVED_CHECKS and prior_alerts:
            details["failure_alert_suppressed"]="UPSTREAM_ROOT_CAUSE_ALREADY_ALERTED"
        else:
            try:details["failure_alert"]=send_failure(root,day,task,reason,failure_alert_env)
            except Exception as alert_exc:details["failure_alert_error"]=f"{type(alert_exc).__name__}: {alert_exc}"
    record=scheduler.record(task,day,outcome,now,details);return {"passed":outcome=="SUCCESS","run":record}
