"""V5-native Sina Level-1 source; no legacy DataFetcher dependency."""
from __future__ import annotations
from datetime import datetime
import re,time
from urllib.request import Request,urlopen
from .core import CHINA_TZ
from .market_snapshot import MarketSnapshotV1,QuoteV1

def _fetch(url,timeout):
    request=Request(url,headers={"Referer":"https://finance.sina.com.cn","User-Agent":"Mozilla/5.0"})
    with urlopen(request,timeout=timeout) as response:return response.read().decode("gbk",errors="replace")
class SinaRealtimeSource:
    name="sina_realtime_level1"
    def __init__(self,fetch_text=None,timeout=15,batch_size=700,clock=None,overall_budget_seconds=25,monotonic=None,sleeper=None,retries=1):self.fetch_text=fetch_text or _fetch;self.timeout=timeout;self.batch_size=batch_size;self.clock=clock or (lambda:datetime.now(CHINA_TZ));self.overall_budget_seconds=float(overall_budget_seconds);self.monotonic=monotonic or time.monotonic;self.sleeper=sleeper or time.sleep;self.retries=int(retries)
    def capture(self,codes,*,stage,now):
        started=self.clock();deadline=self.monotonic()+self.overall_budget_seconds;quotes=[]
        for offset in range(0,len(codes),self.batch_size):
            remaining=deadline-self.monotonic()
            if remaining<=0:raise TimeoutError("sina capture exceeded overall budget")
            batch=codes[offset:offset+self.batch_size];symbols=[("sh" if x.startswith("6") else "sz")+x for x in batch]
            for attempt in range(self.retries+1):
                remaining=deadline-self.monotonic()
                if remaining<=0:raise TimeoutError("sina capture exceeded overall budget")
                try:text=self.fetch_text("https://hq.sinajs.cn/list="+",".join(symbols),min(self.timeout,max(.1,remaining)));break
                except (TimeoutError,ConnectionError,OSError,RuntimeError) as exc:
                    if attempt>=self.retries:raise RuntimeError(f"sina batch unavailable: {type(exc).__name__}") from exc
                    self.sleeper(min(.2*(attempt+1),max(0,deadline-self.monotonic())))
            received=self.clock()
            for line in text.splitlines():
                match=re.match(r'var hq_str_(?:sh|sz)(\d{6})="(.*)";',line.strip())
                if not match:continue
                code=match.group(1);f=match.group(2).split(",")
                try:
                    if len(f)<32 or not f[0] or not f[30] or not f[31]:continue
                    previous,price,opened,high,low=map(float,(f[2],f[3],f[1],f[4],f[5]));exchange=datetime.fromisoformat(f"{f[30]}T{f[31]}+08:00");bid,ask=float(f[11] or 0),float(f[21] or 0);volume=int(float(f[8] or 0));halted=price<=0 or volume<=0;ratio=.2 if code.startswith(("30","688","689")) else .1
                    quotes.append(QuoteV1.from_mapping({"code":code,"name":f[0],"trade_date":f[30],"exchange_time":exchange,"provider_time":received,"received_at":received,"last_price":price,"previous_close":previous,"open_price":opened,"high_price":high,"low_price":low,"bid1":bid,"bid1_volume":int(float(f[10] or 0)),"ask1":ask,"ask1_volume":int(float(f[20] or 0)),"volume":volume,"amount":float(f[9] or 0),"halted":halted,"limit_up":price>=round(previous*(1+ratio),2) and ask<=0,"limit_down":price<=round(previous*(1-ratio),2) and bid<=0,"provider":self.name}))
                except Exception:continue
            if offset+self.batch_size<len(codes):
                remaining=deadline-self.monotonic()
                if remaining<=0:raise TimeoutError("sina capture exceeded overall budget")
                self.sleeper(min(.15,remaining))
        completed=self.clock();session={"morning":"morning","signal":"signal","confirmation":"buy","sell":"sell"}[stage]
        return MarketSnapshotV1.build(trade_date=now.astimezone(CHINA_TZ).date().isoformat(),session=session,batch_started_at=started,batch_completed_at=completed,quotes=quotes,expected_codes=len(codes))
