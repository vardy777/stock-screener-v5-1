from datetime import datetime,timedelta
import pytest
from shared_core.core import CHINA_TZ,ContractViolation
from shared_core.market_snapshot import MarketSnapshotV1,QuoteV1
from v5_1.decision import MAX_MORNING_SNAPSHOT_AGE_SECONDS,DecisionSnapshotRepository,build_morning_pool,build_confirmation
from v5_1.execution import build_execution_observation,StrategyPaperExecutorV51
from v5_1.closescan import build_facts,select,isolated_ledgers
from v5_1.tradability import DailyTradabilityFactV1
from v5_1.storage import V51FactStore

DAY="2026-08-28"
def quote(code="600000",at="2026-08-28T09:34:55+08:00",**kw):
 row={"code":code,"name":"浦发银行","trade_date":DAY,"exchange_time":at,"provider_time":at,"received_at":at,"last_price":10.2,"previous_close":10,"open_price":10.1,"high_price":10.3,"low_price":10,"bid1":10.19,"bid1_volume":10000,"ask1":10.21,"ask1_volume":10000,"volume":1000000,"amount":10000000,"halted":False,"limit_up":False,"limit_down":False,"provider":"consensus_conservative"};row.update(kw);return QuoteV1.from_mapping(row)
def snap(at="2026-08-28T09:34:59+08:00",session="morning_0935",quotes=None):
 completed=datetime.fromisoformat(at);return MarketSnapshotV1.build(trade_date=DAY,session=session,batch_started_at=completed-timedelta(seconds=2),batch_completed_at=completed,quotes=quotes or [quote(at=(completed-timedelta(seconds=1)).isoformat())],expected_codes=len(quotes or [1]))
def tradability(*codes):
 return DailyTradabilityFactV1(DAY,"2026-08-28T09:34:00+08:00","smverify1-x",tuple("smv1-"+x for x in codes),tuple("status1-"+x for x in codes),tuple(codes),(),1.0,True)
def frozen(tmp_path,snapshot):
 repo=DecisionSnapshotRepository(tmp_path);return repo,repo.freeze(snapshot,"2026-08-28T14:49:31+08:00")

def test_0935_morning_accepts_0934_data_and_rejects_future_or_wrong_window():
 pool=build_morning_pool(snap(),tradability("600000"),decided_at="2026-08-28T09:35:00+08:00",market_state_id="mstate1-x",market_valid=True)
 assert pool.strategy_version=="v5.1-baseline-0935-v1" and pool.candidates[0]["candidate_origin"]=="V5.1_BASELINE_0935"
 with pytest.raises(ContractViolation,match="outside"):build_morning_pool(snap(),tradability("600000"),decided_at="2026-08-28T09:25:00+08:00",market_state_id="mstate1-x",market_valid=True)
 with pytest.raises(ContractViolation,match="future"):build_morning_pool(snap("2026-08-28T09:35:01+08:00"),tradability("600000"),decided_at="2026-08-28T09:35:00+08:00",market_state_id="mstate1-x",market_valid=True)
 stale=snap("2026-08-28T09:30:00+08:00")
 with pytest.raises(ContractViolation,match="stale at decision"):build_morning_pool(stale,tradability("600000"),decided_at="2026-08-28T09:35:00+08:00",market_state_id="mstate1-x",market_valid=True)
 assert MAX_MORNING_SNAPSHOT_AGE_SECONDS==30

def test_0935_rejects_bad_coverage_and_ranking_is_deterministic():
 bad=MarketSnapshotV1.build(trade_date=DAY,session="morning_0935",batch_started_at=datetime(2026,8,28,9,34,55,tzinfo=CHINA_TZ),batch_completed_at=datetime(2026,8,28,9,34,59,tzinfo=CHINA_TZ),quotes=[quote()],expected_codes=2)
 with pytest.raises(ContractViolation,match="accepted"):build_morning_pool(bad,tradability("600000"),decided_at="2026-08-28T09:35:00+08:00",market_state_id="mstate1-x",market_valid=True)
 quotes=[quote("600000"),quote("600001",last_price=10.3,amount=20000000)];snapshot=snap(quotes=quotes)
 a=build_morning_pool(snapshot,tradability("600000","600001"),decided_at="2026-08-28T09:35:00+08:00",market_state_id="mstate1-x",market_valid=True);b=build_morning_pool(snapshot,tradability("600000","600001"),decided_at="2026-08-28T09:35:00+08:00",market_state_id="mstate1-x",market_valid=True)
 assert a.pool_id==b.pool_id and [x["code"] for x in a.candidates]==[x["code"] for x in b.candidates]

