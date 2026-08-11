"""Authorized P3 paper execution using final P2 entities and MarketSnapshotV1."""
from __future__ import annotations
from datetime import datetime
import hashlib,json
from pathlib import Path
from .candidate_journal import CandidateJournal
from .execution import CHINA_TZ,ExecutionBlocked,TradingClock
from .market_gateway import MarketDataGateway,SnapshotRepository
from .p3_account import OfflinePaperLedger
from .p3_execution import OfflineExecutionEngine,OfflineIntentFactory
from .production_gate import require_authorized_owner
from .snapshot_compat import archive_market_snapshot

ROOT=Path(__file__).resolve().parents[1]

def _write_batch(root,body):
    raw=json.dumps(body,ensure_ascii=False,sort_keys=True,separators=(",",":"))
    value={**body,"batch_id":"pebatch1-"+hashlib.sha256(raw.encode()).hexdigest()[:24]}
    path=Path(root)/"execution_batches"/body["trade_date"]/(body["side"].lower()+".json")
    path.parent.mkdir(parents=True,exist_ok=True)
    if path.exists(): return json.loads(path.read_text(encoding="utf-8"))
    temporary=path.with_suffix(".tmp"); temporary.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding="utf-8"); temporary.replace(path)
    return value

def _decision_snapshot(decision):
    snapshot_id=str(decision.get("lineage",{}).get("input_snapshot_id",""))
    paths=list((ROOT/"v4"/"data"/"market_snapshots_v1").glob(f"*/{decision['trade_date']}/buy/{snapshot_id}.json"))
    if len(paths)!=1: raise RuntimeError("BUY_SNAPSHOT_NOT_UNIQUELY_RESOLVED")
    return SnapshotRepository().load(paths[0])

def execute(mode,*,authorization_file,now=None,account_dir=None):
    require_authorized_owner(authorization_file,resource="paper_account",owner="P3")
    current=(now or datetime.now(CHINA_TZ)).astimezone(CHINA_TZ)
    clock=TradingClock.action_status(mode,now=current)
    if not clock.allowed: raise ExecutionBlocked(clock.reason)
    root=Path(account_dir or ROOT/"v4"/"data"/"p3")
    ledger=OfflinePaperLedger(root); engine=OfflineExecutionEngine(ledger); factory=OfflineIntentFactory()
    intents=[]; decision_id=""
    if mode=="buy":
        decision=CandidateJournal().confirmation(current.date().isoformat()); decision_id=str(decision.get("decision_id",""))
        if not decision: raise RuntimeError("CONFIRMATION_DECISION_MISSING")
        if decision.get("outcome")=="BUY":
            intents=[factory.buy_from_decision(decision,_decision_snapshot(decision),created_at=current,total_equity=ledger.snapshot()["cash"])]
    else:
        positions=ledger.snapshot()["positions"]
        if positions:
            snapshot=MarketDataGateway().fetch_snapshot([x["code"] for x in positions],session="sell",minimum_coverage=1.0,now=current)
            if archive_market_snapshot(snapshot,capture_role="p3_sell_gateway") is None:
                raise RuntimeError("STRICT_SELL_SNAPSHOT_ARCHIVE_FAILED")
            intents=[factory.sell_from_position(x,snapshot,created_at=current) for x in positions]
    result=engine.execute(intents,filled_at=current) if intents else {"success":True,"filled":0,"failed":0,"results":[]}
    body={"schema_version":"paper-execution-batch-v1","trade_date":current.date().isoformat(),"side":mode.upper(),
          "decision_id":decision_id,"intent_count":len(intents),"result":result,"account":ledger.snapshot(),
          "reconciliation":ledger.reconcile(engine.order_journal)}
    return _write_batch(root,body)
