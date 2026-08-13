"""Non-trading V5 readiness probe; diagnostic only."""
from __future__ import annotations
from datetime import datetime
import json
from pathlib import Path
from .core import CHINA_TZ
from .eastmoney_source import EastmoneyRealtimeSource
from .sina_source import SinaRealtimeSource
from .jobs import load_universe
from .shadow_schedule import ShadowScheduler
def run(root,day=None):
 root=Path(root);now=datetime.now(CHINA_TZ);day=day or now.date().isoformat();checks={};details={}
 try:u=load_universe(root,day);checks["universe"]=len(u.codes)>=4000;details["universe_count"]=len(u.codes)
 except Exception as exc:checks["universe"]=False;details["universe_error"]=type(exc).__name__;u=None
 checks["schedule_contract"]=ShadowScheduler(root).validate()["passed"]
 # One known liquid symbol proves transport/parser availability only; it is
 # never accepted as full-market or strict-window evidence.
 for name,source in (("sina",SinaRealtimeSource()),("eastmoney",EastmoneyRealtimeSource(page_size=500,retries=0))):
  try:s=source.capture(["600000"],stage="signal",now=now);checks[name+"_transport"]=len(s.quotes)==1;details[name+"_quote_time"]=s.quotes[0].exchange_time if s.quotes else None
  except Exception as exc:checks[name+"_transport"]=False;details[name+"_error"]=type(exc).__name__
 report={"schema_version":"v5-weekend-preflight-v1","recorded_at":now.isoformat(),"trade_date":day,"diagnostic_only":True,"strict_evidence":False,"checks":checks,"details":details,"passed":all(checks.values())};path=root/"preflight"/now.date().isoformat()/f"{now.strftime('%H%M%S')}.json";path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(report,ensure_ascii=False,sort_keys=True,separators=(",",":")),encoding="utf-8");return report
if __name__=="__main__":print(json.dumps(run(Path(__file__).resolve().parent/"data"),ensure_ascii=False,indent=2))
