from datetime import datetime,timedelta
from v5.core import CHINA_TZ
from v5.sina_source import SinaRealtimeSource
NOW=datetime(2026,8,14,9,25,tzinfo=CHINA_TZ)
def test_sina_source_builds_native_snapshot_without_legacy_imports():
    fields=["测试","10.00","10.00","10.20","10.30","9.90","0","0","100000","8000000","10000","10.19"]+["0","0"]*4+["12000","10.21"]+["0","0"]*4+["2026-08-14","09:24:59"]
    text='var hq_str_sz000001="'+','.join(fields)+'";'
    source=SinaRealtimeSource(fetch_text=lambda *_:text,clock=lambda:NOW);snapshot=source.capture(["000001"],stage="morning",now=NOW)
    assert snapshot.quality.accepted and snapshot.quotes[0].provider==source.name and snapshot.quotes[0].exchange_time.startswith("2026-08-14T09:24:59")
def test_sina_source_fails_closed_when_overall_budget_is_exhausted():
    ticks=iter((0,0,2));source=SinaRealtimeSource(fetch_text=lambda *_:"",batch_size=1,overall_budget_seconds=1,monotonic=lambda:next(ticks),sleeper=lambda *_:None,clock=lambda:NOW)
    import pytest
    with pytest.raises(TimeoutError,match="overall budget"):source.capture(["000001","000002"],stage="morning",now=NOW)
def test_sina_source_retries_complete_batch_without_lowering_coverage():
    fields=["测试","10.00","10.00","10.20","10.30","9.90","0","0","100000","8000000","10000","10.19"]+["0","0"]*4+["12000","10.21"]+["0","0"]*4+["2026-08-14","09:24:59"]
    text='var hq_str_sz000001="'+','.join(fields)+'";';calls=[]
    def fetch(*_):
        calls.append(1)
        if len(calls)==1:raise ConnectionError("transient")
        return text
    source=SinaRealtimeSource(fetch_text=fetch,clock=lambda:NOW,sleeper=lambda _:None,retries=1)
    snapshot=source.capture(["000001"],stage="morning",now=NOW)
    assert calls==[1,1] and snapshot.quality.accepted and snapshot.quality.coverage==1
