"""Non-trading V5 readiness probe; diagnostic only."""
from __future__ import annotations
from datetime import datetime
import json
from pathlib import Path
import time
from .core import CHINA_TZ
from .eastmoney_source import EastmoneyRealtimeSource
from .sina_source import SinaRealtimeSource
from .jobs import load_universe
from .shadow_schedule import ShadowScheduler
from .universe_refresh import refresh as refresh_universe
from .clock_gate import check as check_clock
def run(root,day=None,*,refresh_attempts=3,sleeper=None,clock_checker=None):
 root=Path(root);now=datetime.now(CHINA_TZ);day=day or now.date().isoformat();checks={};details={};trading_day=now.weekday()<5 and day==now.date().isoformat();details["trading_day"]=trading_day
 clock=(clock_checker or check_clock)();checks["causal_clock"]=clock["passed"];details["clock_gate"]=clock
 if not trading_day:
  checks["universe_refresh"]=True;checks["universe"]=True;checks["sina_transport"]=True;checks["eastmoney_transport"]=True;details["market_checks_skipped"]="market_closed_diagnostic"
 elif not clock["passed"]:
  checks["universe_refresh"]=False;checks["universe"]=False;checks["sina_transport"]=False;checks["eastmoney_transport"]=False;details["market_checks_skipped"]="causal_clock_rejected"
 else:
  sleeper=sleeper or time.sleep;errors=[]
  for attempt in range(1,max(1,int(refresh_attempts))+1):
   try:r=refresh_universe(root,now=now);checks["universe_refresh"]=True;details["universe_refresh_id"]=r["universe_id"];details["universe_refresh_count"]=r["count"];details["universe_refresh_attempts"]=attempt;break
   except Exception as exc:
    errors.append(f"{type(exc).__name__}: {exc}")
    if attempt<max(1,int(refresh_attempts)):sleeper(2)
  if not checks.get("universe_refresh"):
   checks["universe_refresh"]=False;details["universe_refresh_error"]=errors[-1];details["universe_refresh_errors"]=errors;details["universe_refresh_attempts"]=len(errors)
 if clock["passed"] and trading_day:
  try:u=load_universe(root,day,as_of=now,require_native=(day==now.date().isoformat() and now.weekday()<5));checks["universe"]=len(u.codes)>=4000;details["universe_count"]=len(u.codes);details["universe_sources"]=list(u.sources)
  except Exception as exc:checks["universe"]=False;details["universe_error"]=type(exc).__name__;u=None
 checks["schedule_contract"]=ShadowScheduler(root).validate()["passed"]
 # One known liquid symbol proves transport/parser availability only; it is
 # never accepted as full-market or strict-window evidence.
 if clock["passed"] and trading_day:
  for name,source in (("sina",SinaRealtimeSource()),("eastmoney",EastmoneyRealtimeSource(page_size=500,retries=0))):
   try:s=source.capture(["600000"],stage="signal",now=now);checks[name+"_transport"]=len(s.quotes)==1;details[name+"_quote_time"]=s.quotes[0].exchange_time if s.quotes else None
   except Exception as exc:checks[name+"_transport"]=False;details[name+"_error"]=type(exc).__name__
 report={"schema_version":"v5-readiness-preflight-v2","recorded_at":now.isoformat(),"trade_date":day,"mode":"TRADING_DAY_PREPARATION" if trading_day else "MARKET_CLOSED_DIAGNOSTIC","diagnostic_only":True,"strict_evidence":False,"universe_preparation":trading_day,"checks":checks,"details":details,"passed":all(checks.values())};path=root/"preflight"/now.date().isoformat()/f"{now.strftime('%H%M%S')}.json";path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(report,ensure_ascii=False,sort_keys=True,separators=(",",":")),encoding="utf-8");return report
if __name__=="__main__":
 data=Path(__file__).resolve().parent/"data";report=run(data);print(json.dumps(report,ensure_ascii=False,indent=2))
 if not report["passed"] and report["mode"]=="TRADING_DAY_PREPARATION":
  try:
   from .alerts import send_failure
   failed=", ".join(name for name,ok in report["checks"].items() if not ok);send_failure(data,report["trade_date"],"preflight",failed,Path(__file__).resolve().parent/".env")
  except Exception as exc:print(json.dumps({"alert_error":f"{type(exc).__name__}: {exc}"},ensure_ascii=False))
 raise SystemExit(0 if report["passed"] else 3)
