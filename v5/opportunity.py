"""Content-addressed eligible opportunity-day and pairing evidence."""
from __future__ import annotations
import hashlib,json,os
from pathlib import Path
from datetime import datetime,time
from .core import ContractViolation

def _window(value,start,end):
    if not value:return False
    return start<=datetime.fromisoformat(value).time()<=end
def _canonical(value):return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(",",":"))
def _entity_id(prefix,value):return prefix+hashlib.sha256(_canonical(value).encode()).hexdigest()[:32 if prefix.startswith("v5ch") else 24]
def _save(root,kind,day,prefix,value):
    raw=_canonical(value);entity_id=_entity_id(prefix,value);path=Path(root)/kind/day/f"{entity_id}.json";path.parent.mkdir(parents=True,exist_ok=True);tmp=path.with_suffix(f".{os.getpid()}.tmp");tmp.write_text(raw,encoding="utf-8")
    try:os.link(tmp,path)
    except FileExistsError:
        if path.read_text(encoding="utf-8")!=raw:raise ContractViolation(f"{kind} immutable collision")
    finally:tmp.unlink(missing_ok=True)
    return entity_id
def _load_hashed(path,prefix,id_key=None):
    path=Path(path);row=json.loads(path.read_text(encoding="utf-8"));declared=row.pop(id_key,None) if id_key else None;rebuilt=_entity_id(prefix,row)
    if path.stem!=rebuilt or declared not in (None,rebuilt):raise ContractViolation(f"immutable fact hash mismatch: {path}")
    if id_key:row[id_key]=rebuilt
    return row
def _single(root,kind,day,entity_id):
    path=Path(root)/kind/day/f"{entity_id}.json"
    if not path.is_file():raise ContractViolation(f"referenced {kind} fact missing")
    return path

def save_opportunity(root,*,trade_date,created_at,morning_pool_id,morning_observed_at,decision_snapshot_id,decision_snapshot_at,confirmation_at,baseline_confirmation_id,challenger_confirmation_id,baseline_code,challenger_code,buy_execution_snapshot_id,buy_execution_at,market_regime,turnover_regime,large_index_decline):
    needs_execution=bool(baseline_code or challenger_code);windows=_window(morning_observed_at,time(9,25),time(9,29,59)) and _window(decision_snapshot_at,time(14,48,30),time(14,49,59)) and _window(confirmation_at,time(14,50),time(14,51,59)) and (_window(buy_execution_at,time(14,50),time(14,51,59)) or not needs_execution);eligible=bool(windows and morning_pool_id and decision_snapshot_id and baseline_confirmation_id and challenger_confirmation_id and (buy_execution_snapshot_id or not needs_execution))
    value={"schema_version":"v5-eligible-opportunity-day-v2","trade_date":trade_date,"created_at":created_at,"morning_pool_id":morning_pool_id,"morning_observed_at":morning_observed_at,"decision_snapshot_id":decision_snapshot_id,"decision_snapshot_at":decision_snapshot_at,"confirmation_at":confirmation_at,"baseline_confirmation_id":baseline_confirmation_id,"challenger_confirmation_id":challenger_confirmation_id,"baseline_code":baseline_code,"challenger_code":challenger_code,"buy_execution_snapshot_id":buy_execution_snapshot_id,"buy_execution_at":buy_execution_at,"market_regime":market_regime,"turnover_regime":turnover_regime,"large_index_decline":bool(large_index_decline),"eligible":eligible}
    opportunity_id=_save(root,"opportunities",trade_date,"opp1-",value);return value|{"opportunity_id":opportunity_id}

def save_sell_observation(root,*,trade_date,observed_at,snapshot_id,codes):
    value={"schema_version":"v5-sell-window-observation-v1","trade_date":trade_date,"observed_at":observed_at,"snapshot_id":snapshot_id,"codes":sorted(codes),"window_valid":_window(observed_at,time(9,30),time(9,30,59))}
    observation_id=_save(root,"sell_observations",trade_date,"sellobs1-",value);return value|{"observation_id":observation_id}

