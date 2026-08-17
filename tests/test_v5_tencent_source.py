from datetime import datetime

from v5.core import CHINA_TZ
from v5.tencent_source import TencentRealtimeSource, active_codes


NOW = datetime(2026, 8, 17, 14, 49, 5, tzinfo=CHINA_TZ)


def row(code="000001", name="平安银行", status="", timestamp="20260817144904"):
    fields = [""] * 88
    fields[0]="51";fields[1]=name;fields[2]=code;fields[3]="11.10";fields[4]="11.00";fields[5]="11.05"
    fields[6]="1000";fields[9]="11.09";fields[10]="20";fields[19]="11.10";fields[20]="30"
    fields[30]=timestamp;fields[33]="11.20";fields[34]="10.90";fields[36]="1000";fields[37]="111";fields[40]=status
    market="sh" if code.startswith("6") else "sz"
    return f'v_{market}{code}="{"~".join(fields)}";'


def test_tencent_snapshot_has_independent_lineage_and_units():
    source=TencentRealtimeSource(fetch_text=lambda *_:row(),clock=lambda:NOW,batch_size=300)
    snapshot=source.capture(["000001"],stage="signal",now=NOW)
    assert snapshot.quality.accepted and snapshot.quotes[0].provider==source.name
    assert snapshot.quotes[0].volume==100000 and snapshot.quotes[0].amount==1110000


def test_active_listing_filter_excludes_explicit_delisted_rows():
    text=row("000001")+"\n"+row("000003","PT金田A","D")
    assert active_codes(["000001","000003"],fetch_text=lambda *_:text)==["000001"]
