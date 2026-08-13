from datetime import datetime,timedelta
from v5.core import CHINA_TZ
from v5.sina_source import SinaRealtimeSource
NOW=datetime(2026,8,14,9,25,tzinfo=CHINA_TZ)
def test_sina_source_builds_native_snapshot_without_legacy_imports():
    fields=["测试","10.00","10.00","10.20","10.30","9.90","0","0","100000","8000000","10000","10.19"]+["0","0"]*4+["12000","10.21"]+["0","0"]*4+["2026-08-14","09:24:59"]
    text='var hq_str_sz000001="'+','.join(fields)+'";'
    source=SinaRealtimeSource(fetch_text=lambda *_:text,clock=lambda:NOW);snapshot=source.capture(["000001"],stage="morning",now=NOW)
    assert snapshot.quality.accepted and snapshot.quotes[0].provider==source.name and snapshot.quotes[0].exchange_time.startswith("2026-08-14T09:24:59")
