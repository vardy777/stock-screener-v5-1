"""Disabled-by-default V5 shadow task graph. No notifications or V4 writes."""
from __future__ import annotations
from dataclasses import dataclass,asdict
from datetime import datetime,timedelta
import hashlib,json
from pathlib import Path
import os
from .core import CHINA_TZ,ContractViolation

@dataclass(frozen=True)
class TaskV1:
    name:str;time:str;depends_on:tuple[str,...];entrypoint:str;external_notifications:bool=False;broker_orders:bool=False;v4_writes:bool=False
TASKS=(TaskV1("morning_pool","09:24:30",(),"v5.task_runner morning_pool"),TaskV1("morning_push","09:25:20",("morning_pool",),"v5.task_runner morning_push",True),TaskV1("paper_sell","09:30:10",(),"v5.task_runner paper_sell"),TaskV1("feature_freeze","14:49:00",(),"v5.task_runner feature_freeze"),TaskV1("confirmation","14:50:00",("morning_pool","feature_freeze"),"v5.task_runner confirmation"),TaskV1("confirmation_push","14:50:30",("confirmation",),"v5.task_runner confirmation_push",True),TaskV1("paper_buy","14:50:40",("confirmation",),"v5.task_runner paper_buy"),TaskV1("health_check","14:53:00",("confirmation","confirmation_push","paper_buy"),"v5.task_runner health_check"),TaskV1("maintenance","15:10:00",("health_check",),"v5.task_runner maintenance"))
class ShadowScheduler:
    def __init__(self,root,*,enabled=False):self.root=Path(root);self.enabled=enabled
    def inventory(self):return {"schema_version":"v5-shadow-schedule-v1","enabled":self.enabled,"notifications_enabled":False,"broker_orders_enabled":False,"v4_writes_enabled":False,"tasks":[asdict(x) for x in TASKS]}
    def validate(self):
        names={x.name for x in TASKS};checks={"unique_names":len(names)==len(TASKS),"exactly_nine_business_tasks":len(TASKS)==9,"dependencies_exist":all(set(x.depends_on)<=names for x in TASKS),"exactly_two_notifications":sum(x.external_notifications for x in TASKS)==2,"no_broker_orders":not any(x.broker_orders for x in TASKS),"no_v4_writes":not any(x.v4_writes for x in TASKS),"disabled_by_default":self.enabled is False};return {"passed":all(checks.values()),"checks":checks}
    def record(self,task,trade_date,outcome,at,details=None):
        if task not in {x.name for x in TASKS}:raise ContractViolation("unknown shadow task")
        row={"schema_version":"v5-shadow-run-v1","task":task,"trade_date":trade_date,"outcome":outcome,"recorded_at":at.astimezone(CHINA_TZ).isoformat(),"details":details or {}};row["run_id"]="run1-"+hashlib.sha256(json.dumps(row,sort_keys=True,separators=(",",":")).encode()).hexdigest()[:24]
        path=self.root/"runs"/trade_date/f"{row['run_id']}.json";path.parent.mkdir(parents=True,exist_ok=True);raw=json.dumps(row,ensure_ascii=False,sort_keys=True,separators=(",",":"))
        if path.exists():
            if path.read_text(encoding="utf-8")!=raw:raise ContractViolation("immutable shadow run collision")
            return row
        tmp=path.with_suffix(f".{os.getpid()}.tmp");tmp.write_text(raw,encoding="utf-8")
        try:os.link(tmp,path)
        except FileExistsError:
            if path.read_text(encoding="utf-8")!=raw:raise ContractViolation("immutable shadow run collision")
        finally:tmp.unlink(missing_ok=True)
        return row
    def recovery_report(self,trade_date,now,*,excluded_tasks=()):
        excluded=set(excluded_tasks);unknown=excluded-{x.name for x in TASKS}
        if unknown:raise ContractViolation("unknown excluded shadow task")
        rows=[]
        for path in (self.root/"runs"/trade_date).glob("*.json") if (self.root/"runs"/trade_date).exists() else []:rows.append(json.loads(path.read_text(encoding="utf-8")))
        completed={x["task"] for x in rows if x["outcome"]=="SUCCESS"};due=[]
        for task in TASKS:
            if task.name in excluded:continue
            scheduled=datetime.fromisoformat(f"{trade_date}T{task.time}+08:00")
            if scheduled<=now.astimezone(CHINA_TZ) and task.name not in completed:due.append({"task":task.name,"scheduled_at":scheduled.isoformat(),"blocked_by":[x for x in task.depends_on if x not in completed]})
        return {"schema_version":"v5-shadow-recovery-v1","trade_date":trade_date,"excluded_tasks":sorted(excluded),"missing_due_tasks":due,"status":"RECOVERY_REQUIRED" if due else "CLEAN"}
