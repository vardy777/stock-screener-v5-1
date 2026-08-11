#!/usr/bin/env python3
"""Build the next strict context without the rate-limited Sina archive loop."""
from __future__ import annotations
import argparse,json,sys
from datetime import datetime
from datetime import date
from pathlib import Path

BASE=Path(__file__).resolve().parent.parent; ROOT=BASE.parent
sys.path.insert(0,str(ROOT)); sys.path.insert(0,str(BASE))
from overnight.context_gateway import build_context,fetch_sina_reference_prices
from overnight.dataset import is_eligible_code
from overnight.live_features import save_live_feature_context
from v4.calendar import TradingCalendar
from v4.market_gateway import SnapshotRepository
from v4.execution import CHINA_TZ

def _reference(trade_date: str, expected_previous: str):
    root=ROOT/"v4/data/market_snapshots_v1/strict"
    morning=sorted((root/trade_date/"morning").glob("*.json"))
    if morning:
        snapshot=SnapshotRepository().load(morning[-1])
        return {q.code:q.previous_close for q in snapshot.quotes},snapshot.snapshot_id+":previous_close"
    signal=sorted((root/expected_previous/"signal").glob("*.json"))
    if signal:
        snapshot=SnapshotRepository().load(signal[-1])
        return {q.code:q.last_price for q in snapshot.quotes},snapshot.snapshot_id+":signal_last_price"
    return {},"missing"

def main(argv=None):
    parser=argparse.ArgumentParser(); parser.add_argument("--trade-date",default=date.today().isoformat())
    parser.add_argument("--workers",type=int,default=24); parser.add_argument("--max-stocks",type=int)
    parser.add_argument("--output",type=Path,default=BASE/"data/overnight/live_feature_context.csv.gz")
    args=parser.parse_args(argv); calendar=TradingCalendar(); trade=date.fromisoformat(args.trade_date)
    previous=calendar.previous_open(trade)
    if previous is None: print("拒绝构建: 交易日历未核验"); return 2
    codes=[p.stem for p in sorted((BASE/"data/daily").glob("*.csv")) if is_eligible_code(p.stem)]
    if args.max_stocks is not None: codes=codes[:max(0,args.max_stocks)]
    references,source=_reference(trade.isoformat(),previous.isoformat())
    if len(references)/len(codes) < 0.95:
        references,source=fetch_sina_reference_prices(codes)
    context,metadata=build_context(codes,previous.isoformat(),reference_prices=references,
                                   reference_source=source,workers=args.workers)
    if metadata["strict_context_ready"]:
        save_live_feature_context(context,metadata,args.output)
    else:
        failure=args.output.parent/"live_feature_context_gateway_failure.json"
        report={**metadata,"failed_at":datetime.now(CHINA_TZ).isoformat(timespec="seconds"),
                "published":False,"preserved_previous_context":args.output.exists()}
        temporary=failure.with_suffix(failure.suffix+".tmp")
        temporary.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
        temporary.replace(failure)
    print(json.dumps(metadata,ensure_ascii=False,indent=2)); print(f"已保存: {args.output}")
    return 0 if metadata["strict_context_ready"] else 1

if __name__=="__main__": raise SystemExit(main())
