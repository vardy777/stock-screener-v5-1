from datetime import datetime,timedelta
from tempfile import TemporaryDirectory
from v5.core import CHINA_TZ
from v5.market_snapshot import QuoteV1,MarketSnapshotV1
from v5.universe import UniverseV1
from v5.paper import PaperLedger
from v5.replay import replay
NOW=datetime(2026,8,13,9,25,tzinfo=CHINA_TZ)
def snap(price,at,session):
    q=QuoteV1.from_mapping({"code":"000001","name":"测试","trade_date":at.date().isoformat(),"exchange_time":at-timedelta(seconds=1),"provider_time":at-timedelta(seconds=1),"received_at":at,"last_price":price,"previous_close":10,"open_price":10,"high_price":max(10.3,price),"low_price":9.9,"bid1":price-.01,"bid1_volume":10000,"ask1":price+.01,"ask1_volume":10000,"volume":100000,"amount":8000000,"halted":False,"limit_up":False,"limit_down":False,"provider":"frozen"})
    return MarketSnapshotV1.build(trade_date=at.date().isoformat(),session=session,batch_started_at=at-timedelta(seconds=2),batch_completed_at=at,quotes=[q],expected_codes=1)
class Source:
    def __init__(self,name,value):self.name=name;self.value=value
    def capture(self,*a,**k):
        if isinstance(self.value,Exception):raise self.value
        return self.value
def test_frozen_end_to_end_replay_is_complete_idempotent_and_insufficient_evidence():
    universe=UniverseV1.build(trade_date="2026-08-13",created_at=NOW,codes=["000001"],sources=["frozen"]);morning=snap(10.1,NOW,"morning");confirm_at=NOW.replace(hour=14,minute=50);confirm=snap(10.2,confirm_at,"buy");sell_at=NOW+timedelta(days=1,seconds=5);sell_at=sell_at.replace(hour=9,minute=30);sell=snap(10.4,sell_at,"sell")
    with TemporaryDirectory() as d:
        ledger=PaperLedger(d);args=dict(universe=universe,morning_sources=(Source("a",morning),Source("b",morning)),confirmation_sources=(Source("a",confirm),Source("b",confirm)),morning_at=NOW,confirmation_at=confirm_at,sell_snapshot=sell,sell_at=sell_at,ledger=ledger)
        result=replay(**args);assert result["status"]=="COMPLETED" and result["reconciliation"]["passed"] and result["performance"]["conclusion"]=="INSUFFICIENT_EVIDENCE"
        assert replay(**args)["buy_event_id"]==result["buy_event_id"] and ledger.state()["event_count"]==2
def test_source_failure_fails_closed_before_decision():
    universe=UniverseV1.build(trade_date="2026-08-13",created_at=NOW,codes=["000001"],sources=["frozen"]);morning=snap(10.1,NOW,"morning")
    with TemporaryDirectory() as d:
        result=replay(universe=universe,morning_sources=(Source("a",morning),Source("b",RuntimeError("down"))),confirmation_sources=(Source("a",morning),Source("b",morning)),morning_at=NOW,confirmation_at=NOW,sell_snapshot=morning,sell_at=NOW,ledger=PaperLedger(d));assert result["status"]=="REJECTED" and result["stage"]=="morning_consensus"
