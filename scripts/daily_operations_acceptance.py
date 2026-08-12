#!/usr/bin/env python
from __future__ import annotations
import argparse,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]; sys.path.insert(0,str(ROOT))
from v4.daily_operations_acceptance import build

def main():
    parser=argparse.ArgumentParser(); parser.add_argument("--trade-date",required=True); parser.add_argument("--output",type=Path)
    args=parser.parse_args(); report=build(ROOT,args.trade_date)
    if args.output:
        args.output.parent.mkdir(parents=True,exist_ok=True)
        args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(report,ensure_ascii=False,indent=2)); return 0 if report["passed"] else 1
if __name__=="__main__": raise SystemExit(main())
