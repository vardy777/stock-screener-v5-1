"""Independent Eastmoney full-market Level-1 source for V5."""
from __future__ import annotations
from datetime import datetime
import json
from urllib.parse import urlencode
from urllib.request import Request,urlopen
from urllib.error import HTTPError,URLError
import time
from math import ceil
from .core import CHINA_TZ
from .market_snapshot import MarketSnapshotV1,QuoteV1

FIELDS="f12,f14,f2,f5,f6,f15,f16,f17,f18,f31,f32,f33,f34,f124"
UNIVERSE_FILTER="m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23"
ENDPOINTS=("https://push2delay.eastmoney.com","https://push2.eastmoney.com","https://82.push2.eastmoney.com","https://72.push2.eastmoney.com")
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
    def __init__(self,fetch_json=None,timeout=15,clock=None,page_size=500,retries=2,overall_budget_seconds=25,monotonic=None,sleeper=None,endpoints=ENDPOINTS):self.fetch_json=fetch_json or _default_fetch;self.timeout=timeout;self.clock=clock or (lambda:datetime.now(CHINA_TZ));self.page_size=int(page_size);self.retries=int(retries);self.overall_budget_seconds=float(overall_budget_seconds);self.monotonic=monotonic or time.monotonic;self.sleeper=sleeper or time.sleep;self.endpoints=tuple(endpoints)
    def _page(self,page,deadline):
        query=urlencode({"pn":page,"pz":self.page_size,"po":1,"np":1,"fltt":2,"invt":2,"fid":"f3","fs":UNIVERSE_FILTER,"fields":FIELDS})
        last=None
        attempts=max(self.retries+1,len(self.endpoints))
        for attempt in range(attempts):
            remaining=deadline-self.monotonic()
            if remaining<=0:raise TimeoutError("eastmoney capture exceeded overall budget")
            endpoint=self.endpoints[attempt%len(self.endpoints)]
            try:return self.fetch_json(endpoint+"/api/qt/clist/get?"+query,min(self.timeout,max(.1,remaining)))
            except (HTTPError,URLError,TimeoutError,ConnectionError,OSError,RuntimeError) as exc:
                last=exc
                if attempt<attempts-1:
                    remaining=deadline-self.monotonic()
                    if remaining<=0:raise TimeoutError("eastmoney capture exceeded overall budget") from exc
                    self.sleeper(min(.25*(attempt+1),remaining))
        raise RuntimeError(f"eastmoney page {page} unavailable: {type(last).__name__}") from last
    def capture(self,codes:list[str],*,stage:str,now:datetime):
        started=self.clock();deadline=self.monotonic()+self.overall_budget_seconds;wanted=set(codes)
        rows=[];page=1;maximum_pages=None
        while maximum_pages is None or page<=maximum_pages:
            if self.monotonic()>=deadline:raise TimeoutError("eastmoney capture exceeded overall budget")
            payload=self._page(page,deadline);data=payload.get("data",{})
            if payload.get("rc")!=0 or not isinstance(data.get("diff"),list):raise RuntimeError("provider payload invalid")
            page_rows=data["diff"]
            page_codes={str(row.get("f12","")).zfill(6) for row in page_rows}
            prior_codes={str(row.get("f12","")).zfill(6) for row in rows}
            if page>1 and page_rows and page_codes<=prior_codes:raise RuntimeError("provider pagination repeated page")
            rows.extend(page_rows);total=int(data.get("total",len(rows)) or len(rows))
            if maximum_pages is None:
                actual_page_size=len(page_rows)
                if actual_page_size<1:break
                maximum_pages=ceil(total/actual_page_size)+1
                if maximum_pages>100:raise RuntimeError("provider pagination unreasonable")
            if len(rows)>=total or not data["diff"]:break
            page+=1
        if len(rows)<total:raise RuntimeError(f"provider pagination incomplete: {len(rows)}/{total}")
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
