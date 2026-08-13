"""V5 operational health, maintenance and recovery reports."""
from __future__ import annotations
from datetime import datetime
import hashlib,json,os
from pathlib import Path
from .core import CHINA_TZ
from .shadow_schedule import ShadowScheduler
from .paper import PaperLedger
from .ownership import load as load_ownership
from .fact_reader import latest
from .lineage_acceptance import audit as lineage_audit
from .jobs import load_universe

def _latest(root,kind,day,*,as_of=None):
    try:return latest(root,kind,day,as_of=as_of)
    except Exception:return None
def health(root,day,now):
    root=Path(root);morning=_latest(root,"morning_pools",day,as_of=now);confirmation=_latest(root,"confirmations",day,as_of=now);notifications=root/"notifications"/day
    ownership=load_ownership(root/"ownership.json");v5_owns_paper=ownership["paper_writer"]=="v5" and ownership.get("authorized") is True
    try:universe=load_universe(root,day,as_of=now,require_native=True);native_universe_exists=bool(universe.codes)
    except Exception:native_universe_exists=False
    lineage=lineage_audit(root,day,as_of=now)
    checks={"native_universe_exists":native_universe_exists,"morning_fact_exists":morning is not None,"confirmation_fact_exists":confirmation is not None,"morning_notification_accepted":False,"confirmation_notification_accepted":False,"lineage_accepted":lineage["passed"],"paper_ledger_reconciled":PaperLedger(root/"paper").reconcile()["passed"],"paper_writer_exclusive":ownership["paper_writer"] in {"v4","v5"}}
    for stage in ("morning","confirmation"):
        path=notifications/f"{stage}.json"
        checks[f"{stage}_notification_accepted"]=path.exists() and json.loads(path.read_text(encoding="utf-8")).get("outcome")=="ACCEPTED"
    # A running health task cannot have recorded its own SUCCESS yet.  Treating
    # that as a missed task makes every otherwise healthy 14:53 run fail.
    excluded=("health_check",) if v5_owns_paper else ("paper_sell","paper_buy","health_check")
    recovery=ShadowScheduler(root).recovery_report(day,now,excluded_tasks=excluded);report={"schema_version":"v5-health-v1","trade_date":day,"recorded_at":now.astimezone(CHINA_TZ).isoformat(),"mode":"production" if v5_owns_paper else "shadow_without_paper_writer","checks":checks,"lineage":lineage,"recovery":recovery,"production_complete":v5_owns_paper,"passed":all(checks.values()) and recovery["status"]=="CLEAN"};return report
def maintenance(root,day,now):
    root=Path(root);files=[];bad=[]
    for path in root.rglob("*.json"):
        try:raw=path.read_bytes();json.loads(raw.decode("utf-8"));files.append({"path":str(path.relative_to(root)),"sha256":hashlib.sha256(raw).hexdigest(),"bytes":len(raw)})
        except Exception as exc:bad.append({"path":str(path.relative_to(root)),"error":type(exc).__name__})
    report={"schema_version":"v5-maintenance-v1","trade_date":day,"recorded_at":now.astimezone(CHINA_TZ).isoformat(),"file_count":len(files),"files":files,"invalid_files":bad,"passed":not bad};out=root/"maintenance"/day/"manifest.json";out.parent.mkdir(parents=True,exist_ok=True);tmp=out.with_suffix(f".{os.getpid()}.tmp");tmp.write_text(json.dumps(report,ensure_ascii=False,sort_keys=True,separators=(",",":")),encoding="utf-8");os.replace(tmp,out);return report
