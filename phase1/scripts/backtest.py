#!/usr/bin/env python3
"""Transparent point-in-time baseline for the overnight strategy."""

import argparse
import json
import sys
from dataclasses import replace
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
ROOT = BASE.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(BASE))

from overnight import load_or_build_dataset, run_rule_backtest
from strategy_spec import DEFAULT_SPEC


def _pct(value):
    return f"{float(value) * 100:+.2f}%"


def _save_csv_atomic(frame, path: Path) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    frame.to_csv(temporary, index=False)
    temporary.replace(path)


def _save_json_atomic(value, path: Path) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2)
    temporary.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rebuild", action="store_true")
    parser.add_argument("--max-stocks", type=int, default=None)
    parser.add_argument("--minimum-score", type=float, default=0.55)
    parser.add_argument("--no-market-filter", action="store_true")
    parser.add_argument("--cache", type=Path, default=None)
    parser.add_argument("--report-dir", type=Path, default=None)
    parser.add_argument(
        "--stress",
        action="store_true",
        help="use 0.10 percent slippage on both buy and sell",
    )
    args = parser.parse_args()

    cache = args.cache or (BASE / "data" / "overnight" / "dataset.csv.gz")
    dataset, metadata = load_or_build_dataset(
        BASE / "data" / "daily",
        cache,
        DEFAULT_SPEC,
        rebuild=args.rebuild,
        max_stocks=args.max_stocks,
    )
    if dataset.empty:
        print("没有可用样本")
        return 1

    print("=== 无AI时点基线回测 ===")
    print(
        f"样本 {len(dataset):,} 条 | {str(dataset['date'].min())[:10]} → "
        f"{str(dataset['date'].max())[:10]}"
    )
    if metadata.get("strict_1450_rows", 0) == 0:
        print("[警告] 数据精度: 15:00收盘价代理14:50买入，不具备实盘验收资格")

    run_spec = (
        replace(
            DEFAULT_SPEC,
            buy_slippage_rate=DEFAULT_SPEC.stress_slippage_rate,
            sell_slippage_rate=DEFAULT_SPEC.stress_slippage_rate,
        )
        if args.stress
        else DEFAULT_SPEC
    )
    trades, daily, summary = run_rule_backtest(
        dataset,
        run_spec,
        minimum_score=args.minimum_score,
        market_filter=not args.no_market_filter,
    )

    default_cache = BASE / "data" / "overnight" / "dataset.csv.gz"
    if args.report_dir is not None:
        report = args.report_dir
    elif cache.resolve() == default_cache.resolve():
        report = BASE / "data" / "overnight" / (
            "rule_report_stress" if args.stress else "rule_report"
        )
    else:
        report = BASE / "data" / "overnight" / (
            "rule_report_smoke_stress" if args.stress else "rule_report_smoke"
        )
    report.mkdir(parents=True, exist_ok=True)
    summary.update({
        "dataset_files_considered": metadata.get("files_considered"),
        "dataset_rows": int(len(dataset)),
        "strict_1450_rows": metadata.get("strict_1450_rows", 0),
        "historical_st_status_available": metadata.get(
            "historical_st_status_available", False
        ),
        "research_only": metadata.get("strict_1450_rows", 0) == 0,
        "stress_slippage": bool(args.stress),
    })
    _save_csv_atomic(trades, report / "trades.csv")
    _save_csv_atomic(daily, report / "equity_curve.csv")
    _save_json_atomic(summary, report / "summary.json")

    print(f"交易笔数: {summary['trades']}")
    print(f"胜率: {_pct(summary.get('win_rate', 0))}")
    print(f"净收益≥1%命中率: {_pct(summary.get('target_1pct_rate', 0))}")
    print(f"平均净收益/笔: {_pct(summary.get('average_net_return', 0))}")
    print(f"累计收益: {_pct(summary.get('cumulative_return', 0))}")
    print(f"最大回撤: {_pct(summary.get('max_drawdown', 0))}")
    print(f"Profit Factor: {summary.get('profit_factor', 0):.2f}")
    print(f"报告: {report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
