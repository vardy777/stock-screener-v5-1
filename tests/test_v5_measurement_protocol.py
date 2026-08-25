from datetime import datetime
from tempfile import TemporaryDirectory
from v5.core import CHINA_TZ,ContractViolation
from v5.order_quantity import board,floor_quantity,valid_buy
from v5.paper import PaperLedger,PaperEngine,PaperOrderV1
from v5.baseline_policy import registry,BASELINE_HASH,assert_runtime_frozen
from v5.statistical_protocol import StatisticalProtocolV1,evaluate
from v5.factor_research import analyze,observations_from_snapshot,join_strict_labels,_rank
from v5.regime_coverage import report

def test_board_quantity_rules_are_not_one_size_fits_all():
    assert board("688001")=="STAR" and valid_buy("688001",201)
    assert floor_quantity("688001",201.9)==201
    assert not valid_buy("688001",199)
    assert valid_buy("300001",200) and not valid_buy("300001",201)
    assert valid_buy("430001",101)

def test_sell_is_strictly_the_0930_minute():
    with TemporaryDirectory() as root:
        engine=PaperEngine(PaperLedger(root));at=datetime(2026,8,25,9,31,tzinfo=CHINA_TZ)
        order=PaperOrderV1("d","SELL","000001","2026-08-25",at.isoformat(),"10",100,"snap","2026-08-25")
        try:engine.execute(order,at=at)
        except ContractViolation as exc:assert "strict 09:30" in str(exc)
        else:raise AssertionError("09:31 must not be strict sell evidence")

def test_baseline_registry_is_frozen_and_hash_stable():
    value=registry();assert value["mutable"] is False and value["parameter_hash"]==BASELINE_HASH
    assert value["parameters"]["momentum_weight"]==.45 and assert_runtime_frozen()

def test_baseline_runtime_drift_fails_closed(monkeypatch):
    import v5.baseline_policy as frozen
    monkeypatch.setattr(frozen,"MOMENTUM_WEIGHT",.46)
    try:frozen.assert_runtime_frozen()
    except RuntimeError as exc:assert "drift" in str(exc)
    else:raise AssertionError("baseline drift must require a challenger")

def test_preregistered_protocol_cannot_promote_insufficient_data():
    protocol=StatisticalProtocolV1();result=evaluate([{"trade_date":f"2026-01-{i+1:02d}","baseline_return":0,"challenger_return":.01,"same_window":True,"lineage_valid":True,"eligible":True,"market_regime":"STRONG","turnover_regime":"HIGH","large_index_decline":False} for i in range(20)],protocol)
    assert result["decision"]=="CONTINUE_RESEARCH" and protocol.paired_eligible_days_minimum==60

def _promotable():
    markets=("STRONG","NEUTRAL","WEAK");turnovers=("HIGH","NORMAL","LOW")
    return [{"trade_date":f"2026-{1+i//28:02d}-{1+i%28:02d}","pairing_id":str(i),"baseline_return":0,"challenger_return":.01,"same_window":True,"lineage_valid":True,"eligible":True,"market_regime":markets[i%3],"turnover_regime":turnovers[(i//3)%3],"large_index_decline":i<3} for i in range(60)]

def test_protocol_promotes_only_after_coverage_and_real_walk_forward():
    result=evaluate(_promotable());assert result["decision"]=="PROMOTE" and result["walk_forward"]["development"]["count"]==36 and result["walk_forward"]["validation"]["count"]==12 and result["walk_forward"]["holdout"]["count"]==12

def test_protocol_kills_lineage_violation_negative_evidence_and_compounded_drawdown():
    broken=_promotable();broken[0]["lineage_valid"]=False;assert evaluate(broken)["decision"]=="KILL"
    negative=_promotable()[:30]
    for row in negative:row["challenger_return"]=-.01
    assert evaluate(negative)["decision"]=="KILL"
    drawdown=_promotable();drawdown[30]["challenger_return"]=-.13;result=evaluate(drawdown);assert result["decision"]=="KILL" and result["maximum_compounded_drawdown"]>.12

def test_factor_diagnostics_identifies_constant_close_location_without_labels():
    rows=[{"intraday_change":i/100,"amount":100+i,"close_location":.5} for i in range(10)]
    result=analyze(rows);assert result["label_status"]=="INSUFFICIENT_STRICT_LABELS" and result["factors"]["close_location"]["near_constant"] is True

def test_factor_quintiles_are_contiguous_equal_frequency_and_ties_use_average_rank():
    rows=[{"intraday_change":i,"amount":i,"close_location":0 if i<5 else 1,"net_return":i/100} for i in range(10)];result=analyze(rows);groups=result["factors"]["intraday_change"]["quintile_returns"]
    assert [x["count"] for x in groups]==[2,2,2,2,2] and groups[0]["maximum_factor"]<groups[1]["minimum_factor"]
    assert _rank([1,1,3])==[.5,.5,2]

def test_factor_label_join_is_causal_and_rejects_future_or_wrong_snapshot():
    observation={"trade_date":"2026-08-25","snapshot_id":"morning-1","created_at":"2026-08-25T09:25:20+08:00","observations":[{"code":"000001","snapshot_id":"morning-1","observed_at":"2026-08-25T09:25:10+08:00","intraday_change":.01,"amount":1e7,"close_location":.5}]};label={"code":"000001","buy_trade_date":"2026-08-25","morning_snapshot_id":"morning-1","strict_exit_window":True,"sell_recorded_at":"2026-08-26T09:30:10+08:00","net_return":.02}
    joined=join_strict_labels(observation,[label],as_of="2026-08-26T10:00:00+08:00");assert joined["label_status"]=="AVAILABLE"
    try:join_strict_labels(observation,[label],as_of="2026-08-25T15:00:00+08:00")
    except ValueError as exc:assert "future" in str(exc)
    else:raise AssertionError("future exit label must be rejected")
    assert join_strict_labels(observation,[label|{"morning_snapshot_id":"other"}],as_of="2026-08-26T10:00:00+08:00")["label_status"]=="INSUFFICIENT_STRICT_LABELS"

def test_factor_observations_are_point_in_time_and_unlabelled():
    class Quote:
        code="000001";name="平安银行";halted=False;limit_up=False;limit_down=False;amount=9_000_000;previous_close=10;last_price=10.2;high_price=10.3;low_price=9.9;exchange_time="2026-08-25T09:25:10+08:00"
    class Snapshot:snapshot_id="ms1";quotes=(Quote(),)
    rows=observations_from_snapshot(Snapshot());assert rows[0]["snapshot_id"]=="ms1" and "net_return" not in rows[0]

def test_regime_report_requires_diversity_not_round_number():
    value=report([{"market_regime":"STRONG","turnover_regime":"HIGH"} for _ in range(100)])
    assert value["strict_sample_count"]==100 and value["status"]=="ACCUMULATING"
