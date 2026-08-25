"""Point-in-time 09:25 factor diagnostics; labels are joined only after exit."""
from __future__ import annotations
from math import sqrt

FACTORS=("intraday_change","amount_percentile","close_location")
def observations_from_snapshot(snapshot,*,minimum_amount=5_000_000.0,maximum_change=.095,maximum_range=.15):
    rows=[]
    for q in snapshot.quotes:
        if "ST" in q.name.upper() or "退" in q.name or q.halted or q.limit_up or q.limit_down or q.amount<minimum_amount or q.previous_close<=0:continue
        change=q.last_price/q.previous_close-1;day_range=(q.high_price-q.low_price)/q.previous_close
        if change>maximum_change or day_range>maximum_range:continue
        rows.append({"code":q.code,"snapshot_id":snapshot.snapshot_id,"observed_at":q.exchange_time,"last_price":q.last_price,"intraday_change":change,"amount":q.amount,"close_location":(q.last_price-q.low_price)/max(q.high_price-q.low_price,.000001)})
    ranks=_rank([row["amount"] for row in rows]);denominator=len(rows)-1
    for row,rank in zip(rows,ranks):row["amount_percentile"]=rank/denominator if denominator>0 else .5
    return rows
def _rank(values):
    order=sorted(range(len(values)),key=lambda i:values[i]);result=[0.]*len(values);start=0
    while start<len(order):
        end=start+1
        while end<len(order) and values[order[end]]==values[order[start]]:end+=1
        average=(start+end-1)/2
        for index in order[start:end]:result[index]=average
        start=end
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
    rows=list(observations)
    if rows and any("amount_percentile" not in row for row in rows):
        ranks=_rank([float(row["amount"]) for row in rows]);denominator=len(rows)-1
        rows=[dict(row)|{"amount_percentile":rank/denominator if denominator>0 else .5} for row,rank in zip(rows,ranks)]
    result={"schema_version":"v5-factor-diagnostics-v2","amount_percentile_rule":"cross_section_average_rank_divided_by_n_minus_1; singleton=0.5; range=[0,1]","observation_count":len(rows),"factors":{},"correlations":{},"label_status":"AVAILABLE" if rows and all("net_return" in x for x in rows) else "INSUFFICIENT_STRICT_LABELS"}
    for factor in FACTORS:
        values=[float(x[factor]) for x in rows];entry={"distribution":_summary(values)}
        if factor=="close_location" and values:
            entry["near_constant"]=(max(values)-min(values)<.02 or (_summary(values)["q75"]-_summary(values)["q25"])<.01)
        if result["label_status"]=="AVAILABLE":
            returns=[float(x["net_return"]) for x in rows];entry["rank_ic"]=_corr(_rank(values),_rank(returns));ordered=sorted(zip(values,returns));groups=[]
            group_count=min(5,len(ordered))
            for group in range(group_count):
                start=group*len(ordered)//group_count;end=(group+1)*len(ordered)//group_count;chunk=ordered[start:end]
                if chunk:groups.append({"count":len(chunk),"minimum_factor":chunk[0][0],"maximum_factor":chunk[-1][0],"mean_return":sum(y for _,y in chunk)/len(chunk)})
            entry["quintile_returns"]=groups
        result["factors"][factor]=entry
    for i,left in enumerate(FACTORS):
        for right in FACTORS[i+1:]:result["correlations"][f"{left}__{right}"]=_corr([float(x[left]) for x in rows],[float(x[right]) for x in rows])
    return result

def join_strict_labels(observation_fact,labels,*,as_of):
    import hashlib,json
    from datetime import datetime
    observed_at=datetime.fromisoformat(observation_fact["created_at"]);cutoff=datetime.fromisoformat(as_of) if isinstance(as_of,str) else as_of
    if observed_at.tzinfo is None or cutoff.tzinfo is None:raise ValueError("causal timestamps must be timezone aware")
    if observed_at>cutoff:raise ValueError("observation is in the future")
    by_code={row["code"]:row for row in observation_fact.get("observations",[])};joined=[]
    for label in labels:
        declared=label.get("label_id","");unsigned={key:value for key,value in label.items() if key!="label_id"};expected="flabel1-"+hashlib.sha256(json.dumps(unsigned,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode()).hexdigest()[:24]
        if declared!=expected:raise ValueError("strict label content-address verification failed")
        if label.get("strict_exit_window") is not True or label.get("buy_trade_date")!=observation_fact["trade_date"] or label.get("morning_snapshot_id")!=observation_fact["snapshot_id"]:continue
        exited=datetime.fromisoformat(label["sell_recorded_at"])
        if exited<=observed_at or exited>cutoff:raise ValueError("future or non-causal strict label")
        if label["code"] in by_code:joined.append(dict(by_code[label["code"]])|{"net_return":float(label["net_return"]),"sell_recorded_at":label["sell_recorded_at"]})
    return {"schema_version":"v5-factor-labelled-cohort-v1","trade_date":observation_fact["trade_date"],"snapshot_id":observation_fact["snapshot_id"],"as_of":cutoff.isoformat(),"label_status":"AVAILABLE" if joined else "INSUFFICIENT_STRICT_LABELS","rows":joined,"diagnostics":analyze(joined if joined else observation_fact.get("observations",[]))}
