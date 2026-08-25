#!/usr/bin/env python
"""Build immutable strict factor labels from verified V5 paper evidence."""
from __future__ import annotations
import argparse,json,sys
from datetime import datetime
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from v5.core import CHINA_TZ
from v5.factor_label_production import produce
def main():
    parser=argparse.ArgumentParser();parser.add_argument("--trade-date",required=True);parser.add_argument("--as-of");parser.add_argument("--root",type=Path,default=ROOT/"v5"/"data");args=parser.parse_args();as_of=datetime.fromisoformat(args.as_of) if args.as_of else datetime.now(CHINA_TZ);print(json.dumps(produce(args.root,args.trade_date,as_of=as_of),ensure_ascii=False,indent=2));return 0
if __name__=="__main__":raise SystemExit(main())
