from datetime import datetime,timedelta
from tempfile import TemporaryDirectory
from v5.core import CHINA_TZ
from v5.market_snapshot import QuoteV1,MarketSnapshotV1
from v5.paper_production import PaperProduction
NOW=datetime(2026,8,14,14,50,tzinfo=CHINA_TZ)
def snapshot(at,session,price):
 q=QuoteV1.from_mapping({"code":"000001","name":"测试","trade_date":at.date().isoformat(),"exchange_time":at-timedelta(seconds=1),"provider_time":at-timedelta(seconds=1),"received_at":at,"last_price":price,"previous_close":10,"open_price":10,"high_price":price,"low_price":9.9,"bid1":price-.01,"bid1_volume":10000,"ask1":price+.01,"ask1_volume":10000,"volume":100000,"amount":8000000,"halted":False,"limit_up":False,"limit_down":False,"provider":"test"});return MarketSnapshotV1.build(trade_date=at.date().isoformat(),session=session,batch_started_at=at-timedelta(seconds=2),batch_completed_at=at,quotes=[q],expected_codes=1)
def test_production_adapter_uses_only_final_v5_confirmation_and_reconciles():
 with TemporaryDirectory() as d:
  p=PaperProduction(d);confirmation={"outcome":"BUY_CANDIDATE","confirmation_id":"v5cd1-test","trade_date":"2026-08-14","candidates":[{"code":"000001"}]};buy=p.buy(confirmation,snapshot(NOW,"buy",10.2),at=NOW,eligible_sell_date="2026-08-17");assert buy.outcome=="FILLED"
  sell_at=datetime(2026,8,17,9,30,tzinfo=CHINA_TZ);events=p.sell_all(snapshot(sell_at,"sell",10.4),at=sell_at);assert events[0].outcome=="FILLED" and p.ledger.reconcile()["passed"]
