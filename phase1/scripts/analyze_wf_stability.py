#!/usr/bin/env python3
"""Post-only concentration diagnostics for proxy Walk-Forward reports."""

import json
from pathlib import Path

import numpy as np
import pandas as pd


BASE = Path(__file__).resolve().parent.parent
OVERNIGHT = BASE / "data" / "overnight"


def _safe_share(numerator: float, denominator: float) -> float:
    return float(numerator / denominator) if denominator > 0 else 0.0


def analyse(report_name: str) -> tuple[dict, pd.DataFrame]:
    report = OVERNIGHT / report_name
    trades = pd.read_csv(
        report / "all_trades.csv", dtype={"code": str}, low_memory=False
    )
    summary = json.loads((report / "summary.json").read_text(encoding="utf-8"))
    windows = pd.read_csv(report / "window_stats.csv", low_memory=False)
    if trades.empty:
        return {
            "report": report_name,
            "trades": 0,
            "diagnostic_only": True,
            "acceptance_pass": False,
        }, pd.DataFrame()

    trades["date"] = pd.to_datetime(trades["date"], errors="coerce")
    trades["month"] = trades["date"].dt.to_period("M").astype(str)
    trades["pnl"] = pd.to_numeric(trades["pnl"], errors="coerce").fillna(0.0)
    trades["net_return"] = pd.to_numeric(
        trades["net_return"], errors="coerce"
    )
    monthly = (
        trades.groupby("month", sort=True)
        .agg(
            trades=("code", "size"),
            unique_codes=("code", "nunique"),
            pnl=("pnl", "sum"),
            average_net_return=("net_return", "mean"),
            win_rate=("net_return", lambda values: float((values > 0).mean())),
        )
        .reset_index()
    )
    positive_month_pnl = monthly.loc[monthly["pnl"] > 0, "pnl"]
    positive_trade_pnl = trades.loc[trades["pnl"] > 0, "pnl"].sort_values(
        ascending=False
    )
    code_counts = trades["code"].value_counts()
    day_counts = trades.groupby("date").size()
    total_positive_month_pnl = float(positive_month_pnl.sum())
    total_positive_trade_pnl = float(positive_trade_pnl.sum())
    result = {
        "report": report_name,
        "diagnostic_only": True,
        "trades": int(len(trades)),
        "unique_trading_days": int(trades["date"].nunique()),
        "maximum_trades_per_day": int(day_counts.max()),
        "top1_contract_satisfied": bool(day_counts.max() <= 1),
        "unique_codes": int(trades["code"].nunique()),
        "largest_code_trade_share": _safe_share(
            float(code_counts.iloc[0]), float(len(trades))
        ),
        "months_with_trades": int(len(monthly)),
        "profitable_months_with_trades": int((monthly["pnl"] > 0).sum()),
        "largest_positive_month_share": _safe_share(
            float(positive_month_pnl.max()) if not positive_month_pnl.empty else 0.0,
            total_positive_month_pnl,
        ),
        "top5_winning_trade_pnl_share": _safe_share(
            float(positive_trade_pnl.head(5).sum()), total_positive_trade_pnl
        ),
        "largest_winning_trade_pnl_share": _safe_share(
            float(positive_trade_pnl.iloc[0]) if not positive_trade_pnl.empty else 0.0,
            total_positive_trade_pnl,
        ),
        "total_windows": int(len(windows)),
        "profitable_windows": int((windows["cumulative_return"] > 0).sum()),
        "zero_trade_windows": int((windows["trades"] == 0).sum()),
        "proxy_trade_rate": float(summary.get("proxy_trade_rate", 1.0)),
        "strict_trade_rate": float(summary.get("strict_trade_rate", 0.0)),
        "win_rate_ci_low_95": float(summary.get("win_rate_ci_low_95", 0.0)),
        "window_consistency": float(summary.get("window_consistency", 0.0)),
        "acceptance_pass": bool(summary.get("acceptance_pass", False)),
        "research_only": bool(summary.get("research_only", True)),
    }
    result["concentration_warning"] = bool(
        result["largest_positive_month_share"] > 0.50
        or result["top5_winning_trade_pnl_share"] > 0.50
        or result["profitable_windows"] < 0.70 * result["total_windows"]
    )
    return result, monthly


def _save_json_atomic(value, path: Path) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    temporary.replace(path)


def _save_csv_atomic(frame: pd.DataFrame, path: Path) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    frame.to_csv(temporary, index=False)
    temporary.replace(path)


def main() -> int:
    results = []
    for name in ("wf_report", "wf_report_stress"):
        result, monthly = analyse(name)
        results.append(result)
        _save_csv_atomic(
            monthly, OVERNIGHT / name / "monthly_concentration.csv"
        )
    combined = {
        "contract": "post-only-proxy-stability-v1",
        "may_unlock_research_gate": False,
        "reports": results,
    }
    output = OVERNIGHT / "wf_stability.json"
    _save_json_atomic(combined, output)
    print(json.dumps(combined, ensure_ascii=False, indent=2))
    print(f"已保存: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
