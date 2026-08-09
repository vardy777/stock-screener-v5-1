#!/usr/bin/env python
"""Future production entrypoint. It is intentionally disabled by default."""
import argparse,json,sys
from datetime import datetime
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from v4.execution import CHINA_TZ
from v4.production_adapter import run_disabled

def main(argv=None):
    p=argparse.ArgumentParser(); p.add_argument("task_name"); p.add_argument("--trade-date")
    p.add_argument("--authorization-file",type=Path); args=p.parse_args(argv)
    day=args.trade_date or datetime.now(CHINA_TZ).date().isoformat()
    result=run_disabled(args.task_name,trade_date=day,authorization_file=args.authorization_file)
    print(json.dumps(result.to_dict(),ensure_ascii=False,sort_keys=True))
    return 0 if result.status=="SUCCEEDED" else 3
if __name__=="__main__": raise SystemExit(main())
