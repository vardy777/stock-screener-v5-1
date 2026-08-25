from datetime import datetime,timedelta
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from v5.core import CHINA_TZ
from v5.universe import UniverseV1
from v5.market_snapshot import QuoteV1,MarketSnapshotV1
from v5.jobs import produce,freeze,confirm_frozen,load_universe
from v5.index_benchmark import source_observation
import pytest
NOW=datetime(2026,8,14,9,25,tzinfo=CHINA_TZ)
def snap(at,session):
    q=QuoteV1.from_mapping({"code":"000001","name":"测试","trade_date":at.date().isoformat(),"exchange_time":at-timedelta(seconds=1),"provider_time":at-timedelta(seconds=1),"received_at":at,"last_price":10.2,"previous_close":10,"open_price":10,"high_price":10.3,"low_price":9.9,"bid1":10.19,"bid1_volume":10000,"ask1":10.21,"ask1_volume":10000,"volume":100000,"amount":8000000,"halted":False,"limit_up":False,"limit_down":False,"provider":"test"});return MarketSnapshotV1.build(trade_date=at.date().isoformat(),session=session,batch_started_at=at-timedelta(seconds=2),batch_completed_at=at,quotes=[q],expected_codes=1)
class Source:
    def __init__(self,name,value):self.name=name;self.value=value
    def capture(self,*a,**k):
        rows=[]
        for item in self.value.quotes:
            row=item.to_dict();row["provider"]=self.name;rows.append(QuoteV1.from_mapping(row))
        return MarketSnapshotV1.build(trade_date=self.value.trade_date,session=self.value.session,batch_started_at=self.value.batch_started_at,batch_completed_at=self.value.batch_completed_at,quotes=rows,expected_codes=self.value.quality.expected_codes)
class IndexSource:
    def __init__(self,name,at,price=3980):self.name=name;self.at=at;self.price=price
    def capture(self,now):return source_observation(observed_at=self.at.isoformat(),previous_close=4000,last_price=self.price,provider=self.name,source_snapshot_id=f"idxresp-{self.name}")
def index_sources(at):return (IndexSource("index_a",at),IndexSource("index_b",at,3979))
def test_jobs_produce_v5_only_mother_pool_and_confirmation_facts():
    with TemporaryDirectory() as d:
        root=Path(d);universe=UniverseV1.build(trade_date="2026-08-14",created_at=NOW,codes=["000001"],sources=["eastmoney_realtime_market_directory"]);universe.save(root);morning=snap(NOW,"morning");pool=produce(root,"morning",now=NOW,sources=(Source("sina",morning),Source("eastmoney",morning)));assert pool["pool_id"].startswith("v5mp1-");assert list((root/"acquisition"/"2026-08-14").glob("*.json"))
        later=NOW.replace(hour=14,minute=49);confirmation=snap(later,"signal");frozen=freeze(root,now=later,sources=(Source("sina",confirmation),Source("eastmoney",confirmation)),index_sources=index_sources(later));decision=confirm_frozen(root,now=later.replace(minute=50));assert decision["confirmation_id"].startswith("v5cd1-") and decision["morning_pool_id"]==pool["pool_id"] and decision["snapshot_id"]==frozen["snapshot_id"]
def test_feature_freeze_persists_independent_pointer_before_confirmation():
    with TemporaryDirectory() as d:
        root=Path(d);universe=UniverseV1.build(trade_date="2026-08-14",created_at=NOW,codes=["000001"],sources=["eastmoney_realtime_market_directory"]);universe.save(root);at=NOW.replace(hour=14,minute=49);signal=snap(at,"signal");result=freeze(root,now=at,sources=(Source("sina",signal),Source("eastmoney",signal)),index_sources=index_sources(at));assert result["snapshot_id"].startswith("ms1-") and result["acquisition_session_id"].startswith("acq1-") and (root/"frozen/2026-08-14/signal.json").exists() and result["index_benchmark_capture"]["status"]=="VERIFIED_NOT_DECLINE"
        states=list((root/"market_states/2026-08-14").glob("*.json"));assert len(states)==1 and json.loads(states[0].read_text())["snapshot_id"]==result["snapshot_id"]
        assert freeze(root,now=at,sources=(Source("sina",signal),Source("eastmoney",signal)),index_sources=index_sources(at))==result
        changed=snap(at+timedelta(seconds=1),"signal")
        with pytest.raises(Exception,match="frozen pointer immutable collision"):freeze(root,now=at+timedelta(seconds=1),sources=(Source("sina",changed),Source("eastmoney",changed)),index_sources=index_sources(at+timedelta(seconds=1)))
        assert len(list((root/"consensus/2026-08-14").glob("cons1-*.json")))==2
def test_feature_freeze_index_single_source_is_observable_unknown_but_non_blocking():
    with TemporaryDirectory() as d:
        root=Path(d);UniverseV1.build(trade_date="2026-08-14",created_at=NOW,codes=["000001"],sources=["eastmoney_realtime_market_directory"]).save(root);at=NOW.replace(hour=14,minute=49);signal=snap(at,"signal")
        result=freeze(root,now=at,sources=(Source("sina",signal),Source("eastmoney",signal)),index_sources=(IndexSource("only_one",at),))
        assert result["snapshot_id"].startswith("ms1-") and result["index_benchmark_capture"]["status"]=="UNKNOWN" and result["index_benchmark_capture"]["errors"]
def test_load_universe_selects_latest_business_time_not_hash_filename():
    with TemporaryDirectory() as d:
        root=Path(d);UniverseV1.build(trade_date="2026-08-14",created_at=NOW,codes=["000001"],sources=["seed"]).save(root);UniverseV1.build(trade_date="2026-08-14",created_at=NOW+timedelta(minutes=1),codes=["000001","000002"],sources=["live"]).save(root);assert load_universe(root,"2026-08-14").codes==("000001","000002")
def test_load_universe_is_causal_and_native_when_used_by_production():
    with TemporaryDirectory() as d:
        root=Path(d);UniverseV1.build(trade_date="2026-08-14",created_at=NOW-timedelta(minutes=1),codes=["000001"],sources=["legacy_daily_archive_seed_migration"]).save(root);UniverseV1.build(trade_date="2026-08-14",created_at=NOW+timedelta(minutes=1),codes=["000001","000002"],sources=["eastmoney_realtime_market_directory"]).save(root)
        try:load_universe(root,"2026-08-14",as_of=NOW,require_native=True)
        except Exception as exc:assert "native V5 universe fact missing" in str(exc)
        else:raise AssertionError("future native universe must not satisfy production")
