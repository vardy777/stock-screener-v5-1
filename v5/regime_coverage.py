"""Strict-sample coverage across market regimes; never fabricates samples."""
from __future__ import annotations
def report(samples):
    samples=list(samples);market={name:sum(x.get("market_regime")==name for x in samples) for name in ("STRONG","NEUTRAL","WEAK")};turnover={name:sum(x.get("turnover_regime")==name for x in samples) for name in ("HIGH","NORMAL","LOW")}
    covered=[name for name,count in market.items() if count>0]
    return {"schema_version":"v5-strict-regime-coverage-v1","strict_sample_count":len(samples),"market_regime_counts":market,"turnover_regime_counts":turnover,"large_decline_count":sum(bool(x.get("large_index_decline")) for x in samples),"covered_market_regimes":covered,"sufficient_diversity":len(covered)==3 and all(turnover.values()),"status":"DIVERSE" if len(covered)==3 and all(turnover.values()) else "ACCUMULATING"}
