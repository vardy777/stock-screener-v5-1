"""Independent Eastmoney full-market Level-1 source for V5."""
from __future__ import annotations
from datetime import datetime
import json
from urllib.parse import urlencode
from urllib.request import Request,urlopen
from urllib.error import HTTPError,URLError
import time
from .core import CHINA_TZ
from .market_snapshot import MarketSnapshotV1,QuoteV1

FIELDS="f12,f14,f2,f5,f6,f15,f16,f17,f18,f31,f32,f33,f34,f124"
UNIVERSE_FILTER="m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23"
def _real(value):
    if value in (None,"","-"):return None
    try:return float(value)
    except (TypeError,ValueError):return None
def _default_fetch(url,timeout):
    request=Request(url,headers={"Referer":"https://quote.eastmoney.com/","User-Agent":"Mozilla/5.0"})
    with urlopen(request,timeout=timeout) as response:
        if response.status!=200:raise RuntimeError(f"HTTP {response.status}")
        return json.loads(response.read().decode("utf-8"))

class EastmoneyRealtimeSource:
    name="eastmoney_realtime_full_market"
    def __init__(self,fetch_json=None,timeout=15,clock=None,page_size=500,retries=2):self.fetch_json=fetch_json or _default_fetch;self.timeout=timeout;self.clock=clock or (lambda:datetime.now(CHINA_TZ));self.page_size=int(page_size);self.retries=int(retries)
    def _page(self,page):
        query=urlencode({"pn":page,"pz":self.page_size,"po":1,"np":1,"fltt":2,"invt":2,"fid":"f3","fs":UNIVERSE_FILTER,"fields":FIELDS})
        last=None
        for attempt in range(self.retries+1):
            try:return self.fetch_json("https://push2.eastmoney.com/api/qt/clist/get?"+query,self.timeout)
            except (HTTPError,URLError,TimeoutError,ConnectionError,OSError,RuntimeError) as exc:
                last=exc
                if attempt<self.retries:time.sleep(.25*(attempt+1))
        raise RuntimeError(f"eastmoney page {page} unavailable: {type(last).__name__}") from last
    def capture(self,codes:list[str],*,stage:str,now:datetime):
        started=self.clock();wanted=set(codes)
        rows=[];page=1
        while page<=20:
            payload=self._page(page);data=payload.get("data",{})
            if payload.get("rc")!=0 or not isinstance(data.get("diff"),list):raise RuntimeError("provider payload invalid")
            rows.extend(data["diff"]);total=int(data.get("total",len(rows)) or len(rows))
            if len(rows)>=total or not data["diff"]:break
            page+=1
        received=self.clock();quotes=[]
        for row in rows:
            code=str(row.get("f12","")).zfill(6)
            if code not in wanted:continue
            price,previous,opened,high,low=map(_real,(row.get("f2"),row.get("f18"),row.get("f17"),row.get("f15"),row.get("f16")))
            timestamp=_real(row.get("f124"));bid,ask,bid_volume,ask_volume=map(_real,(row.get("f31"),row.get("f32"),row.get("f33"),row.get("f34")))
            if None in (price,previous,opened,high,low,timestamp):continue
            exchange=datetime.fromtimestamp(timestamp,tz=CHINA_TZ)
            halted=price<=0 or _real(row.get("f5")) in (None,0)
            bid=bid or 0.;ask=ask or 0.;bid_volume=int((bid_volume or 0)*100);ask_volume=int((ask_volume or 0)*100)
            limit_up=ask<=0 and bid>0 and not halted;limit_down=bid<=0 and ask>0 and not halted
            try:quotes.append(QuoteV1.from_mapping({"code":code,"name":row.get("f14"),"trade_date":exchange.date().isoformat(),"exchange_time":exchange,"provider_time":exchange,"received_at":received,"last_price":price,"previous_close":previous,"open_price":opened,"high_price":high,"low_price":low,"bid1":bid,"bid1_volume":bid_volume,"ask1":ask,"ask1_volume":ask_volume,"volume":int(float(row.get("f5") or 0)*100),"amount":float(row.get("f6") or 0),"halted":halted,"limit_up":limit_up,"limit_down":limit_down,"provider":self.name}))
            except Exception:continue
        session={"morning":"morning","signal":"signal","confirmation":"buy","sell":"sell"}[stage]
        return MarketSnapshotV1.build(trade_date=now.astimezone(CHINA_TZ).date().isoformat(),session=session,batch_started_at=started,batch_completed_at=received,quotes=quotes,expected_codes=len(wanted))