def _validate_references(root,row):
    from .decision_flow import MorningPoolV5,ConfirmationV5
    from .paper_production import load_snapshot
    day=row["trade_date"]
    raw=json.loads(_single(root,"morning_pools",day,row["morning_pool_id"]).read_text(encoding="utf-8"));pool=MorningPoolV5(raw["trade_date"],raw["created_at"],raw["funnel_id"],raw["snapshot_id"],raw["market_state_id"],tuple(raw["candidates"]))
    if pool.pool_id!=row["morning_pool_id"] or pool.created_at!=row["morning_observed_at"]:raise ContractViolation("opportunity morning pool lineage mismatch")
    raw=json.loads(_single(root,"confirmations",day,row["baseline_confirmation_id"]).read_text(encoding="utf-8"));baseline=ConfirmationV5(raw["trade_date"],raw["decided_at"],raw["morning_pool_id"],raw["funnel_id"],raw["snapshot_id"],raw["market_state_id"],tuple(raw["candidates"]),tuple(raw["changes"]),raw["outcome"])
    if baseline.confirmation_id!=row["baseline_confirmation_id"] or baseline.morning_pool_id!=pool.pool_id or baseline.snapshot_id!=row["decision_snapshot_id"] or baseline.decided_at!=row["confirmation_at"]:raise ContractViolation("opportunity baseline confirmation lineage mismatch")
    cpath=_single(Path(root)/"challengers"/"volume_price_v1","confirmations",day,row["challenger_confirmation_id"]);challenger=_load_hashed(cpath,"v5chcd1-","confirmation_id")
    if challenger.get("snapshot_id")!=row["decision_snapshot_id"] or challenger.get("decided_at")!=row["confirmation_at"]:raise ContractViolation("opportunity challenger confirmation lineage mismatch")
    bcode=baseline.candidates[0]["code"] if baseline.candidates else "";ccode=challenger.get("candidates",[{}])[0].get("code","") if challenger.get("candidates") else ""
    if (bcode,ccode)!=(row.get("baseline_code",""),row.get("challenger_code","")):raise ContractViolation("opportunity selected code lineage mismatch")
    decision=load_snapshot(_single(root,"snapshots",day,row["decision_snapshot_id"]))
    if decision.batch_completed_at!=row["decision_snapshot_at"]:raise ContractViolation("opportunity decision snapshot time mismatch")
    if row.get("buy_execution_snapshot_id"):
        buy=load_snapshot(_single(root,"snapshots",day,row["buy_execution_snapshot_id"]))
        if buy.batch_completed_at!=row["buy_execution_at"]:raise ContractViolation("opportunity buy snapshot time mismatch")
    return True

def load_due(root,sell_date,calendar):
    rows=[]
    for path in (Path(root)/"opportunities").glob("*/*.json") if (Path(root)/"opportunities").exists() else ():
        row=_load_hashed(path,"opp1-");row["opportunity_id"]=path.stem
        if calendar.next_open(__import__("datetime").date.fromisoformat(row["trade_date"])).isoformat()==sell_date:
            try:_validate_references(root,row)
            except Exception as exc:row["eligible"]=False;row["evidence_error"]=f"{type(exc).__name__}: {exc}"
            rows.append(row)
    return rows

def _order_snapshot(ledger,event_id):
    event_row=next((x for x in ledger.events() if x["event_id"]==event_id),None)
    if not event_row:raise ContractViolation("referenced paper event missing")
    event=event_row["event"];path=Path(ledger.root)/"orders"/event["trade_date"]/f"{event['order_id']}.json"
    from .paper import PaperOrderV1
    raw=json.loads(path.read_text(encoding="utf-8"));declared=raw.pop("order_id");order=PaperOrderV1(**raw)
    if declared!=order.order_id or path.stem!=order.order_id:raise ContractViolation("paper order content-address mismatch")
    return order.snapshot_id,event["recorded_at"]

def _verify_execution_lineage(root,opportunity,row,baseline_ledger,challenger_ledger):
    baseline={trip["buy_trade_date"]:trip for trip in baseline_ledger.round_trips()}.get(opportunity["trade_date"]);challenger={trip["buy_trade_date"]:trip for trip in challenger_ledger.round_trips()}.get(opportunity["trade_date"])
    if (baseline is not None)!=(row.get("baseline_traded") is True) or (challenger is not None)!=(row.get("challenger_traded") is True):raise ContractViolation("pairing traded flags do not match immutable ledger")
    if baseline or challenger:
        if not row.get("sell_execution_snapshot_id"):raise ContractViolation("shared sell execution snapshot missing")
        from .paper_production import load_snapshot
        sell_day=datetime.fromisoformat(row["recorded_at"]).date().isoformat();sell=load_snapshot(_single(root,"snapshots",sell_day,row["sell_execution_snapshot_id"]))
        if sell.batch_completed_at!=row["recorded_at"]:raise ContractViolation("sell snapshot time mismatch")
        for trip,ledger in ((baseline,baseline_ledger),(challenger,challenger_ledger)):
            if not trip:continue
            buy_snapshot,_=_order_snapshot(ledger,trip["buy_event_id"]);sell_snapshot,sell_event_at=_order_snapshot(ledger,trip["sell_event_id"])
            if buy_snapshot!=opportunity.get("buy_execution_snapshot_id") or sell_snapshot!=row["sell_execution_snapshot_id"] or sell_event_at!=row["recorded_at"]:raise ContractViolation("paper order/event execution lineage mismatch")
    else:
        observation=_load_hashed(_single(root,"sell_observations",datetime.fromisoformat(row["recorded_at"]).date().isoformat(),row.get("sell_observation_id","")),"sellobs1-")
        if observation.get("observed_at")!=row["recorded_at"] or observation.get("window_valid") is not True or observation.get("codes")!=[]:raise ContractViolation("empty 09:30 observation invalid")
    return True

