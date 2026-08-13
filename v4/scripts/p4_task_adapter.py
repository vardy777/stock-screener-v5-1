#!/usr/bin/env python
"""Future production entrypoint. It is intentionally disabled by default."""
import argparse,json,sys
from datetime import datetime
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from v4.execution import CHINA_TZ
from v4.production_task_runner import run

def main(argv=None):
    p=argparse.ArgumentParser(); p.add_argument("task_name"); p.add_argument("--trade-date")
    p.add_argument("--authorization-file",type=Path,required=True); p.add_argument("--preflight",action="store_true"); args=p.parse_args(argv)
    day=args.trade_date or datetime.now(CHINA_TZ).date().isoformat()
    # V4 notification ownership was permanently retired in favour of V5.
    # Keep this guard in the scheduled entrypoint so an elevated legacy task
    # cannot transmit V4 content even when Task Scheduler permissions prevent
    # a lower-privilege maintenance session from disabling the task itself.
    if args.task_name in {"morning_push","confirmation_push"}:
        print(json.dumps({"passed":False,"status":"DISABLED","reason_code":"V4_NOTIFICATION_RETIRED_V5_ONLY","task_name":args.task_name,"trade_date":day},ensure_ascii=False,sort_keys=True))
        return 3
    result=run(args.task_name,authorization_file=args.authorization_file,preflight=args.preflight)
    print(json.dumps(result,ensure_ascii=False,sort_keys=True))
    return 0 if result.get("passed") is True or result.get("status")=="SUCCEEDED" else 3
if __name__=="__main__": raise SystemExit(main())
