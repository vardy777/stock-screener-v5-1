"""Single V5 task entrypoint with immutable run artifacts."""
from __future__ import annotations
from datetime import datetime
import json,traceback
from pathlib import Path
from .core import CHINA_TZ
from .jobs import produce,freeze,confirm_frozen
from .notification import send
from .operations import health,maintenance
from .shadow_schedule import ShadowScheduler
from .alerts import send_failure

WINDOWS={
    "morning_pool":((9,24,20),(9,25,19)),
    "morning_push":((9,25,0),(9,29,59)),
    "feature_freeze":((14,48,30),(14,49,59)),
    "confirmation":((14,50,0),(14,51,59)),
    "confirmation_push":((14,50,0),(14,52,59)),
    "health_check":((14,53,0),(15,9,59)),
    "maintenance":((15,10,0),(23,59,59)),
}
SAFE_DEPENDENCIES={"morning_push":("morning_pool",),"confirmation":("morning_pool","feature_freeze"),"confirmation_push":("confirmation",),"health_check":("morning_pool","morning_push","feature_freeze","confirmation","confirmation_push"),"maintenance":("health_check",)}

def inside_window(task,now):
    if task not in WINDOWS:return False
    start,end=WINDOWS[task];clock=(now.hour,now.minute,now.second)
    return start<=clock<=end

def run(root,task,*,now=None,failure_alert_env=None):
    root=Path(root);now=(now or datetime.now(CHINA_TZ)).astimezone(CHINA_TZ);day=now.date().isoformat();scheduler=ShadowScheduler(root);outcome="SUCCESS";details={}
    try:
        if not inside_window(task,now):raise ValueError(f"V5 task outside allowed window: {task} at {now.isoformat()}")
        missing=[name for name in SAFE_DEPENDENCIES.get(task,()) if name not in scheduler.successful_tasks(day)]
        if missing:raise ValueError(f"V5 task dependencies incomplete: {', '.join(missing)}")
        if task=="morning_pool":details=produce(root,"morning",now=now)
        elif task=="morning_push":details=send(root,day,"morning",root.parent/".env",as_of=now)
        elif task=="feature_freeze":details=freeze(root,now=now)
        elif task=="confirmation":details=confirm_frozen(root,now=now)
        elif task=="confirmation_push":details=send(root,day,"confirmation",root.parent/".env",as_of=now)
        elif task=="health_check":details=health(root,day,now);outcome="SUCCESS" if details["passed"] else "FAILED"
        elif task=="maintenance":details=maintenance(root,day,now);outcome="SUCCESS" if details["passed"] else "FAILED"
        else:raise ValueError("unsupported V5 task")
    except Exception as exc:
        outcome="FAILED";details={"error_type":type(exc).__name__,"error":str(exc)}
        if failure_alert_env is not None:
            try:details["failure_alert"]=send_failure(root,day,task,str(exc),failure_alert_env)
            except Exception as alert_exc:details["failure_alert_error"]=f"{type(alert_exc).__name__}: {alert_exc}"
    record=scheduler.record(task,day,outcome,now,details);return {"passed":outcome=="SUCCESS","run":record}
