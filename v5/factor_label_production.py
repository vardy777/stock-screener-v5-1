"""Read-only production of content-addressed strict 09:25 factor labels."""
from __future__ import annotations
from datetime import datetime,time
from pathlib import Path
import hashlib,json,os
from .core import CHINA_TZ,ContractViolation
from .factor_research import join_strict_labels
from .opportunity import load_pairs
from .paper_production import PaperProduction
from .challenger import challenger_root

def _canonical(value):return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(",",":"))
def _id(prefix,value):return prefix+hashlib.sha256(_canonical(value).encode()).hexdigest()[:24]
def _save(root,kind,day,prefix,value):
    entity_id=_id(prefix,value);path=Path(root)/kind/day/f"{entity_id}.json";path.parent.mkdir(parents=True,exist_ok=True);raw=_canonical(value);tmp=path.with_suffix(f".{os.getpid()}.tmp");tmp.write_text(raw,encoding="utf-8")
    try:os.link(tmp,path)
    except FileExistsError:
        if path.read_text(encoding="utf-8")!=raw:raise ContractViolation(f"{kind} immutable collision")
    finally:tmp.unlink(missing_ok=True)
    return entity_id
def _diagnostic(root,day):
    rows=[]
    for path in (Path(root)/"factor_diagnostics"/day).glob("fac1-*.json"):
        value=json.loads(path.read_text(encoding="utf-8"))
        if path.stem!=_id("fac1-",value):raise ContractViolation("factor diagnostic content-address mismatch")
        if value.get("trade_date")!=day or any(row.get("snapshot_id")!=value.get("snapshot_id") for row in value.get("observations",[])):raise ContractViolation("factor diagnostic observation lineage mismatch")
        if not value.get("created_at") and value.get("observations"):value["created_at"]=max(row["observed_at"] for row in value["observations"])
        rows.append(value|{"diagnostic_id":path.stem})
    if not rows:raise ContractViolation("strict 09:25 factor diagnostic missing")
    return max(rows,key=lambda row:(row.get("created_at",row.get("observations",[{}])[0].get("observed_at","")),row["diagnostic_id"]))
def _label(strategy,trip,pair,morning_snapshot_id):
    if trip.get("return_basis")!="net_pnl_divided_by_invested_capital":raise ContractViolation("strict factor label return basis invalid")
    recorded=pair["recorded_at"];clock=datetime.fromisoformat(recorded).time()
    if not time(9,30)<=clock<=time(9,30,59):raise ContractViolation("strict factor label sell window invalid")
    value={"schema_version":"v5-strict-factor-label-v1","strategy_id":strategy,"code":trip["code"],"buy_trade_date":trip["buy_trade_date"],"morning_snapshot_id":morning_snapshot_id,"buy_execution_snapshot_id":pair["buy_execution_snapshot_id"],"sell_execution_snapshot_id":pair["sell_execution_snapshot_id"],"buy_event_id":trip["buy_event_id"],"sell_event_id":trip["sell_event_id"],"sell_recorded_at":recorded,"strict_exit_window":True,"return_basis":trip["return_basis"],"net_return":float(trip["net_return"])}
    return value|{"label_id":_id("flabel1-",value)}

def produce(root,trade_date,*,as_of):
    root=Path(root);cutoff=datetime.fromisoformat(as_of) if isinstance(as_of,str) else as_of
    if cutoff.tzinfo is None or cutoff.utcoffset() is None:raise ContractViolation("factor label as_of timezone required")
    cutoff=cutoff.astimezone(CHINA_TZ);diagnostic=_diagnostic(root,trade_date);pairs=[row for row in load_pairs(root) if row.get("trade_date")==trade_date]
    invalid=any(row.get("eligible") is not True for row in pairs);pair=next((row for row in pairs if row.get("eligible") is True and datetime.fromisoformat(row["recorded_at"])<=cutoff),None);labels=[]
    if pair:
        pool_path=root/"morning_pools"/trade_date/f"{pair['morning_pool_id']}.json";pool=json.loads(pool_path.read_text(encoding="utf-8"))
        if pool.get("snapshot_id")!=diagnostic["snapshot_id"]:raise ContractViolation("factor diagnostic is not the paired 09:25 morning snapshot")
        observed_codes={row["code"] for row in diagnostic.get("observations",[])}
        ledgers=(("baseline",PaperProduction(root).ledger),("volume_price_v1",PaperProduction(challenger_root(root)).ledger))
        for strategy,ledger in ledgers:
            trip=next((row for row in ledger.round_trips(as_of=cutoff) if row["buy_trade_date"]==trade_date),None)
            if trip:
                if trip["code"] not in observed_codes:raise ContractViolation("strict label code missing from 09:25 eligible cross-section")
                label=_label(strategy,trip,pair,diagnostic["snapshot_id"]);_save(root,"strategy_factor_labels",trade_date,"flabel1-",{key:value for key,value in label.items() if key!="label_id"});labels.append(label)
    joined=join_strict_labels(diagnostic,labels,as_of=cutoff);status="EVIDENCE_INVALID" if invalid else joined["label_status"]
    value={"schema_version":"v5-factor-labelled-cohort-v1","trade_date":trade_date,"created_at":cutoff.isoformat(),"diagnostic_id":diagnostic["diagnostic_id"],"morning_snapshot_id":diagnostic["snapshot_id"],"pairing_id":pair.get("pairing_id","") if pair else "","label_ids":[row["label_id"] for row in labels],"label_status":status,"rows":joined["rows"],"diagnostics":joined["diagnostics"]}
    value["cohort_type"]="strategy_executed_only_not_cross_sectional"
    cohort_id=_save(root,"strategy_factor_labelled_cohorts",trade_date,"flcohort1-",value);return value|{"cohort_id":cohort_id}
