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

def run(root,task,*,now=None):
    root=Path(root);now=(now or datetime.now(CHINA_TZ)).astimezone(CHINA_TZ);day=now.date().isoformat();scheduler=ShadowScheduler(root);outcome="SUCCESS";details={}
    try:
        if task=="morning_pool":details=produce(root,"morning",now=now)
        elif task=="morning_push":details=send(root,day,"morning",root.parent/".env")
        elif task=="feature_freeze":details=freeze(root,now=now)
        elif task=="confirmation":details=confirm_frozen(root,now=now)
        elif task=="confirmation_push":details=send(root,day,"confirmation",root.parent/".env")
        elif task=="health_check":details=health(root,day,now);outcome="SUCCESS" if details["passed"] else "FAILED"
        elif task=="maintenance":details=maintenance(root,day,now);outcome="SUCCESS" if details["passed"] else "FAILED"
        else:raise ValueError("unsupported V5 task")
    except Exception as exc:outcome="FAILED";details={"error_type":type(exc).__name__,"error":str(exc)}
    record=scheduler.record(task,day,outcome,now,details);return {"passed":outcome=="SUCCESS","run":record}
