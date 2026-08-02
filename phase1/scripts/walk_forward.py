#!/usr/bin/env python3
"""Genuine date-ordered walk-forward validation."""

import argparse
import json
import sys
from dataclasses import replace
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
ROOT = BASE.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(BASE))

from overnight import (
    build_precision_coverage_report,
    load_or_build_dataset,
    run_walk_forward,
)
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
    parser.add_argument("--train-months", type=int, default=12)
    parser.add_argument("--test-months", type=int, default=3)
    parser.add_argument("--embargo-days", type=int, default=1)
    parser.add_argument("--model", choices=["auto", "ridge", "lightgbm"], default="auto")
    parser.add_argument("--minimum-predicted-return", type=float, default=0.0)
    parser.add_argument("--no-market-filter", action="store_true")
    parser.add_argument("--max-train-rows", type=int, default=500_000)
    parser.add_argument(
        "--no-precision-optimization",
        action="store_true",
        help="关闭训练窗口内的胜率/覆盖率策略选择",
    )
    parser.add_argument("--cache", type=Path, default=None)
    parser.add_argument("--report-dir", type=Path, default=None)
    parser.add_argument("--stress", action="store_true", help="买卖滑点均按0.10%")
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

    print("=== 严格按日期 Walk-Forward ===")
    if metadata.get("strict_1450_rows", 0) == 0:
        print("[警告] 成交价仍是15:00代理；本次结果只能评价模型流程，不能作为实盘依据")

    run_spec = (
        replace(
            DEFAULT_SPEC,
            buy_slippage_rate=DEFAULT_SPEC.stress_slippage_rate,
            sell_slippage_rate=DEFAULT_SPEC.stress_slippage_rate,
        )
        if args.stress
        else DEFAULT_SPEC
    )
    trades, daily, windows, importance, summary = run_walk_forward(
        dataset,
        run_spec,
        train_months=args.train_months,
        test_months=args.test_months,
        embargo_trading_days=args.embargo_days,
        model_kind=args.model,
        minimum_predicted_return=args.minimum_predicted_return,
        market_filter=not args.no_market_filter,
        max_train_rows=args.max_train_rows,
        optimize_precision=not args.no_precision_optimization,
    )

    default_cache = BASE / "data" / "overnight" / "dataset.csv.gz"
    if args.report_dir is not None:
        report = args.report_dir
    elif cache.resolve() == default_cache.resolve():
        report = BASE / "data" / "overnight" / (
            "wf_report_stress" if args.stress else "wf_report"
        )
    else:
        report = BASE / "data" / "overnight" / (
            "wf_report_smoke_stress" if args.stress else "wf_report_smoke"
        )
    report.mkdir(parents=True, exist_ok=True)
    summary.update({
        "dataset_files_considered": metadata.get("files_considered"),
        "dataset_rows": int(len(dataset)),
        "strict_1450_rows": metadata.get("strict_1450_rows", 0),
        "historical_st_status_available": metadata.get(
            "historical_st_status_available", False
        ),
        "strict_sell_rows": metadata.get("strict_sell_rows", 0),
        "strict_feature_rows": metadata.get("strict_feature_rows", 0),
        "strict_rows": metadata.get("strict_rows", 0),
        "calendar_verified": bool(metadata.get("calendar_verified", False)),
        "minimum_buy_universe_coverage": float(
            metadata.get("minimum_buy_universe_coverage", 0.0)
        ),
        "strict_dataset_ready": bool(metadata.get("strict_dataset_ready", False)),
        "volume_unit": metadata.get("volume_unit", "unknown"),
        "volume_unit_verified": bool(metadata.get("volume_unit_verified", False)),
        "research_only": not bool(metadata.get("strict_dataset_ready", False)),
        "stress_slippage": bool(args.stress),
    })
    summary["acceptance_pass"] = bool(
        not summary["research_only"]
        and summary.get("proxy_trade_rate", 1.0) == 0.0
        and summary.get("strict_buy_trade_rate", 0.0) == 1.0
        and summary.get("strict_sell_trade_rate", 0.0) == 1.0
        and summary.get("strict_feature_trade_rate", 0.0) == 1.0
        and summary.get("order_book_verified_trade_rate", 0.0) == 1.0
        and summary.get("order_book_liquidity_trade_rate", 0.0) == 1.0
        and summary.get("calendar_verified_trade_rate", 0.0) == 1.0
        and summary.get("calendar_verified", False)
        and summary.get("minimum_buy_universe_coverage", 0.0) >= 0.95
        and summary.get("volume_unit_verified", False)
        and summary.get("trades", 0) >= 500
        and summary.get("win_rate_ci_low_95", 0.0) > 0.50
        and summary.get("profit_factor", 0.0) >= 1.20
        and summary.get("window_consistency", 0.0) >= 0.70
        and summary.get("cumulative_return", 0.0) > 0.0
        and summary.get("max_drawdown", -1.0) >= -0.12
    )
    _save_csv_atomic(trades, report / "all_trades.csv")
    _save_csv_atomic(daily, report / "equity_curve.csv")
    _save_csv_atomic(windows, report / "window_stats.csv")
    _save_csv_atomic(importance, report / "feature_importance.csv")
    _save_csv_atomic(
        build_precision_coverage_report(trades), report / "precision_coverage.csv"
    )
    _save_json_atomic(summary, report / "summary.json")

    for row in windows.itertuples(index=False):
        print(
            f"W{row.window} {row.test_start}→{row.test_end} | "
            f"{row.trades}笔 | 收益 {_pct(row.cumulative_return)} | "
            f"DD {_pct(row.max_drawdown)}"
        )
    print("\n--- 汇总 ---")
    print(f"交易笔数: {summary['trades']}")
    print(f"胜率: {_pct(summary.get('win_rate', 0))}")
    print(
        "胜率95%下限: "
        f"{_pct(summary.get('win_rate_ci_low_95', 0))}"
    )
    print(f"净收益≥1%命中率: {_pct(summary.get('target_1pct_rate', 0))}")
    print(f"平均净收益/笔: {_pct(summary.get('average_net_return', 0))}")
    print(f"累计收益: {_pct(summary.get('cumulative_return', 0))}")
    print(f"最大回撤: {_pct(summary.get('max_drawdown', 0))}")
    print(
        f"盈利窗口: {summary.get('profitable_windows', 0)}/"
        f"{summary.get('total_windows', 0)}"
    )
    if summary.get("proxy_trade_rate", 1.0) > 0:
        print("结论: 研究流程已可用；取得14:50分钟历史数据前，不进入实盘验收。")
    print(f"报告: {report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
