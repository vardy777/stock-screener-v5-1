"""Read-only V5 live-window evidence summary. Never mutates facts or sends."""
from __future__ import annotations
from datetime import datetime
import json
from pathlib import Path
from .core import CHINA_TZ
from .fact_reader import latest
from .lineage_acceptance import audit as lineage_audit
from .paper import PaperLedger


def _latest(root,kind,day,predicate=None):
    try:return latest(root,kind,day,predicate=predicate)
    except Exception:return None


def build(root,day,*,now=None):
    root=Path(root);current=(now or datetime.now(CHINA_TZ)).astimezone(CHINA_TZ)
    readiness=[]
    for path in (root/"preflight"/day).glob("*.json") if (root/"preflight"/day).exists() else []:
        try:readiness.append(json.loads(path.read_text(encoding="utf-8")))
        except Exception:continue
    readiness.sort(key=lambda row:(row.get("recorded_at",""),row.get("report_id","")))
    runs=[]
    for path in (root/"runs"/day).glob("*.json") if (root/"runs"/day).exists() else []:
        try:runs.append(json.loads(path.read_text(encoding="utf-8")))
        except Exception:continue
    accepted_receipts={}
    for stage in ("morning","confirmation"):
        path=root/"notifications"/day/f"{stage}.json"
        if path.exists():
            try:row=json.loads(path.read_text(encoding="utf-8"));accepted_receipts[stage]=row.get("outcome")=="ACCEPTED" and row.get("response_code")==200
            except Exception:accepted_receipts[stage]=False
        else:accepted_receipts[stage]=False
    morning=_latest(root,"acquisition",day,lambda row:row.get("stage")=="morning");signal=_latest(root,"acquisition",day,lambda row:row.get("stage")=="signal")
    completed={row.get("task"):row.get("outcome") for row in sorted(runs,key=lambda row:row.get("recorded_at",""))}
    ledger=PaperLedger(root/"paper")
    report={"schema_version":"v5-live-acceptance-summary-v1","trade_date":day,"observed_at":current.isoformat(),"research_locked":True,"broker_orders":False,"readiness":{"attempts":len(readiness),"latest_passed":readiness[-1].get("passed") if readiness else None,"latest":readiness[-1] if readiness else None},"tasks":completed,"morning_acquisition":morning,"signal_acquisition":signal,"notifications":accepted_receipts,"paper":{"reconciled":ledger.reconcile()["passed"],"recovery":ledger.recovery_report()["status"],"round_trips":len(ledger.round_trips())}}
    report["lineage"]=lineage_audit(root,day,as_of=current) if morning and signal else {"passed":False,"reason":"WINDOW_CHAIN_INCOMPLETE"}
    required=("morning_pool","morning_push","feature_freeze","confirmation","confirmation_push","health_check","maintenance")
    report["complete"]=bool(report["readiness"]["latest_passed"] is True and all(completed.get(task)=="SUCCESS" for task in required) and all(accepted_receipts.values()) and report["lineage"].get("passed") is True)
    return report
