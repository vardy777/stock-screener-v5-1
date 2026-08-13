from pathlib import Path
import argparse,json,sys
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from v5.live_acceptance import build
if __name__=="__main__":
    parser=argparse.ArgumentParser();parser.add_argument("--trade-date",required=True);args=parser.parse_args();report=build(ROOT/"v5/data",args.trade_date);print(json.dumps(report,ensure_ascii=False,indent=2));raise SystemExit(0 if report["complete"] else 3)
