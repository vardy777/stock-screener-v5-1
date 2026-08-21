from pathlib import Path
import argparse,json,sys
from datetime import datetime
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from v5.live_acceptance import build,save
from v5.contracts import CHINA_TZ
if __name__=="__main__":
    parser=argparse.ArgumentParser();parser.add_argument("--trade-date",default=None);parser.add_argument("--save",action="store_true");args=parser.parse_args();trade_date=args.trade_date or datetime.now(CHINA_TZ).date().isoformat();report=build(ROOT/"v5/data",trade_date);report=save(ROOT/"v5/data",report) if args.save else report;print(json.dumps(report,ensure_ascii=False,indent=2));raise SystemExit(0 if report["complete"] else 3)
