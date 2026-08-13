from datetime import datetime,timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from v5.core import CHINA_TZ
from v5.universe import UniverseV1
from v5.market_snapshot import QuoteV1,MarketSnapshotV1
from v5.jobs import produce
NOW=datetime(2026,8,14,9,25,tzinfo=CHINA_TZ)
def snap(at,session):
    q=QuoteV1.from_mapping({"code":"000001","name":"测试","trade_date":at.date().isoformat(),"exchange_time":at-timedelta(seconds=1),"provider_time":at-timedelta(seconds=1),"received_at":at,"last_price":10.2,"previous_close":10,"open_price":10,"high_price":10.3,"low_price":9.9,"bid1":10.19,"bid1_volume":10000,"ask1":10.21,"ask1_volume":10000,"volume":100000,"amount":8000000,"halted":False,"limit_up":False,"limit_down":False,"provider":"test"});return MarketSnapshotV1.build(trade_date=at.date().isoformat(),session=session,batch_started_at=at-timedelta(seconds=2),batch_completed_at=at,quotes=[q],expected_codes=1)
class Source:
    def __init__(self,name,value):self.name=name;self.value=value
    def capture(self,*a,**k):return self.value
def test_jobs_produce_v5_only_mother_pool_and_confirmation_facts():
    with TemporaryDirectory() as d:
        root=Path(d);universe=UniverseV1.build(trade_date="2026-08-14",created_at=NOW,codes=["000001"],sources=["v5_seed"]);universe.save(root);morning=snap(NOW,"morning");pool=produce(root,"morning",now=NOW,sources=(Source("sina",morning),Source("eastmoney",morning)));assert pool["pool_id"].startswith("v5mp1-");assert list((root/"acquisition"/"2026-08-14").glob("*.json"))
        later=NOW.replace(hour=14,minute=50);confirmation=snap(later,"buy");decision=produce(root,"confirmation",now=later,sources=(Source("sina",confirmation),Source("eastmoney",confirmation)));assert decision["confirmation_id"].startswith("v5cd1-") and decision["morning_pool_id"]==pool["pool_id"]
