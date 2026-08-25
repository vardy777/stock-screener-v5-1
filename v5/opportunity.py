"""Immutable eligible opportunity-day and completed pairing facts."""
from __future__ import annotations
import hashlib,json,os
from pathlib import Path
from .core import ContractViolation
from datetime import datetime,time
def _window(value,start,end):
    if not value:return False
    clock=datetime.fromisoformat(value).time();return start<=clock<=end

def _save(root,kind,day,prefix,value):
    raw=json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(",",":"));entity_id=prefix+hashlib.sha256(raw.encode()).hexdigest()[:24];path=Path(root)/kind/day/f"{entity_id}.json";path.parent.mkdir(parents=True,exist_ok=True);tmp=path.with_suffix(f".{os.getpid()}.tmp");tmp.write_text(raw,encoding="utf-8")
    try:os.link(tmp,path)
    except FileExistsError:
        if path.read_text(encoding="utf-8")!=raw:raise ContractViolation(f"{kind} immutable collision")
    finally:tmp.unlink(missing_ok=True)
    return entity_id

def save_opportunity(root,*,trade_date,created_at,morning_pool_id,morning_observed_at,decision_snapshot_id,decision_snapshot_at,confirmation_at,baseline_confirmation_id,challenger_confirmation_id,baseline_code,challenger_code,buy_execution_snapshot_id,buy_execution_at,market_regime,turnover_regime,large_index_decline):
    needs_execution=bool(baseline_code or challenger_code);windows=_window(morning_observed_at,time(9,25),time(9,29,59)) and _window(decision_snapshot_at,time(14,48,30),time(14,49,59)) and _window(confirmation_at,time(14,50),time(14,51,59)) and (_window(buy_execution_at,time(14,50),time(14,51,59)) or not needs_execution);eligible=bool(windows and morning_pool_id and decision_snapshot_id and baseline_confirmation_id and challenger_confirmation_id and (buy_execution_snapshot_id or not needs_execution))
    value={"schema_version":"v5-eligible-opportunity-day-v1","trade_date":trade_date,"created_at":created_at,"morning_pool_id":morning_pool_id,"morning_observed_at":morning_observed_at,"decision_snapshot_id":decision_snapshot_id,"decision_snapshot_at":decision_snapshot_at,"confirmation_at":confirmation_at,"baseline_confirmation_id":baseline_confirmation_id,"challenger_confirmation_id":challenger_confirmation_id,"baseline_code":baseline_code,"challenger_code":challenger_code,"buy_execution_snapshot_id":buy_execution_snapshot_id,"buy_execution_at":buy_execution_at,"market_regime":market_regime,"turnover_regime":turnover_regime,"large_index_decline":bool(large_index_decline),"eligible":eligible}
    opportunity_id=_save(root,"opportunities",trade_date,"opp1-",value);return value|{"opportunity_id":opportunity_id}

def load_due(root,sell_date,calendar):
    rows=[]
    for path in (Path(root)/"opportunities").glob("*/*.json") if (Path(root)/"opportunities").exists() else ():
        row=json.loads(path.read_text(encoding="utf-8"));row["opportunity_id"]=path.stem
        if calendar.next_open(__import__("datetime").date.fromisoformat(row["trade_date"])).isoformat()==sell_date:rows.append(row)
    return rows

def save_pairing(root,opportunity,*,recorded_at,sell_execution_snapshot_id,baseline_return,challenger_return,baseline_traded,challenger_traded):
    requires_sell=baseline_traded or challenger_traded;sell_window=_window(recorded_at,time(9,30),time(9,30,59));lineage_valid=bool(sell_window and opportunity.get("eligible") and opportunity.get("morning_pool_id") and opportunity.get("decision_snapshot_id") and (opportunity.get("buy_execution_snapshot_id") or not (opportunity.get("baseline_code") or opportunity.get("challenger_code"))) and (sell_execution_snapshot_id or not requires_sell))
    value={"schema_version":"v5-paired-opportunity-day-v1","opportunity_id":opportunity["opportunity_id"],"trade_date":opportunity["trade_date"],"recorded_at":recorded_at,"morning_pool_id":opportunity["morning_pool_id"],"decision_snapshot_id":opportunity["decision_snapshot_id"],"buy_execution_snapshot_id":opportunity.get("buy_execution_snapshot_id","") ,"sell_execution_snapshot_id":sell_execution_snapshot_id,"baseline_return":float(baseline_return),"challenger_return":float(challenger_return),"baseline_traded":bool(baseline_traded),"challenger_traded":bool(challenger_traded),"same_window":lineage_valid,"lineage_valid":lineage_valid,"eligible":lineage_valid,"market_regime":opportunity.get("market_regime","UNKNOWN"),"turnover_regime":opportunity.get("turnover_regime","UNKNOWN"),"large_index_decline":bool(opportunity.get("large_index_decline"))}
    pairing_id=_save(root,"pairings",opportunity["trade_date"],"pair1-",value);return value|{"pairing_id":pairing_id}

def load_pairs(root):
    rows=[]
    for path in (Path(root)/"pairings").glob("*/*.json") if (Path(root)/"pairings").exists() else ():
        row=json.loads(path.read_text(encoding="utf-8"));row["pairing_id"]=path.stem;rows.append(row)
    return sorted(rows,key=lambda row:(row["trade_date"],row["pairing_id"]))

def finalize_due(root,sell_date,recorded_at,sell_execution_snapshot_id,baseline_ledger,challenger_ledger,calendar):
    baseline={row["buy_trade_date"]:row for row in baseline_ledger.round_trips()};challenger={row["buy_trade_date"]:row for row in challenger_ledger.round_trips()};results=[]
    for opportunity in load_due(root,sell_date,calendar):
        left=baseline.get(opportunity["trade_date"]);right=challenger.get(opportunity["trade_date"])
        results.append(save_pairing(root,opportunity,recorded_at=recorded_at,sell_execution_snapshot_id=sell_execution_snapshot_id,baseline_return=left["net_return"] if left else 0,challenger_return=right["net_return"] if right else 0,baseline_traded=left is not None,challenger_traded=right is not None))
    return results
