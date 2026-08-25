"""Point-in-time 09:25 factor diagnostics; labels are joined only after exit."""
from __future__ import annotations
from math import sqrt

FACTORS=("intraday_change","amount","close_location")
def observations_from_snapshot(snapshot,*,minimum_amount=5_000_000.0,maximum_change=.095,maximum_range=.15):
    rows=[]
    for q in snapshot.quotes:
        if "ST" in q.name.upper() or "退" in q.name or q.halted or q.limit_up or q.limit_down or q.amount<minimum_amount or q.previous_close<=0:continue
        change=q.last_price/q.previous_close-1;day_range=(q.high_price-q.low_price)/q.previous_close
        if change>maximum_change or day_range>maximum_range:continue
        rows.append({"code":q.code,"snapshot_id":snapshot.snapshot_id,"observed_at":q.exchange_time,"intraday_change":change,"amount":q.amount,"close_location":(q.last_price-q.low_price)/max(q.high_price-q.low_price,.000001)})
    return rows
def _rank(values):
    order=sorted(range(len(values)),key=lambda i:(values[i],i));result=[0.]*len(values)
    for rank,index in enumerate(order):result[index]=rank
    return result
def _corr(a,b):
    if len(a)<2:return None
    ma=sum(a)/len(a);mb=sum(b)/len(b);da=sum((x-ma)**2 for x in a);db=sum((x-mb)**2 for x in b)
    return None if not da or not db else sum((x-ma)*(y-mb) for x,y in zip(a,b))/sqrt(da*db)
def _summary(values):
    values=sorted(map(float,values));n=len(values)
    if not n:return {"count":0}
    q=lambda p:values[round((n-1)*p)]
    return {"count":n,"min":values[0],"q25":q(.25),"median":q(.5),"q75":q(.75),"max":values[-1],"mean":sum(values)/n}
def analyze(observations):
    rows=list(observations);result={"schema_version":"v5-factor-diagnostics-v1","observation_count":len(rows),"factors":{},"correlations":{},"label_status":"AVAILABLE" if rows and all("net_return" in x for x in rows) else "INSUFFICIENT_STRICT_LABELS"}
    for factor in FACTORS:
        values=[float(x[factor]) for x in rows];entry={"distribution":_summary(values)}
        if factor=="close_location" and values:
            entry["near_constant"]=(max(values)-min(values)<.02 or (_summary(values)["q75"]-_summary(values)["q25"])<.01)
        if result["label_status"]=="AVAILABLE":
            returns=[float(x["net_return"]) for x in rows];entry["rank_ic"]=_corr(_rank(values),_rank(returns));ordered=sorted(zip(values,returns));entry["quintile_returns"]=[sum(y for _,y in ordered[i::5])/len(ordered[i::5]) for i in range(min(5,len(ordered)))]
        result["factors"][factor]=entry
    for i,left in enumerate(FACTORS):
        for right in FACTORS[i+1:]:result["correlations"][f"{left}__{right}"]=_corr([float(x[left]) for x in rows],[float(x[right]) for x in rows])
    return result
