"""Read-only V5 paper performance and predeclared baseline comparison."""
from __future__ import annotations
from dataclasses import dataclass
from math import sqrt
from typing import Iterable,Mapping

@dataclass(frozen=True)
class PerformanceReportV1:
    cohort:str; trade_count:int; win_rate:float|None; net_pnl:float; average_return:float|None; max_drawdown:float; baseline_name:str; baseline_average_return:float|None; conclusion:str; schema_version:str="v5-performance-report-v1"
    def to_dict(self):return self.__dict__.copy()

def _returns(trips:Iterable[Mapping])->list[float]:
    result=[]
    for row in trips:
        if "net_return" not in row:raise ValueError("round trip: net_return required")
        result.append(float(row["net_return"]))
    return result

def report_strict_paper(trips:Iterable[Mapping],*,baseline_returns:Iterable[float]=(),minimum_trades:int=40,baseline_name:str="equal_weight_next_open") -> PerformanceReportV1:
    """Never mixes proxy data. Below minimum trades emits INSUFFICIENT_EVIDENCE."""
    values=_returns(trips);baseline=[float(x) for x in baseline_returns]
    pnl=sum(float(x.get("net_pnl",0.0)) for x in trips)
    equity=0.0;peak=0.0;drawdown=0.0
    for value in values:
        equity+=value;peak=max(peak,equity);drawdown=min(drawdown,equity-peak)
    average=sum(values)/len(values) if values else None
    base=sum(baseline)/len(baseline) if baseline else None
    if len(values)<minimum_trades:conclusion="INSUFFICIENT_EVIDENCE"
    elif base is None:conclusion="BASELINE_MISSING"
    elif average>base:conclusion="OUTPERFORMS_BASELINE_NOT_ADMISSION"
    else:conclusion="DOES_NOT_OUTPERFORM_BASELINE"
    return PerformanceReportV1("paper_round_trips",len(values),sum(x>0 for x in values)/len(values) if values else None,pnl,average,drawdown,baseline_name,base,conclusion)