def save_pairing(root,opportunity,*,recorded_at,sell_execution_snapshot_id,sell_observation_id,baseline_return,challenger_return,baseline_traded,challenger_traded,lineage_valid):
    value={"schema_version":"v5-paired-opportunity-day-v2","opportunity_id":opportunity["opportunity_id"],"trade_date":opportunity["trade_date"],"recorded_at":recorded_at,"morning_pool_id":opportunity["morning_pool_id"],"decision_snapshot_id":opportunity["decision_snapshot_id"],"buy_execution_snapshot_id":opportunity.get("buy_execution_snapshot_id","") ,"sell_execution_snapshot_id":sell_execution_snapshot_id,"sell_observation_id":sell_observation_id,"baseline_return":float(baseline_return),"challenger_return":float(challenger_return),"baseline_traded":bool(baseline_traded),"challenger_traded":bool(challenger_traded),"same_window":bool(lineage_valid),"lineage_valid":bool(lineage_valid),"eligible":bool(lineage_valid),"evidence_error":opportunity.get("evidence_error",""),"market_regime":opportunity.get("market_regime","UNKNOWN"),"turnover_regime":opportunity.get("turnover_regime","UNKNOWN"),"large_index_decline":bool(opportunity.get("large_index_decline"))}
    pairing_id=_save(root,"pairings",opportunity["trade_date"],"pair1-",value);return value|{"pairing_id":pairing_id}

def load_pairs(root):
    rows=[]
    for path in (Path(root)/"pairings").glob("*/*.json") if (Path(root)/"pairings").exists() else ():
        try:row=_load_hashed(path,"pair1-")
        except Exception as exc:rows.append({"pairing_id":path.stem,"eligible":False,"same_window":False,"lineage_valid":False,"evidence_error":f"{type(exc).__name__}: {exc}"});continue
        row["pairing_id"]=path.stem
        try:
            opp=_load_hashed(_single(root,"opportunities",row["trade_date"],row["opportunity_id"]),"opp1-");opp["opportunity_id"]=row["opportunity_id"]
            _validate_references(root,opp)
            if any(row.get(k)!=opp.get(k) for k in ("morning_pool_id","decision_snapshot_id","buy_execution_snapshot_id")):raise ContractViolation("pairing opportunity projection mismatch")
            from .paper_production import PaperProduction
            from .challenger import challenger_root
            _verify_execution_lineage(root,opp,row,PaperProduction(root).ledger,PaperProduction(challenger_root(root)).ledger)
        except Exception as exc:row.update({"eligible":False,"same_window":False,"lineage_valid":False,"evidence_error":f"{type(exc).__name__}: {exc}"})
        rows.append(row)
    return sorted(rows,key=lambda row:(row.get("trade_date",""),row["pairing_id"]))

def finalize_due(root,sell_date,recorded_at,sell_execution_snapshot_id,baseline_ledger,challenger_ledger,calendar,sell_observation_id=""):
    baseline={row["buy_trade_date"]:row for row in baseline_ledger.round_trips()};challenger={row["buy_trade_date"]:row for row in challenger_ledger.round_trips()};results=[]
    for opportunity in load_due(root,sell_date,calendar):
        left=baseline.get(opportunity["trade_date"]);right=challenger.get(opportunity["trade_date"]);requires_sell=bool(left or right);valid=bool(opportunity.get("eligible") and _window(recorded_at,time(9,30),time(9,30,59)))
        try:
            _verify_execution_lineage(root,opportunity,{"recorded_at":recorded_at,"sell_execution_snapshot_id":sell_execution_snapshot_id,"sell_observation_id":sell_observation_id,"baseline_traded":left is not None,"challenger_traded":right is not None},baseline_ledger,challenger_ledger)
        except Exception as exc:valid=False;opportunity["evidence_error"]=f"{type(exc).__name__}: {exc}"
        results.append(save_pairing(root,opportunity,recorded_at=recorded_at,sell_execution_snapshot_id=sell_execution_snapshot_id,sell_observation_id=sell_observation_id,baseline_return=left["net_return"] if left else 0,challenger_return=right["net_return"] if right else 0,baseline_traded=left is not None,challenger_traded=right is not None,lineage_valid=valid))
    return results
