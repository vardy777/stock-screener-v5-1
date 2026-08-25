from datetime import datetime
from tempfile import TemporaryDirectory
from v5.core import CHINA_TZ,ContractViolation
from v5.order_quantity import board,floor_quantity,valid_buy
from v5.paper import PaperLedger,PaperEngine,PaperOrderV1
from v5.baseline_policy import registry,BASELINE_HASH,assert_runtime_frozen
from v5.statistical_protocol import StatisticalProtocolV1,evaluate
from v5.factor_research import analyze,observations_from_snapshot
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

def test_preregistered_protocol_cannot_promote_insufficient_data():
    protocol=StatisticalProtocolV1();result=evaluate([{"baseline_return":0,"challenger_return":.01,"same_window":True,"lineage_valid":True,"regime":"STRONG"}]*20,protocol)
    assert result["decision"]=="CONTINUE_RESEARCH" and protocol.paired_eligible_days_minimum==60

def test_factor_diagnostics_identifies_constant_close_location_without_labels():
    rows=[{"intraday_change":i/100,"amount":100+i,"close_location":.5} for i in range(10)]
    result=analyze(rows);assert result["label_status"]=="INSUFFICIENT_STRICT_LABELS" and result["factors"]["close_location"]["near_constant"] is True

def test_factor_observations_are_point_in_time_and_unlabelled():
    class Quote:
        code="000001";name="平安银行";halted=False;limit_up=False;limit_down=False;amount=9_000_000;previous_close=10;last_price=10.2;high_price=10.3;low_price=9.9;exchange_time="2026-08-25T09:25:10+08:00"
    class Snapshot:snapshot_id="ms1";quotes=(Quote(),)
    rows=observations_from_snapshot(Snapshot());assert rows[0]["snapshot_id"]=="ms1" and "net_return" not in rows[0]

def test_regime_report_requires_diversity_not_round_number():
    value=report([{"market_regime":"STRONG","turnover_regime":"HIGH"} for _ in range(100)])
    assert value["strict_sample_count"]==100 and value["status"]=="ACCUMULATING"
