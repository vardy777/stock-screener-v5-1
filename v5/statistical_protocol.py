"""Frozen, pre-registered challenger evaluation over immutable pairing facts."""
from __future__ import annotations
from dataclasses import dataclass,asdict
from math import sqrt
Z_95=1.959963984540054
@dataclass(frozen=True)
class StatisticalProtocolV1:
    protocol_id:str="v5-challenger-prereg-2026-08-25-v2";paired_eligible_days_minimum:int=60;per_market_regime_minimum:int=10;per_turnover_regime_minimum:int=10;large_decline_minimum:int=3;challenger_max_drawdown:float=.10;kill_max_drawdown:float=.12;minimum_mean_return:float=0.0;minimum_mean_excess:float=0.0;early_kill_days:int=30;required_market_regimes:tuple=("STRONG","NEUTRAL","WEAK");required_turnover_regimes:tuple=("HIGH","NORMAL","LOW");pairing_unit:str="immutable eligible opportunity day; no-trade return is zero"
    def to_dict(self):return asdict(self)|{"confidence_level":.95,"walk_forward":"chronological 60/20/20; validation and untouched holdout independently require positive excess CI lower bounds"}
def _mean_ci(values):
    values=list(map(float,values))
    if not values:return None,None,None
    mean=sum(values)/len(values)
    if len(values)<2:return mean,None,None
    variance=sum((x-mean)**2 for x in values)/(len(values)-1);half=Z_95*sqrt(variance/len(values));return mean,mean-half,mean+half
def _drawdown(returns):
    equity=peak=1.;maximum=0.
    for value in returns:equity*=1+float(value);peak=max(peak,equity);maximum=max(maximum,(peak-equity)/peak)
    return maximum
def _split(rows):
    n=len(rows);a=int(n*.60);b=int(n*.80);return {"development":rows[:a],"validation":rows[a:b],"holdout":rows[b:]}
def _segment(rows):
    mean,low,high=_mean_ci(float(x["challenger_return"])-float(x["baseline_return"]) for x in rows);return {"count":len(rows),"mean_excess":mean,"excess_ci95":[low,high]}
def evaluate(pairing_facts,protocol=None):
    protocol=protocol or StatisticalProtocolV1();all_rows=sorted((dict(x) for x in pairing_facts),key=lambda x:(x.get("trade_date",""),x.get("pairing_id","")));invalid=[x for x in all_rows if not (x.get("eligible") is True and x.get("same_window") is True and x.get("lineage_valid") is True)];rows=[x for x in all_rows if x not in invalid];excess=[float(x["challenger_return"])-float(x["baseline_return"]) for x in rows];mean,low,high=_mean_ci(excess);market={name:sum(x.get("market_regime")==name for x in rows) for name in protocol.required_market_regimes};turnover={name:sum(x.get("turnover_regime")==name for x in rows) for name in protocol.required_turnover_regimes};declines=sum(x.get("index_decline_status")=="VERIFIED_DECLINE" and bool(x.get("index_benchmark_id")) for x in rows);drawdown=_drawdown(x["challenger_return"] for x in rows);segments={name:_segment(values) for name,values in _split(rows).items()};validation_low=segments["validation"]["excess_ci95"][0];holdout_low=segments["holdout"]["excess_ci95"][0];coverage=all(v>=protocol.per_market_regime_minimum for v in market.values()) and all(v>=protocol.per_turnover_regime_minimum for v in turnover.values()) and declines>=protocol.large_decline_minimum
    promote=(not invalid and len(rows)>=protocol.paired_eligible_days_minimum and coverage and low is not None and low>protocol.minimum_mean_excess and validation_low is not None and validation_low>0 and holdout_low is not None and holdout_low>0 and sum(float(x["challenger_return"]) for x in rows)/len(rows)>protocol.minimum_mean_return and drawdown<=protocol.challenger_max_drawdown)
    kill=not invalid and (drawdown>protocol.kill_max_drawdown or (len(rows)>=protocol.early_kill_days and high is not None and high<0))
    decision="EVIDENCE_INVALID" if invalid else "KILL" if kill else "PROMOTE" if promote else "CONTINUE_RESEARCH"
    return {"schema_version":"v5-challenger-evaluation-v2","protocol_id":protocol.protocol_id,"observed_pairing_facts":len(all_rows),"paired_eligible_days":len(rows),"paired_days":len(rows),"excluded_ineligible_days":len(invalid),"evidence_status":"QUARANTINE" if invalid else "VALID","market_regime_counts":market,"regime_counts":market,"turnover_regime_counts":turnover,"large_decline_count":declines,"coverage_passed":coverage,"paired_mean_excess":mean,"paired_excess_ci95":[low,high],"maximum_compounded_drawdown":drawdown,"maximum_drawdown":drawdown,"walk_forward":segments,"decision":decision}