def test_confirmation_is_same_pool_subset_and_records_0935_to_1450_change(tmp_path):
 pool=build_morning_pool(snap(),tradability("600000"),decided_at="2026-08-28T09:35:00+08:00",market_state_id="mstate1-m",market_valid=True)
 signal=snap("2026-08-28T14:49:30+08:00","signal",[quote(at="2026-08-28T14:49:29+08:00",last_price=10.4,amount=30000000)])
 repo,freeze=frozen(tmp_path,signal);result=build_confirmation(pool,signal,freeze=freeze,snapshot_repository=repo,decided_at="2026-08-28T14:50:00+08:00",market_state_id="mstate1-s",market_valid=True)
 assert result.morning_pool_id==pool.pool_id and set(x["code"] for x in result.candidates)<=set(x["code"] for x in pool.candidates) and result.changes

def test_execution_snapshot_is_post_decision_distinct_and_executable():
 decision=snap("2026-08-28T14:49:30+08:00","signal",[quote(at="2026-08-28T14:49:29+08:00")]);execution=snap("2026-08-28T14:50:42+08:00","buy_execution",[quote(at="2026-08-28T14:50:41+08:00")])
 fact=build_execution_observation(execution,side="BUY",strategy_id="baseline",decision_id="decision-x",decision_snapshot_id=decision.snapshot_id,decision_time="2026-08-28T14:50:00+08:00",execution_time="2026-08-28T14:50:43+08:00",code="600000")
 assert fact.decision_snapshot_id!=fact.execution_snapshot_id and fact.decision_time<fact.execution_observation_time<=fact.execution_time
 with pytest.raises(ContractViolation,match="independent"):build_execution_observation(decision,side="BUY",strategy_id="baseline",decision_id="x",decision_snapshot_id=decision.snapshot_id,decision_time="2026-08-28T14:49:00+08:00",execution_time="2026-08-28T14:50:00+08:00",code="600000")
 no_ask=snap("2026-08-28T14:50:42+08:00","buy_execution",[quote(at="2026-08-28T14:50:41+08:00",ask1=0,ask1_volume=0)])
 with pytest.raises(ContractViolation,match="ask"):build_execution_observation(no_ask,side="BUY",strategy_id="baseline",decision_id="x",decision_snapshot_id=decision.snapshot_id,decision_time="2026-08-28T14:50:00+08:00",execution_time="2026-08-28T14:50:43+08:00",code="600000")

def test_sell_execution_uses_post_open_bid_and_rejects_limit_down():
 decision=snap("2026-08-28T14:49:30+08:00","signal",[quote(at="2026-08-28T14:49:29+08:00")]);sell=snap("2026-08-28T09:30:10+08:00","sell_execution",[quote(at="2026-08-28T09:30:09+08:00")])
 fact=build_execution_observation(sell,side="SELL",strategy_id="baseline",decision_id="exit-policy",decision_snapshot_id=decision.snapshot_id,decision_time="2026-08-28T09:30:00+08:00",execution_time="2026-08-28T09:30:11+08:00",code="600000");assert fact.bid1>0
 blocked=snap("2026-08-28T09:30:10+08:00","sell_execution",[quote(at="2026-08-28T09:30:09+08:00",limit_down=True)])
 with pytest.raises(ContractViolation,match="bid"):build_execution_observation(blocked,side="SELL",strategy_id="baseline",decision_id="x",decision_snapshot_id=decision.snapshot_id,decision_time="2026-08-28T09:30:00+08:00",execution_time="2026-08-28T09:30:11+08:00",code="600000")

def test_closescan_has_full_market_origin_no_morning_dependency_and_isolated_ledger(tmp_path):
 signal=snap("2026-08-28T14:49:30+08:00","signal",[quote(at="2026-08-28T14:49:29+08:00")]);repo,freeze=frozen(tmp_path/"facts",signal);facts=build_facts(signal,tradability("600000"),freeze=freeze,snapshot_repository=repo,decided_at="2026-08-28T14:50:00+08:00",market_state_id="mstate1-s",market_valid=True);result=facts.selection
 assert result.strategy_version=="v5.1-closescan-v1" and result.candidates[0]["candidate_origin"]=="CLOSESCAN_FULL_MARKET_1449" and not hasattr(result,"morning_pool_id")
 assert facts.candidates.decision_snapshot_id==result.decision_snapshot_id and facts.run.selection_id==result.selection_id and facts.run.candidate_fact_id==facts.candidates.candidate_fact_id
 store=V51FactStore(tmp_path/"store");assert store.save("closescan_candidates",facts.candidates).exists() and store.save("closescan_selections",facts.selection).exists() and store.save("closescan_runs",facts.run).exists()
 baseline,closescan=isolated_ledgers(tmp_path);assert baseline.root!=closescan.root

