from pathlib import Path
from datetime import datetime
from unittest.mock import patch
from v5.core import CHINA_TZ
from v5.preflight import run
import v5.preflight
def test_preflight_is_explicitly_diagnostic_prepares_universe_and_never_strict_evidence():
 text=(Path(__file__).resolve().parents[1]/"v5/preflight.py").read_text(encoding="utf-8");assert '"diagnostic_only":True' in text and '"strict_evidence":False' in text and 'refresh_universe(root,now=now)' in text and "PaperLedger" not in text and 'SystemExit(0 if report["passed"] else 3)' in text and 'send_failure' in text

def test_preflight_retries_native_universe_refresh_before_failing(tmp_path):
 calls=[];now=datetime(2026,8,14,8,30,tzinfo=CHINA_TZ)
 def refresh(*args,**kwargs):
  calls.append(1)
  if len(calls)<3:raise TimeoutError("transient")
  return {"universe_id":"univ1-ok","count":4930}
 with patch("v5.preflight.datetime") as clock,patch("v5.preflight.refresh_universe",side_effect=refresh),patch("v5.preflight.load_universe") as load,patch("v5.preflight.ShadowScheduler") as scheduler,patch("v5.preflight.SinaRealtimeSource"),patch("v5.preflight.EastmoneyRealtimeSource"):
  clock.now.return_value=now;load.return_value.codes=tuple(str(x).zfill(6) for x in range(4000));load.return_value.sources=("eastmoney_realtime_market_directory",);scheduler.return_value.validate.return_value={"passed":True}
  for source in (v5.preflight.SinaRealtimeSource.return_value,v5.preflight.EastmoneyRealtimeSource.return_value):source.capture.return_value.quotes=[]
  report=run(tmp_path,refresh_attempts=3,sleeper=lambda _:None,clock_checker=lambda:{"passed":True,"reason":"OK"})
 assert report["details"]["universe_refresh_attempts"]==3 and len(calls)==3
