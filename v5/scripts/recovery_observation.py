from pathlib import Path
from datetime import datetime
import json,sys
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from v5.recovery_observation import run
from v5.alerts import send_failure
from v5.core import CHINA_TZ
if __name__=="__main__":
 try:
  result=run(ROOT/"v5/data");print(json.dumps(result,ensure_ascii=False));raise SystemExit(0)
 except Exception as exc:
  try:print(json.dumps({"error":f"{type(exc).__name__}: {exc}","alert":send_failure(ROOT/"v5/data",datetime.now(CHINA_TZ).date().isoformat(),"recovery_observation",str(exc),ROOT/"v5/.env")},ensure_ascii=False))
  except Exception as alert_exc:print(json.dumps({"error":f"{type(exc).__name__}: {exc}","alert_error":f"{type(alert_exc).__name__}: {alert_exc}"},ensure_ascii=False))
  raise SystemExit(3)
