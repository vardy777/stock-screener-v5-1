import hashlib,json
from datetime import datetime,timedelta
from v5.core import CHINA_TZ
from v5.market_snapshot import QuoteV1,MarketSnapshotV1
from v5.factor_cross_section import capture_exit
from v5.index_capture import capture as capture_index
from v5.index_benchmark import source_observation

MORNING=datetime(2026,8,25,9,25,20,tzinfo=CHINA_TZ);SELL=datetime(2026,8,26,9,30,20,tzinfo=CHINA_TZ)
def diagnostic(root,count=100):
    observations=[{"code":f"{i+1:06d}","snapshot_id":"ms1-morning-full","observed_at":MORNING.isoformat(),"last_price":10+i/100,"intraday_change":i/10000,"amount":10_000_000+i,"amount_percentile":i/(count-1),"close_location":.5} for i in range(count)]
    value={"schema_version":"v5-factor-diagnostics-v2","trade_date":"2026-08-25","created_at":MORNING.isoformat(),"snapshot_id":"ms1-morning-full","observations":observations};entity="fac1-"+hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode()).hexdigest()[:24];path=root/"factor_diagnostics/2026-08-25"/f"{entity}.json";path.parent.mkdir(parents=True);path.write_text(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(",",":")),encoding="utf-8")
class ExitSource:
    def __init__(self,name,conflicts=0):self.name=name;self.conflicts=conflicts
    def capture(self,codes,*,stage,now):
        rows=[]
        for index,code in enumerate(codes):
            price=10+index/100;bid=price*(.98 if index<self.conflicts else 1)
            rows.append(QuoteV1.from_mapping({"code":code,"name":"测试","trade_date":now.date().isoformat(),"exchange_time":now-timedelta(seconds=1),"provider_time":now,"received_at":now,"last_price":price,"previous_close":price,"open_price":price,"high_price":price,"low_price":price,"bid1":bid,"bid1_volume":10000,"ask1":price+.01,"ask1_volume":10000,"volume":100000,"amount":10_000_000,"halted":False,"limit_up":False,"limit_down":False,"provider":self.name}))
        return MarketSnapshotV1.build(trade_date=now.date().isoformat(),session="sell",batch_started_at=now-timedelta(seconds=2),batch_completed_at=now,quotes=rows,expected_codes=len(codes))
class IndexSource:
    def __init__(self,name,price=3980):self.name=name;self.price=price
    def capture(self,now):return source_observation(observed_at=now.isoformat(),previous_close=4000,last_price=self.price,provider=self.name,source_snapshot_id=f"response-{self.name}")

def test_cross_section_labels_all_100_observations_not_only_strategy_trades(tmp_path):
    diagnostic(tmp_path);result=capture_exit(tmp_path,sell_date="2026-08-26",now=SELL,sources=(ExitSource("source_a"),ExitSource("source_b")))
    assert result["eligible_observation_count"]==100 and result["label_count"]==100 and result["usable_for_ic"] is True
    assert len(list((tmp_path/"factor_cross_section_labels/2026-08-25").glob("*.json")))==100
    assert "strategy" not in json.dumps(result).lower()

def test_cross_section_conflicts_are_excluded_and_low_coverage_has_no_usable_ic(tmp_path):
    diagnostic(tmp_path);result=capture_exit(tmp_path,sell_date="2026-08-26",now=SELL,sources=(ExitSource("source_a"),ExitSource("source_b",conflicts=10)))
    assert result["usable_for_ic"] is False and result["label_status"]=="INSUFFICIENT_CROSS_SECTION_COVERAGE" and result["coverage"]<.95
    assert result["diagnostics"]["label_status"]=="INSUFFICIENT_CROSS_SECTION_COVERAGE"

def test_index_capture_production_path_creates_fact_or_observable_unknown(tmp_path):
    ok=capture_index(tmp_path,now=SELL.replace(hour=14,minute=49),sources=(IndexSource("index_a"),IndexSource("index_b",3979)));assert ok["status"]=="VERIFIED_NOT_DECLINE" and ok["index_benchmark_id"]
    other=tmp_path/"single";unknown=capture_index(other,now=SELL.replace(hour=14,minute=49),sources=(IndexSource("only_one"),));assert unknown["status"]=="UNKNOWN" and not list((other/"index_benchmarks").glob("*/*.json")) and unknown["errors"]
    conflict=tmp_path/"conflict";bad=capture_index(conflict,now=SELL.replace(hour=14,minute=49),sources=(IndexSource("a",3900),IndexSource("b",4050)));assert bad["status"]=="UNKNOWN" and bad["errors"]
