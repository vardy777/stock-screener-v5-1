from datetime import datetime,timedelta
import pytest
from shared_core.core import ContractViolation
from shared_core.market_snapshot import MarketSnapshotV1,QuoteV1
from v5_1.execution import build_execution_observation
from v5_1 import BASELINE_STRATEGY_VERSION

DAY="2026-08-28"
DECISION=datetime.fromisoformat("2026-08-28T14:50:10+08:00")

def snapshot(observed):
    q=QuoteV1.from_mapping({"code":"600000","name":"浦发银行","trade_date":DAY,"exchange_time":observed,"provider_time":observed,"received_at":observed,"last_price":10.2,"previous_close":10,"open_price":10.1,"high_price":10.3,"low_price":10,"bid1":10.19,"bid1_volume":10000,"ask1":10.21,"ask1_volume":10000,"volume":100000,"amount":10000000,"halted":False,"limit_up":False,"limit_down":False,"provider":"dual_conservative"})
    return MarketSnapshotV1.build(trade_date=DAY,session="buy_execution",batch_started_at=observed,batch_completed_at=observed,quotes=[q],expected_codes=1)

@pytest.mark.parametrize("age",[0,.1,.8,2,4.9,5.0])
def test_execution_observation_accepts_post_network_quote_up_to_five_seconds(age):
    observed=DECISION+timedelta(seconds=1);snap=snapshot(observed)
    fact=build_execution_observation(snap,side="BUY",strategy_id=BASELINE_STRATEGY_VERSION,decision_id="decision",decision_snapshot_id="ms1-decision",decision_time=DECISION,execution_time=observed+timedelta(seconds=age),code="600000")
    assert fact.execution_observation_time==observed.isoformat()

def test_execution_observation_rejects_5_1_seconds_and_observation_after_execution():
    observed=DECISION+timedelta(seconds=1);snap=snapshot(observed)
    with pytest.raises(ContractViolation,match="stale"):build_execution_observation(snap,side="BUY",strategy_id=BASELINE_STRATEGY_VERSION,decision_id="decision",decision_snapshot_id="ms1-decision",decision_time=DECISION,execution_time=observed+timedelta(seconds=5.1),code="600000")
    with pytest.raises(ContractViolation,match="required"):build_execution_observation(snap,side="BUY",strategy_id=BASELINE_STRATEGY_VERSION,decision_id="decision",decision_snapshot_id="ms1-decision",decision_time=DECISION,execution_time=observed-timedelta(milliseconds=1),code="600000")
