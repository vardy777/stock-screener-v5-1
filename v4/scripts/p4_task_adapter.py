#!/usr/bin/env python
"""Future production entrypoint. It is intentionally disabled by default."""
import argparse,json,sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
CHINA_TZ=ZoneInfo("Asia/Shanghai")

def main(argv=None):
    p=argparse.ArgumentParser(); p.add_argument("task_name"); p.add_argument("--trade-date")
    p.add_argument("--authorization-file",type=Path,required=True); p.add_argument("--preflight",action="store_true"); args=p.parse_args(argv)
    day=args.trade_date or datetime.now(CHINA_TZ).date().isoformat()
    # V4 production ownership is permanently retired in favour of V5.  The
    # OS tasks are ACL-protected on some installations, so every legacy task
    # must stop here before importing or invoking any market-data, decision,
    # paper or notification implementation.
    print(json.dumps({"passed":False,"status":"DISABLED","reason_code":"V4_PRODUCTION_RETIRED_V5_ONLY","task_name":args.task_name,"trade_date":day},ensure_ascii=False,sort_keys=True))
    return 3
if __name__=="__main__": raise SystemExit(main())
