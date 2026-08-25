"""Pre-registered 09:25 cross-section to next-session strict 09:30 return study."""
from __future__ import annotations
from datetime import datetime,time,date
from pathlib import Path
import hashlib,json,os
from .core import CHINA_TZ,ContractViolation
from .data_production import ConsensusAcquirer
from .sina_source import SinaRealtimeSource
from .tencent_source import TencentRealtimeSource
from .universe import UniverseV1
from .factor_research import analyze
from .factor_label_production import _diagnostic
from .calendar import TradingCalendar
from .storage import V5FactStore

PROTOCOL_ID="v5-factor-cross-section-0925-last-to-next-0930-conservative-bid-v1";MINIMUM_USABLE_COVERAGE=.95
def _canonical(value):return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(",",":"))
def _id(prefix,value):return prefix+hashlib.sha256(_canonical(value).encode()).hexdigest()[:24]
def _save(root,kind,day,prefix,value):
    entity_id=_id(prefix,value);path=Path(root)/kind/day/f"{entity_id}.json";path.parent.mkdir(parents=True,exist_ok=True);raw=_canonical(value);tmp=path.with_suffix(f".{os.getpid()}.tmp");tmp.write_text(raw,encoding="utf-8")
    try:os.link(tmp,path)
    except FileExistsError:
        if path.read_text(encoding="utf-8")!=raw:raise ContractViolation(f"{kind} immutable collision")
    finally:tmp.unlink(missing_ok=True)
    return entity_id
def due_trade_date(root,sell_date,calendar=None):
    calendar=calendar or TradingCalendar();days=[]
    for path in (Path(root)/"factor_diagnostics").iterdir() if (Path(root)/"factor_diagnostics").exists() else ():
        if path.is_dir() and calendar.next_open(date.fromisoformat(path.name)).isoformat()==sell_date:days.append(path.name)
    return max(days) if days else ""
def capture_exit(root,*,sell_date,now,sources=None):
    root=Path(root);current=now.astimezone(CHINA_TZ);trade_date=due_trade_date(root,sell_date)
    if not trade_date:return {"status":"NO_DUE_0925_CROSS_SECTION","usable":False,"coverage":0.0}
    diagnostic=_diagnostic(root,trade_date);observations=list(diagnostic.get("observations",[]));codes=sorted({row["code"] for row in observations});excluded={};labels=[];snapshot_id="";report={}
    if codes:
        universe=UniverseV1.build(trade_date=sell_date,created_at=current,codes=codes,sources=["v5_factor_cross_section_exit"]);sources=sources or (SinaRealtimeSource(),TencentRealtimeSource());result=ConsensusAcquirer(*sources).acquire(universe,stage="sell",now=current);report=result.report
        _save(root,"factor_cross_section_consensus",sell_date,"faccons1-",report)
        if result.accepted:
            V5FactStore(root).save_snapshot(result.primary);snapshot_id=result.primary.snapshot_id;quotes={quote.code:quote for quote in result.primary.quotes}
            for observation in observations:
                code=observation["code"];quote=quotes.get(code);entry=float(observation.get("last_price",0))
                if not quote:excluded[code]="DUAL_SOURCE_EXIT_CONFLICT_OR_MISSING";continue
                if entry<=0:excluded[code]="STRICT_0925_ENTRY_PRICE_MISSING";continue
                value={"schema_version":"v5-cross-section-factor-label-v1","protocol_id":PROTOCOL_ID,"code":code,"buy_trade_date":trade_date,"sell_trade_date":sell_date,"morning_snapshot_id":diagnostic["snapshot_id"],"sell_execution_snapshot_id":snapshot_id,"entry_observed_at":observation["observed_at"],"entry_price":entry,"sell_recorded_at":result.primary.batch_completed_at,"exit_price":quote.bid1,"strict_exit_window":time(9,30)<=datetime.fromisoformat(result.primary.batch_completed_at).time()<=time(9,30,59),"return_basis":"next_0930_conservative_bid_divided_by_0925_observed_last_minus_1","net_return":quote.bid1/entry-1}
                if value["strict_exit_window"] is not True:excluded[code]="EXIT_OUTSIDE_STRICT_0930_MINUTE";continue
                label_id=_save(root,"factor_cross_section_labels",trade_date,"fcslabel1-",value);labels.append(value|{"label_id":label_id})
        else:
            excluded.update({code:"DUAL_SOURCE_EXIT_ACQUISITION_REJECTED" for code in codes})
    coverage=len(labels)/max(len(observations),1);usable=bool(observations and coverage>=MINIMUM_USABLE_COVERAGE);by_code={row["code"]:row for row in observations};labelled=[dict(by_code[row["code"]])|{"net_return":row["net_return"]} for row in labels];diagnostics=analyze(labelled) if usable else {"label_status":"INSUFFICIENT_CROSS_SECTION_COVERAGE","observation_count":len(labelled)}
    value={"schema_version":"v5-factor-cross-section-cohort-v1","protocol_id":PROTOCOL_ID,"trade_date":trade_date,"sell_trade_date":sell_date,"created_at":current.isoformat(),"morning_diagnostic_id":diagnostic["diagnostic_id"],"morning_snapshot_id":diagnostic["snapshot_id"],"sell_execution_snapshot_id":snapshot_id,"eligible_observation_count":len(observations),"label_count":len(labels),"coverage":coverage,"minimum_usable_coverage":MINIMUM_USABLE_COVERAGE,"usable_for_ic":usable,"label_status":"AVAILABLE" if usable else "INSUFFICIENT_CROSS_SECTION_COVERAGE","excluded":excluded,"label_ids":[row["label_id"] for row in labels],"diagnostics":diagnostics,"consensus_status":"ACCEPTED" if report.get("accepted") else "REJECTED" if report else "NOT_RUN"}
    cohort_id=_save(root,"factor_cross_section_cohorts",trade_date,"fcscohort1-",value);return value|{"cohort_id":cohort_id}

def aggregate(root,*,as_of):
    cutoff=datetime.fromisoformat(as_of) if isinstance(as_of,str) else as_of;days=[]
    for path in (Path(root)/"factor_cross_section_cohorts").glob("*/*.json") if (Path(root)/"factor_cross_section_cohorts").exists() else ():
        row=json.loads(path.read_text(encoding="utf-8"))
        if path.stem!=_id("fcscohort1-",row):raise ContractViolation("factor cross-section cohort hash mismatch")
        if row.get("usable_for_ic") is True and datetime.fromisoformat(row["created_at"])<=cutoff:days.append(row)
    factors={}
    for factor in ("intraday_change","amount_percentile","close_location"):
        ics=[row["diagnostics"]["factors"][factor].get("rank_ic") for row in days];ics=[value for value in ics if value is not None]
        quintiles=[row["diagnostics"]["factors"][factor].get("quintile_returns",[]) for row in days];mean_quintiles=[]
        for index in range(5):
            values=[groups[index]["mean_return"] for groups in quintiles if len(groups)==5]
            mean_quintiles.append(sum(values)/len(values) if values else None)
        factors[factor]={"usable_days":len(ics),"mean_daily_rank_ic":sum(ics)/len(ics) if ics else None,"mean_daily_quintile_returns":mean_quintiles,"aggregation":"equal_weight_mean_across_daily_cross_section_statistics"}
    return {"schema_version":"v5-factor-cross-section-aggregate-v1","protocol_id":PROTOCOL_ID,"as_of":cutoff.isoformat(),"usable_days":len(days),"factors":factors}
