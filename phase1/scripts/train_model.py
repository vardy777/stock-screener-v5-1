#!/usr/bin/env python3
"""Fit the final overnight model after walk-forward validation."""

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

BASE = Path(__file__).resolve().parent.parent
ROOT = BASE.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(BASE))

from overnight import FEATURE_COLUMNS, load_or_build_dataset
from overnight.model import create_model
from strategy_spec import DEFAULT_SPEC


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rebuild", action="store_true")
    parser.add_argument("--max-stocks", type=int, default=None)
    parser.add_argument("--model", choices=["auto", "ridge", "lightgbm"], default="auto")
    parser.add_argument("--cache", type=Path, default=None)
    parser.add_argument(
        "--force",
        action="store_true",
        help="绕过Walk-Forward准入门槛，仅用于开发诊断",
    )
    args = parser.parse_args()

    gate_path = BASE / "data" / "overnight" / "wf_report" / "summary.json"
    stress_gate_path = (
        BASE / "data" / "overnight" / "wf_report_stress" / "summary.json"
    )
    if not args.force:
        if not gate_path.exists():
            print("拒绝训练最终模型: 尚无全市场Walk-Forward报告")
            return 2
        with gate_path.open("r", encoding="utf-8") as handle:
            gate = json.load(handle)
        if not stress_gate_path.exists():
            print("拒绝训练最终模型: 尚无加倍滑点压力测试报告")
            return 2
        with stress_gate_path.open("r", encoding="utf-8") as handle:
            stress_gate = json.load(handle)
        passed = (
            gate.get("acceptance_pass", False)
            and gate.get("proxy_trade_rate", 1.0) == 0.0
            and gate.get("strict_buy_trade_rate", 0.0) == 1.0
            and gate.get("strict_sell_trade_rate", 0.0) == 1.0
            and gate.get("strict_feature_trade_rate", 0.0) == 1.0
            and gate.get("order_book_verified_trade_rate", 0.0) == 1.0
            and gate.get("order_book_liquidity_trade_rate", 0.0) == 1.0
            and gate.get("calendar_verified_trade_rate", 0.0) == 1.0
            and gate.get("calendar_verified", False)
            and gate.get("minimum_buy_universe_coverage", 0.0) >= 0.95
            and gate.get("volume_unit_verified", False)
            and stress_gate.get("cumulative_return", 0.0) > 0.0
            and stress_gate.get("profit_factor", 0.0) >= 1.0
            and stress_gate.get("proxy_trade_rate", 1.0) == 0.0
            and stress_gate.get("strict_trade_rate", 0.0) == 1.0
        )
        if not passed:
            print("拒绝训练最终模型: Walk-Forward未达到实盘准入门槛")
            return 2

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

    dataset["date"] = pd.to_datetime(dataset["date"]).dt.normalize()
    unique_dates = sorted(dataset["date"].unique())
    if len(unique_dates) < 2:
        print("日期不足")
        return 1
    # Keep one trading-day embargo so the newest label is unquestionably known.
    train = dataset[dataset["date"] < unique_dates[-1]].copy()
    model = create_model(FEATURE_COLUMNS, args.model)
    model.fit(train)

    model_dir = BASE / "data" / "overnight" / "model"
    model_dir.mkdir(parents=True, exist_ok=True)
    suffix = ".json" if model.name == "ridge" else ".pkl"
    model_path = model_dir / f"overnight_{model.name}{suffix}"
    model.save(model_path)
    model.feature_importance().to_csv(model_dir / "feature_importance.csv", index=False)
    training_info = {
        "model": model.name,
        "rows": int(len(train)),
        "start_date": str(train["date"].min())[:10],
        "end_date": str(train["date"].max())[:10],
        "target_1pct_rate": float(train["target_1pct"].mean()),
        "average_net_return": float(train["net_return"].mean()),
        "execution_modes": metadata.get("execution_modes", {}),
        "strict_dataset_ready": bool(metadata.get("strict_dataset_ready", False)),
        "research_only": not bool(metadata.get("strict_dataset_ready", False)),
    }
    with (model_dir / "training_info.json").open("w", encoding="utf-8") as handle:
        json.dump(training_info, handle, ensure_ascii=False, indent=2)
    print(json.dumps(training_info, ensure_ascii=False, indent=2))
    print(f"模型: {model_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
