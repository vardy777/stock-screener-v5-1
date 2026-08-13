"""V5-native daily universe refresh with prior-universe anomaly gates."""
from __future__ import annotations
from datetime import datetime
import json
import time
from urllib.error import HTTPError,URLError
from http.client import RemoteDisconnected
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request,urlopen
from .core import CHINA_TZ,ContractViolation
from .eastmoney_source import UNIVERSE_FILTER
from .universe import UniverseV1,eligible
ENDPOINTS=("https://push2delay.eastmoney.com","https://push2.eastmoney.com","https://82.push2.eastmoney.com","https://72.push2.eastmoney.com")

def _fetch(url,timeout):
    request=Request(url,headers={"Referer":"https://quote.eastmoney.com/","User-Agent":"Mozilla/5.0"})
    with urlopen(request,timeout=timeout) as response:return json.loads(response.read().decode("utf-8"))
def fetch_codes(*,fetch_json=None,timeout=10,page_size=500,overall_budget_seconds=12,monotonic=None,sleeper=None,retries=2,endpoints=ENDPOINTS,return_diagnostics=False):
    fetch_json=fetch_json or _fetch;monotonic=monotonic or time.monotonic;sleeper=sleeper or time.sleep;deadline=monotonic()+float(overall_budget_seconds);codes=[];page=1;complete=False;declared_total=None
    maximum_pages=100
    while page<=maximum_pages:
        remaining=deadline-monotonic()
        if remaining<=0:raise TimeoutError("universe refresh exceeded overall budget")
        query=urlencode({"pn":page,"pz":page_size,"po":1,"np":1,"fltt":2,"invt":2,"fid":"f3","fs":UNIVERSE_FILTER,"fields":"f12"});last=None;failures=[];payload=None
        attempts=max(int(retries)+1,len(endpoints))
        for attempt in range(attempts):
            remaining=deadline-monotonic()
            if remaining<=0:raise TimeoutError("universe refresh exceeded overall budget")
            endpoint=endpoints[attempt%len(endpoints)];url=endpoint+"/api/qt/clist/get?"+query
            try:payload=fetch_json(url,min(timeout,max(.1,remaining)));break
            except (HTTPError,URLError,TimeoutError,ConnectionError,OSError,RemoteDisconnected,RuntimeError) as exc:
                last=exc;failures.append({"page":page,"endpoint":endpoint,"error":type(exc).__name__})
                if attempt>=attempts-1:raise RuntimeError(f"universe page {page} unavailable: {type(exc).__name__}") from exc
                sleeper(min(.2*(attempt+1),max(0,deadline-monotonic())))
        data=payload.get("data",{})
        if payload.get("rc")!=0 or not isinstance(data.get("diff"),list):raise ContractViolation("universe provider payload invalid")
        codes.extend(str(row.get("f12","")).zfill(6) for row in data["diff"]);declared_total=int(data.get("total",len(codes)) or len(codes))
        if declared_total>10000:raise ContractViolation("universe declared total outside safety bound")
        if len(codes)>=declared_total:complete=True;break
        if not data["diff"]:break
        page+=1
    if not complete:raise ContractViolation(f"universe pagination incomplete: received={len(codes)} expected={declared_total}")
    values=sorted({code for code in codes if eligible(code)})
    if not values:raise ContractViolation("universe provider returned no eligible codes")
    return (values,{"endpoint_failures":failures,"declared_total":declared_total,"pages":page}) if return_diagnostics else values
def _previous(root,day,*,as_of=None):
    candidates=[]
    for directory in (Path(root)/"universes").iterdir() if (Path(root)/"universes").exists() else ():
        if directory.name>day:continue
        for path in directory.glob("*.json"):
            row=json.loads(path.read_text(encoding="utf-8"));created=datetime.fromisoformat(row["created_at"])
            if created.tzinfo is None:raise ContractViolation("prior universe time requires timezone")
            if as_of is None or created.astimezone(CHINA_TZ)<=as_of.astimezone(CHINA_TZ):candidates.append((created,row.get("universe_id",path.name),row))
    if not candidates:return None
    return max(candidates,key=lambda item:(item[0],item[1]))[2]
def refresh(root,*,now=None,fetch_json=None,minimum_prior_ratio=.98,maximum_churn_ratio=.02,overall_budget_seconds=12,monotonic=None):
    current=(now or datetime.now(CHINA_TZ)).astimezone(CHINA_TZ);day=current.date().isoformat();codes,diagnostics=fetch_codes(fetch_json=fetch_json,overall_budget_seconds=overall_budget_seconds,monotonic=monotonic,return_diagnostics=True);prior=_previous(root,day,as_of=current);checks={"provider_nonempty":bool(codes),"pagination_complete":True}
    if prior:
        old=set(prior["codes"]);new=set(codes);legacy_seed="legacy_daily_archive_seed_migration" in prior.get("sources",[])
        checks["minimum_prior_count"]=len(new)>=len(old)*minimum_prior_ratio
        if legacy_seed:
            checks["legacy_seed_retention"]=len(old&new)/max(len(old),1)>=.995;checks["migration_is_expansion_only"]=len(old-new)==0;checks["bounded_churn"]=checks["legacy_seed_retention"] and checks["migration_is_expansion_only"];diagnostics["migration_mode"]="legacy_seed_to_native_directory"
        else:
            star_scope_upgrade=not any(code.startswith(("688","689")) for code in old) and any(code.startswith(("688","689")) for code in new) and not (old-new)
            checks["bounded_churn"]=len(old^new)/max(len(old),1)<=maximum_churn_ratio or star_scope_upgrade
            if star_scope_upgrade:diagnostics["scope_upgrade"]="ADD_STAR_MARKET_RETAIN_ALL_PRIOR_CODES"
    if not all(checks.values()):raise ContractViolation("daily universe anomaly gate rejected refresh")
    universe=UniverseV1.build(trade_date=day,created_at=current,codes=codes,sources=["eastmoney_realtime_market_directory","prior_universe_anomaly_gate"]);path=universe.save(root);return {"universe_id":universe.universe_id,"trade_date":day,"count":len(universe.codes),"checks":checks,"diagnostics":diagnostics,"path":str(path)}
