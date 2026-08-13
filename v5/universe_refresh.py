"""V5-native daily universe refresh with prior-universe anomaly gates."""
from __future__ import annotations
from datetime import datetime
import json
import time
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request,urlopen
from .core import CHINA_TZ,ContractViolation
from .eastmoney_source import UNIVERSE_FILTER
from .universe import UniverseV1,eligible

def _fetch(url,timeout):
    request=Request(url,headers={"Referer":"https://quote.eastmoney.com/","User-Agent":"Mozilla/5.0"})
    with urlopen(request,timeout=timeout) as response:return json.loads(response.read().decode("utf-8"))
def fetch_codes(*,fetch_json=None,timeout=10,page_size=500,overall_budget_seconds=12,monotonic=None):
    fetch_json=fetch_json or _fetch;monotonic=monotonic or time.monotonic;deadline=monotonic()+float(overall_budget_seconds);codes=[];page=1;complete=False;declared_total=None
    while page<=20:
        remaining=deadline-monotonic()
        if remaining<=0:raise TimeoutError("universe refresh exceeded overall budget")
        query=urlencode({"pn":page,"pz":page_size,"po":1,"np":1,"fltt":2,"invt":2,"fid":"f3","fs":UNIVERSE_FILTER,"fields":"f12"});payload=fetch_json("https://push2.eastmoney.com/api/qt/clist/get?"+query,min(timeout,max(.1,remaining)));data=payload.get("data",{})
        if payload.get("rc")!=0 or not isinstance(data.get("diff"),list):raise ContractViolation("universe provider payload invalid")
        codes.extend(str(row.get("f12","")).zfill(6) for row in data["diff"]);declared_total=int(data.get("total",len(codes)) or len(codes))
        if len(codes)>=declared_total:complete=True;break
        if not data["diff"]:break
        page+=1
    if not complete:raise ContractViolation(f"universe pagination incomplete: received={len(codes)} expected={declared_total}")
    values=sorted({code for code in codes if eligible(code)})
    if not values:raise ContractViolation("universe provider returned no eligible codes")
    return values
def _previous(root,day):
    candidates=[]
    for directory in (Path(root)/"universes").iterdir() if (Path(root)/"universes").exists() else ():
        if directory.name>=day:continue
        for path in directory.glob("*.json"):candidates.append((directory.name,path))
    if not candidates:return None
    return json.loads(max(candidates,key=lambda item:(item[0],item[1].name))[1].read_text(encoding="utf-8"))
def refresh(root,*,now=None,fetch_json=None,minimum_prior_ratio=.98,maximum_churn_ratio=.02,overall_budget_seconds=12,monotonic=None):
    current=(now or datetime.now(CHINA_TZ)).astimezone(CHINA_TZ);day=current.date().isoformat();codes=fetch_codes(fetch_json=fetch_json,overall_budget_seconds=overall_budget_seconds,monotonic=monotonic);prior=_previous(root,day);checks={"provider_nonempty":bool(codes),"pagination_complete":True}
    if prior:
        old=set(prior["codes"]);new=set(codes);checks["minimum_prior_count"]=len(new)>=len(old)*minimum_prior_ratio;checks["bounded_churn"]=len(old^new)/max(len(old),1)<=maximum_churn_ratio
    if not all(checks.values()):raise ContractViolation("daily universe anomaly gate rejected refresh")
    universe=UniverseV1.build(trade_date=day,created_at=current,codes=codes,sources=["eastmoney_realtime_market_directory","prior_universe_anomaly_gate"]);path=universe.save(root);return {"universe_id":universe.universe_id,"trade_date":day,"count":len(universe.codes),"checks":checks,"path":str(path)}
