"""Pre-registered challenger evaluation; independent of observed outcomes."""
from __future__ import annotations
from dataclasses import dataclass,asdict
from math import sqrt

@dataclass(frozen=True)
class StatisticalProtocolV1:
    protocol_id:str="v5-challenger-prereg-2026-08-25-v1"
    paired_eligible_days_minimum:int=60
    per_required_regime_minimum:int=10
    confidence_level:float=.95
    challenger_max_drawdown:float=.10
    kill_max_drawdown:float=.12
    minimum_mean_return:float=0.0
    minimum_mean_excess:float=0.0
    early_kill_days:int=30
    walk_forward:str="anchored chronological 60% development / 20% validation / 20% untouched holdout"
    pairing_unit:str="same eligible trade day and execution windows; no-trade return is zero"
    required_regimes:tuple=("STRONG","NEUTRAL","WEAK")
    def to_dict(self):return asdict(self)|{"promotion_rule":"all minimums pass and lower 95% CI of paired mean excess > 0","kill_rule":"lineage violation immediately; otherwise after early_kill_days if excess upper CI < 0 or drawdown exceeds kill_max_drawdown"}

def _mean_ci(values):
    values=list(map(float,values))
    if not values:return None,None,None
    mean=sum(values)/len(values)
    if len(values)<2:return mean,None,None
    variance=sum((x-mean)**2 for x in values)/(len(values)-1);half=1.96*sqrt(variance/len(values))
    return mean,mean-half,mean+half

def evaluate(pairs,protocol=None):
    protocol=protocol or StatisticalProtocolV1();pairs=list(pairs);excess=[float(x["challenger_return"])-float(x["baseline_return"]) for x in pairs];mean,low,high=_mean_ci(excess)
    counts={name:sum(x.get("regime")==name for x in pairs) for name in protocol.required_regimes};equity=peak=0.;dd=0.
    for row in pairs:
        equity+=float(row["challenger_return"]);peak=max(peak,equity);dd=max(dd,peak-equity)
    violations=[x for x in pairs if not x.get("same_window",False) or not x.get("lineage_valid",False)]
    promote=(not violations and len(pairs)>=protocol.paired_eligible_days_minimum and all(v>=protocol.per_required_regime_minimum for v in counts.values()) and low is not None and low>protocol.minimum_mean_excess and sum(float(x["challenger_return"]) for x in pairs)/len(pairs)>protocol.minimum_mean_return and dd<=protocol.challenger_max_drawdown)
    kill=bool(violations) or dd>protocol.kill_max_drawdown or (len(pairs)>=protocol.early_kill_days and high is not None and high<0)
    return {"schema_version":"v5-challenger-evaluation-v1","protocol_id":protocol.protocol_id,"paired_days":len(pairs),"regime_counts":counts,"paired_mean_excess":mean,"paired_excess_ci95":[low,high],"maximum_drawdown":dd,"lineage_violations":len(violations),"decision":"KILL" if kill else "PROMOTE" if promote else "CONTINUE_RESEARCH"}
