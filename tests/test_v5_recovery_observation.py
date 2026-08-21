from datetime import datetime,timedelta
from v5.core import CHINA_TZ,ContractViolation
from v5.recovery_observation import run
from v5.market_snapshot import MarketSnapshotV1,QuoteV1
from v5.universe import UniverseV1

def test_recovery_observation_rejects_outside_narrow_afternoon_window(tmp_path):
    try:run(tmp_path,now=datetime(2026,8,21,11,50,tzinfo=CHINA_TZ),transport=lambda:{"code":200})
    except ContractViolation as exc:assert "outside" in str(exc)
    else:raise AssertionError("must fail closed")

def test_recovery_source_declares_no_strategy_or_paper_eligibility():
    text=open("v5/recovery_observation.py",encoding="utf-8").read()
    assert '"strict_0925_sample":False' in text
    assert '"eligible_for_confirmation":False' in text
    assert '"eligible_for_paper":False' in text

def test_recovery_observation_serializes_frozen_candidates_and_records_acceptance(tmp_path):
    now=datetime(2026,8,21,13,1,tzinfo=CHINA_TZ)
    UniverseV1.build(trade_date="2026-08-21",created_at=now-timedelta(minutes=1),codes=["000001"],sources=["eastmoney_realtime_market_directory"]).save(tmp_path)
    def snapshot(provider):
        quote=QuoteV1.from_mapping({"code":"000001","name":"测试","trade_date":"2026-08-21","exchange_time":now-timedelta(seconds=1),"provider_time":now-timedelta(seconds=1),"received_at":now,"last_price":10.8,"previous_close":10,"open_price":10,"high_price":10.9,"low_price":9.9,"bid1":10.79,"bid1_volume":10000,"ask1":10.81,"ask1_volume":10000,"volume":100000,"amount":80_000_000,"halted":False,"limit_up":False,"limit_down":False,"provider":provider})
        return MarketSnapshotV1.build(trade_date="2026-08-21",session="signal",batch_started_at=now-timedelta(seconds=2),batch_completed_at=now,quotes=[quote],expected_codes=1)
    class Source:
        def __init__(self,name):self.name=name
        def capture(self,*args,**kwargs):return snapshot(self.name)
    result=run(tmp_path,now=now,sources=(Source("first"),Source("second")),transport=lambda:{"code":200})
    assert result["receipt"]["outcome"]=="ACCEPTED"
    assert result["observation"]["strict_0925_sample"] is False
    assert result["observation"]["eligible_for_confirmation"] is False
    assert list((tmp_path/"recovery_observations/2026-08-21").glob("*.json"))
