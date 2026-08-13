from datetime import datetime,timedelta
from v5.core import CHINA_TZ
from v5.market_snapshot import QuoteV1,MarketSnapshotV1
from v5.market_state import MarketStateV1
from v5.funnel import CandidateFunnel
from v5.decision_flow import MorningPoolV5

NOW=datetime(2026,8,14,14,49,tzinfo=CHINA_TZ)
def snapshot(changes):
 quotes=[]
 for index,change in enumerate(changes):
  price=10*(1+change);quotes.append(QuoteV1.from_mapping({"code":str(index+1).zfill(6),"name":"测试","trade_date":"2026-08-14","exchange_time":NOW-timedelta(seconds=1),"provider_time":NOW-timedelta(seconds=1),"received_at":NOW,"last_price":price,"previous_close":10,"open_price":10,"high_price":max(price,10),"low_price":min(price,10),"bid1":price-.01,"bid1_volume":1000,"ask1":price+.01,"ask1_volume":1000,"volume":1000,"amount":10000000,"halted":False,"limit_up":False,"limit_down":False,"provider":"test"}))
 return MarketSnapshotV1.build(trade_date="2026-08-14",session="signal",batch_started_at=NOW-timedelta(seconds=2),batch_completed_at=NOW,quotes=quotes,expected_codes=len(quotes))
def test_market_state_is_snapshot_lineaged_and_risk_off_on_broad_decline():
 good=MarketStateV1.from_snapshot(snapshot([.01,.02,-.01,0]));assert good.trade_allowed and good.regime=="NEUTRAL" and good.market_state_id.startswith("mstate1-")
 bad=MarketStateV1.from_snapshot(snapshot([-.06,-.07,-.01,0]));assert not bad.trade_allowed and "MARKET_BREADTH_TOO_WEAK" in bad.reasons and "SEVERE_DECLINE_TOO_BROAD" in bad.reasons
 funnel=CandidateFunnel().run(snapshot([-.06,-.07,-.01,0]),market_state_id=bad.market_state_id,market_valid=bad.trade_allowed,stage="morning");pool=MorningPoolV5.from_funnel(funnel,created_at=NOW);assert pool.candidates==()
 raw=good.to_dict();assert MarketStateV1.from_mapping(raw).market_state_id==good.market_state_id;raw["advancers"]+=1
 try:MarketStateV1.from_mapping(raw)
 except ValueError:pass
 else:raise AssertionError("tampered market state accepted")
