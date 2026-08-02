#!/usr/bin/env python3
"""Genuine date-ordered walk-forward validation."""

import argparse
import csv
import hashlib
import json
import math
import sys
from dataclasses import replace
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
ROOT = BASE.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(BASE))

from overnight import (
    build_precision_coverage_report,
    load_research_dataset,
    run_walk_forward,
)
from overnight.backtesting import SelectionPolicy
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


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _optional_float(value):
    if value in (None, "", "None", "nan"):
        return None
    parsed = float(value)
    if not math.isfinite(parsed):
        raise ValueError("frozen policy contains a non-finite threshold")
    return parsed


def _load_frozen_policies(path: Path):
    if not path.exists():
        return {}
    policies = {}
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            key = str(row.get("test_start", ""))[:10]
            if not key:
                continue
            policies[key] = SelectionPolicy(
                max_positions=1,
                minimum_predicted_return=_optional_float(
                    row.get("policy_minimum_predicted_return")
                ),
                minimum_positive_probability=_optional_float(
                    row.get("policy_minimum_positive_probability")
                ),
                maximum_large_loss_probability=_optional_float(
                    row.get("policy_maximum_large_loss_probability")
                ),
                minimum_regime_score=_optional_float(
                    row.get("policy_minimum_regime_score")
                ),
                score_column=str(
                    row.get("policy_score_column") or "predicted_return"
                ),
            )
    return policies


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
    parser.add_argument(
        "--dataset-mode", choices=["proxy", "strict"], default="proxy"
    )
    parser.add_argument("--report-dir", type=Path, default=None)
    parser.add_argument("--stress", action="store_true", help="买卖滑点均按0.10%")
    args = parser.parse_args()

    cache = args.cache or (BASE / "data" / "overnight" / "dataset.csv.gz")
    try:
        dataset, metadata, selected_cache = load_research_dataset(
            BASE / "data" / "daily",
            cache,
            spec=DEFAULT_SPEC,
            dataset_mode=args.dataset_mode,
            rebuild=args.rebuild,
            max_stocks=args.max_stocks,
        )
    except (OSError, TypeError, ValueError, RuntimeError) as exc:
        print(f"拒绝Walk-Forward: {exc}")
        return 2
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
    if args.dataset_mode == "strict":
        normal_report = BASE / "data" / "overnight" / "wf_report_strict"
    else:
        normal_report = BASE / "data" / "overnight" / "wf_report"
    frozen_policies = {}
    normal_summary_hash = ""
    normal_window_hash = ""
    if args.stress:
        normal_window_path = normal_report / "window_stats.csv"
        normal_summary_path = normal_report / "summary.json"
        try:
            frozen_policies = _load_frozen_policies(normal_window_path)
        except (OSError, TypeError, ValueError) as exc:
            print(f"拒绝压力测试: 冻结策略无效: {exc}")
            return 2
        if not frozen_policies or not normal_summary_path.exists() or not normal_window_path.exists():
            print("拒绝压力测试: 必须先生成同数据口径的普通Walk-Forward报告")
            return 2
        try:
            normal_summary = json.loads(normal_summary_path.read_text(encoding="utf-8"))
        except (OSError, TypeError, ValueError) as exc:
            print(f"拒绝压力测试: 普通报告无效: {exc}")
            return 2
        normal_window_hash = _sha256(normal_window_path)
        if normal_summary.get("window_stats_sha256") != normal_window_hash:
            print("拒绝压力测试: 普通报告与窗口策略文件血缘不一致")
            return 2
        normal_summary_hash = _sha256(normal_summary_path)

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
        frozen_policies=frozen_policies or None,
    )

    default_cache = BASE / "data" / "overnight" / "dataset.csv.gz"
    if args.report_dir is not None:
        report = args.report_dir
    elif args.dataset_mode == "strict":
        report = BASE / "data" / "overnight" / (
            "wf_report_strict_stress" if args.stress else "wf_report_strict"
        )
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
        "point_in_time_universe_verified": bool(
            metadata.get("point_in_time_universe_verified", False)
        ),
        "point_in_time_security_name_verified": bool(
            metadata.get("point_in_time_security_name_verified", False)
        ),
        "strict_dataset_ready": bool(metadata.get("strict_dataset_ready", False)),
        "volume_unit": metadata.get("volume_unit", "unknown"),
        "volume_unit_verified": bool(metadata.get("volume_unit_verified", False)),
        "research_only": not bool(metadata.get("strict_dataset_ready", False)),
        "stress_slippage": bool(args.stress),
        "dataset_mode": metadata.get("dataset_mode", args.dataset_mode),
        "dataset_path": str(selected_cache),
        "dataset_sha256": metadata.get("dataset_sha256", ""),
        "lineage_verified": bool(metadata.get("lineage_verified", False)),
        "normal_report_sha256": normal_summary_hash,
        "normal_window_stats_sha256": normal_window_hash,
        "stress_policy_frozen": bool(
            args.stress
            and summary.get("frozen_policy_windows", 0)
            == summary.get("total_windows", 0)
        ),
        "walk_forward_config": {
            "train_months": args.train_months,
            "test_months": args.test_months,
            "embargo_days": args.embargo_days,
            "model": args.model,
            "minimum_predicted_return": args.minimum_predicted_return,
            "market_filter": not args.no_market_filter,
            "max_train_rows": args.max_train_rows,
            "precision_optimization": not args.no_precision_optimization,
        },
    })
    summary["acceptance_pass"] = bool(
        not args.stress
        and summary["dataset_mode"] == "strict"
        and summary["lineage_verified"]
        and not summary["research_only"]
        and summary.get("proxy_trade_rate", 1.0) == 0.0
        and summary.get("strict_buy_trade_rate", 0.0) == 1.0
        and summary.get("strict_sell_trade_rate", 0.0) == 1.0
        and summary.get("strict_feature_trade_rate", 0.0) == 1.0
        and summary.get("order_book_verified_trade_rate", 0.0) == 1.0
        and summary.get("order_book_liquidity_trade_rate", 0.0) == 1.0
        and summary.get("calendar_verified_trade_rate", 0.0) == 1.0
        and summary.get("calendar_verified", False)
        and summary.get("minimum_buy_universe_coverage", 0.0) >= 0.95
        and summary.get("point_in_time_universe_verified", False)
        and summary.get("point_in_time_security_name_verified", False)
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
    summary["window_stats_sha256"] = _sha256(report / "window_stats.csv")
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