def test_strategy_paper_fill_is_deterministic_with_slippage_fees_and_isolation(tmp_path):
 decision=snap("2026-08-28T14:49:30+08:00","signal",[quote(at="2026-08-28T14:49:29+08:00")]);buy_snapshot=snap("2026-08-28T14:50:42+08:00","buy_execution",[quote(at="2026-08-28T14:50:41+08:00")])
 buy=build_execution_observation(buy_snapshot,side="BUY",strategy_id="closescan",decision_id="close-x",decision_snapshot_id=decision.snapshot_id,decision_time="2026-08-28T14:50:00+08:00",execution_time="2026-08-28T14:50:43+08:00",code="600000")
 close=StrategyPaperExecutorV51(tmp_path,"closescan");baseline=StrategyPaperExecutorV51(tmp_path,"baseline");event=close.buy(buy,eligible_sell_date="2026-08-31")
 assert event.outcome=="FILLED" and float(event.fill_price)>buy.ask1 and float(event.commission)>0 and baseline.ledger.state()["positions"]==[]
 # Same deterministic decision/order is idempotent in the event-sourced engine.
 repeated=close.buy(buy,eligible_sell_date="2026-08-31");assert repeated.event_id==event.event_id

def test_stale_execution_snapshot_is_rejected_before_fill():
 old=MarketSnapshotV1.build(trade_date=DAY,session="buy_execution",batch_started_at=datetime(2026,8,28,14,50,40,tzinfo=CHINA_TZ),batch_completed_at=datetime(2026,8,28,14,50,42,tzinfo=CHINA_TZ),quotes=[quote(at="2026-08-28T14:49:00+08:00")],expected_codes=1)
 assert not old.quality.accepted
 with pytest.raises(ContractViolation,match="accepted"):build_execution_observation(old,side="BUY",strategy_id="baseline",decision_id="x",decision_snapshot_id="ms1-decision",decision_time="2026-08-28T14:50:00+08:00",execution_time="2026-08-28T14:50:43+08:00",code="600000")

def test_feature_freeze_rejects_old_outside_future_wrong_day_and_missing_pointer(tmp_path):
 repo=DecisionSnapshotRepository(tmp_path);valid=snap("2026-08-28T14:49:30+08:00","signal",[quote(at="2026-08-28T14:49:29+08:00")]);freeze=repo.freeze(valid,"2026-08-28T14:49:31+08:00");assert repo.require(freeze,valid)==freeze
 for at in ("2026-08-28T10:00:00+08:00","2026-08-28T14:48:59+08:00","2026-08-28T14:50:00+08:00"):
  candidate=snap(at,"signal",[quote(at=at)])
  with pytest.raises(ContractViolation):repo.freeze(candidate,"2026-08-28T14:49:31+08:00")
 missing=DecisionSnapshotRepository(tmp_path/"missing")
 with pytest.raises(ContractViolation,match="missing"):missing.require(freeze,valid)

def test_execution_quote_age_and_causal_boundaries_fail_closed():
 decision=snap("2026-08-28T14:49:30+08:00","signal",[quote(at="2026-08-28T14:49:29+08:00")]);fresh=snap("2026-08-28T14:50:42+08:00","buy_execution",[quote(at="2026-08-28T14:50:41+08:00")])
 with pytest.raises(ContractViolation,match="stale at fill"):build_execution_observation(fresh,side="BUY",strategy_id="baseline",decision_id="x",decision_snapshot_id=decision.snapshot_id,decision_time="2026-08-28T14:50:00+08:00",execution_time="2026-08-28T14:51:00+08:00",code="600000")
 with pytest.raises(ContractViolation,match="required"):build_execution_observation(fresh,side="BUY",strategy_id="baseline",decision_id="x",decision_snapshot_id=decision.snapshot_id,decision_time="2026-08-28T14:50:43+08:00",execution_time="2026-08-28T14:50:44+08:00",code="600000")
 with pytest.raises(ContractViolation,match="required"):build_execution_observation(fresh,side="BUY",strategy_id="baseline",decision_id="x",decision_snapshot_id=decision.snapshot_id,decision_time="2026-08-28T14:50:00+08:00",execution_time="2026-08-28T14:50:41+08:00",code="600000")
 missing_bid=snap("2026-08-28T09:30:10+08:00","sell_execution",[quote(at="2026-08-28T09:30:09+08:00",bid1=0,bid1_volume=0)])
 with pytest.raises(ContractViolation,match="bid"):build_execution_observation(missing_bid,side="SELL",strategy_id="baseline",decision_id="x",decision_snapshot_id=decision.snapshot_id,decision_time="2026-08-28T09:30:00+08:00",execution_time="2026-08-28T09:30:11+08:00",code="600000")

def test_quote_contract_rejects_string_boolean():
 with pytest.raises(ContractViolation,match="strict boolean"):quote(halted="false")
