"""Cash-based baseline and genuine walk-forward simulation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from decision_policy import market_is_risk_off, market_regime_score
from strategy_spec import DEFAULT_SPEC, StrategySpec, TradeCostModel
from .dataset import FEATURE_COLUMNS
from .model import create_model


@dataclass(frozen=True)
class SelectionPolicy:
    """Validation-derived abstention policy for one outer test window."""

    max_positions: int = 1
    minimum_predicted_return: Optional[float] = 0.0
    minimum_positive_probability: Optional[float] = None
    maximum_large_loss_probability: Optional[float] = None
    minimum_regime_score: Optional[float] = None
    score_column: str = "predicted_return"

    def __post_init__(self):
        if self.max_positions != 1:
            raise ValueError("V4 selection policy is fixed to Top1")

    def to_dict(self) -> dict:
        return {
            "max_positions": self.max_positions,
            "minimum_predicted_return": self.minimum_predicted_return,
            "minimum_positive_probability": self.minimum_positive_probability,
            "maximum_large_loss_probability": self.maximum_large_loss_probability,
            "minimum_regime_score": self.minimum_regime_score,
            "score_column": self.score_column,
        }

    @classmethod
    def from_dict(cls, value: dict) -> "SelectionPolicy":
        value = value if isinstance(value, dict) else {}
        return cls(
            max_positions=int(value.get("max_positions", 1)),
            minimum_predicted_return=value.get("minimum_predicted_return", 0.0),
            minimum_positive_probability=value.get("minimum_positive_probability"),
            maximum_large_loss_probability=value.get("maximum_large_loss_probability"),
            minimum_regime_score=value.get("minimum_regime_score"),
            score_column=str(value.get("score_column", "predicted_return")),
        )


def _market_regime_score(day: pd.DataFrame) -> float:
    """Combine breadth, intraday market return and opening gap into [-1, 1]."""

    if day.empty:
        return -1.0
    return market_regime_score(
        float(day["market_breadth"].iloc[0]),
        float(day["market_mean_signal_return"].iloc[0]),
        float(day.get("market_mean_gap", pd.Series([0.0])).iloc[0]),
    )


def _risk_off(day: pd.DataFrame) -> bool:
    """Hard safety gate; finer regime selection is learned on validation data."""

    if day.empty:
        return True
    breadth = float(day["market_breadth"].iloc[0])
    market_return = float(day["market_mean_signal_return"].iloc[0])
    market_gap = float(day.get("market_mean_gap", pd.Series([0.0])).iloc[0])
    return market_is_risk_off(
        breadth, market_return, market_gap
    )


def add_rule_score(dataset: pd.DataFrame) -> pd.DataFrame:
    """Transparent point-in-time baseline; no fitted historical parameters."""

    result = dataset.copy()
    weights = {
        "signal_return": 0.20,
        "signal_close_position": 0.15,
        "volume_ratio_20": 0.10,
        "ret_5d": 0.15,
        "price_to_ma20": 0.10,
        "overnight_mean_20": 0.15,
        "overnight_hit_1pct_20": 0.15,
    }
    result["rule_score"] = 0.0
    by_date = result.groupby("date", sort=False)
    for feature, weight in weights.items():
        ranks = by_date[feature].rank(pct=True, method="average")
        result["rule_score"] += ranks.fillna(0.5) * weight
    result["predicted_return"] = result["rule_score"]
    result["predicted_positive_probability"] = result["overnight_mean_20"].rank(
        pct=True
    ).fillna(0.5)
    result["predicted_hit_probability"] = result["overnight_hit_1pct_20"].clip(0, 1)
    result["predicted_large_loss_probability"] = result["volatility_20"].rank(
        pct=True
    ).fillna(0.5)
    return result


def _simulate_selection(
    scored: pd.DataFrame,
    spec: StrategySpec,
    *,
    score_column: str,
    minimum_score: Optional[float],
    market_filter: bool,
    initial_capital: Optional[float] = None,
    policy: Optional[SelectionPolicy] = None,
) -> Tuple[pd.DataFrame, pd.DataFrame, Dict[str, float]]:
    costs = TradeCostModel(spec)
    capital = float(initial_capital or spec.initial_capital)
    trade_rows: List[dict] = []
    daily_rows: List[dict] = []

    for trade_date, day in scored.groupby("date", sort=True):
        day = day.copy()
        start_capital = capital
        regime_score = _market_regime_score(day)
        if market_filter and _risk_off(day):
            daily_rows.append(
                {
                    "date": trade_date,
                    "start_capital": start_capital,
                    "end_capital": capital,
                    "daily_return": 0.0,
                    "positions": 0,
                    "risk_off": 1,
                    "regime_score": regime_score,
                }
            )
            continue

        if (
            policy is not None
            and policy.minimum_regime_score is not None
            and regime_score < policy.minimum_regime_score
        ):
            daily_rows.append(
                {
                    "date": trade_date,
                    "start_capital": start_capital,
                    "end_capital": capital,
                    "daily_return": 0.0,
                    "positions": 0,
                    "risk_off": 1,
                    "regime_score": regime_score,
                }
            )
            continue

        if "eligible_entry" in day.columns:
            day = day[day["eligible_entry"] == 1]
        if "valid_label" in day.columns:
            day = day[day["valid_label"] == 1]
        day = day.replace([np.inf, -np.inf], np.nan).dropna(
            subset=[score_column, "buy_reference", "sell_reference"]
        )
        if minimum_score is not None:
            day = day[day[score_column] >= minimum_score]
        if policy is not None:
            if (
                policy.minimum_positive_probability is not None
                and "predicted_positive_probability" in day.columns
            ):
                day = day[
                    day["predicted_positive_probability"]
                    >= policy.minimum_positive_probability
                ]
            if (
                policy.maximum_large_loss_probability is not None
                and "predicted_large_loss_probability" in day.columns
            ):
                day = day[
                    day["predicted_large_loss_probability"]
                    <= policy.maximum_large_loss_probability
                ]
        day = day.sort_values(
            [score_column, "predicted_positive_probability", "predicted_hit_probability"],
            ascending=False,
        ).head(policy.max_positions if policy is not None else spec.max_positions)

        position_budget = spec.position_budget(start_capital)
        available_cash = start_capital
        total_pnl = 0.0
        executed = 0
        for _, row in day.iterrows():
            budget = min(position_budget, available_cash)
            shares = costs.max_affordable_shares(
                float(row["buy_reference"]), budget, apply_buy_slippage=True
            )
            if shares <= 0:
                continue
            cash_flow = costs.round_trip(
                float(row["buy_reference"]),
                float(row["sell_reference"]),
                shares,
                apply_slippage=True,
            )
            if cash_flow["cash_out"] > available_cash + 1e-8:
                continue
            available_cash -= cash_flow["cash_out"]
            total_pnl += cash_flow["pnl"]
            executed += 1
            trade_rows.append(
                {
                    "date": trade_date,
                    "code": str(row["code"]).zfill(6),
                    "execution_mode": row.get("execution_mode", "unknown"),
                    "exit_mode": row.get("exit_mode", "next_open_proxy"),
                    "feature_mode": row.get("feature_mode", "unknown"),
                    "exact_buy": bool(row.get("exact_buy", False)),
                    "exact_sell": bool(row.get("exact_sell", False)),
                    "calendar_verified": bool(row.get("calendar_verified", False)),
                    "order_book_verified": bool(
                        row.get("order_book_verified", False)
                    ),
                    "order_book_liquidity_verified": bool(
                        row.get("order_book_liquidity_verified", False)
                    ),
                    "strict_row": bool(row.get("strict_row", False)),
                    "exit_delay_days": int(row.get("exit_delay_days", 0) or 0),
                    "score": float(row[score_column]),
                    "predicted_return": float(row.get("predicted_return", np.nan)),
                    "selection_score": float(row.get("selection_score", np.nan)),
                    "predicted_positive_probability": float(
                        row.get("predicted_positive_probability", np.nan)
                    ),
                    "predicted_hit_probability": float(
                        row.get("predicted_hit_probability", np.nan)
                    ),
                    "predicted_large_loss_probability": float(
                        row.get("predicted_large_loss_probability", np.nan)
                    ),
                    "regime_score": regime_score,
                    **cash_flow,
                }
            )

        capital = start_capital + total_pnl
        daily_rows.append(
            {
                "date": trade_date,
                "start_capital": start_capital,
                "end_capital": capital,
                "daily_return": total_pnl / start_capital if start_capital else 0.0,
                "positions": executed,
                "risk_off": 0,
                "regime_score": regime_score,
            }
        )

    trades = pd.DataFrame(trade_rows)
    daily = pd.DataFrame(daily_rows)
    return trades, daily, calculate_metrics(
        trades, daily, float(initial_capital or spec.initial_capital)
    )


def calculate_metrics(
    trades: pd.DataFrame, daily: pd.DataFrame, initial_capital: float
) -> Dict[str, float]:
    if daily.empty:
        return {
            "trades": 0,
            "trading_days": 0,
            "cumulative_return": 0.0,
            "max_drawdown": 0.0,
            "sharpe": 0.0,
        }

    end_capital = float(daily["end_capital"].iloc[-1])
    daily_return = pd.to_numeric(daily["daily_return"], errors="coerce").fillna(0.0)
    equity = pd.to_numeric(daily["end_capital"], errors="coerce").ffill()
    peak = equity.cummax()
    drawdown = equity / peak - 1.0
    std = float(daily_return.std(ddof=0))
    sharpe = float(daily_return.mean() / std * np.sqrt(252)) if std > 0 else 0.0

    result: Dict[str, float] = {
        "trades": int(len(trades)),
        "trading_days": int((daily["positions"] > 0).sum()),
        "empty_or_filtered_days": int((daily["positions"] == 0).sum()),
        "end_capital": end_capital,
        "cumulative_return": end_capital / float(initial_capital) - 1.0,
        "max_drawdown": float(drawdown.min()),
        "sharpe": sharpe,
    }
    if trades.empty:
        result.update(
            {
                "win_rate": 0.0,
                "win_rate_ci_low_95": 0.0,
                "win_rate_ci_high_95": 0.0,
                "target_1pct_rate": 0.0,
                "average_net_return": 0.0,
                "median_net_return": 0.0,
                "profit_factor": 0.0,
                "largest_loss": 0.0,
                "proxy_trade_rate": 1.0,
                "strict_buy_trade_rate": 0.0,
                "strict_sell_trade_rate": 0.0,
                "strict_feature_trade_rate": 0.0,
                "strict_trade_rate": 0.0,
                "calendar_verified_trade_rate": 0.0,
                "order_book_verified_trade_rate": 0.0,
                "order_book_liquidity_trade_rate": 0.0,
            }
        )
        return result

    returns = pd.to_numeric(trades["net_return"], errors="coerce").dropna()
    if returns.empty:
        result.update(
            {
                "win_rate": 0.0,
                "win_rate_ci_low_95": 0.0,
                "win_rate_ci_high_95": 0.0,
                "target_1pct_rate": 0.0,
                "average_net_return": 0.0,
                "median_net_return": 0.0,
                "profit_factor": 0.0,
                "largest_loss": 0.0,
                "proxy_trade_rate": 1.0,
                "strict_buy_trade_rate": 0.0,
                "strict_sell_trade_rate": 0.0,
                "strict_feature_trade_rate": 0.0,
                "strict_trade_rate": 0.0,
                "calendar_verified_trade_rate": 0.0,
                "order_book_verified_trade_rate": 0.0,
                "order_book_liquidity_trade_rate": 0.0,
            }
        )
        return result
    positive = returns[returns > 0]
    negative = returns[returns <= 0]
    gross_profit = float(positive.sum())
    gross_loss = abs(float(negative.sum()))
    wins = int((returns > 0).sum())
    sample_size = int(len(returns))
    observed = wins / sample_size if sample_size else 0.0
    z = 1.959963984540054
    denominator = 1.0 + z * z / sample_size
    centre = observed + z * z / (2.0 * sample_size)
    margin = z * np.sqrt(
        observed * (1.0 - observed) / sample_size
        + z * z / (4.0 * sample_size * sample_size)
    )
    exact_buy = trades.get(
        "exact_buy", trades["execution_mode"].isin({"minute_14_50", "snapshot_14_50"})
    ).fillna(False).astype(bool)
    exact_sell = trades.get(
        "exact_sell", trades["exit_mode"].eq("snapshot_09_30")
    ).fillna(False).astype(bool)
    strict_feature = trades.get(
        "feature_mode", pd.Series("unknown", index=trades.index)
    ).eq("strict_pre_1450")
    calendar_verified = trades.get(
        "calendar_verified", pd.Series(False, index=trades.index)
    ).fillna(False).astype(bool)
    order_book_verified = trades.get(
        "order_book_verified", pd.Series(False, index=trades.index)
    ).fillna(False).astype(bool)
    order_book_liquidity = trades.get(
        "order_book_liquidity_verified", pd.Series(False, index=trades.index)
    ).fillna(False).astype(bool)
    strict_trade = (
        exact_buy
        & exact_sell
        & strict_feature
        & calendar_verified
        & order_book_verified
        & order_book_liquidity
    )
    result.update(
        {
            "win_rate": observed,
            "win_rate_ci_low_95": float((centre - margin) / denominator),
            "win_rate_ci_high_95": float((centre + margin) / denominator),
            "target_1pct_rate": float((returns >= 0.01).mean()),
            "average_net_return": float(returns.mean()),
            "median_net_return": float(returns.median()),
            "profit_factor": gross_profit / gross_loss if gross_loss > 0 else 0.0,
            "largest_loss": float(returns.min()),
            "proxy_trade_rate": float((~strict_trade).mean()),
            "strict_buy_trade_rate": float(exact_buy.mean()),
            "strict_sell_trade_rate": float(exact_sell.mean()),
            "strict_feature_trade_rate": float(strict_feature.mean()),
            "strict_trade_rate": float(strict_trade.mean()),
            "calendar_verified_trade_rate": float(calendar_verified.mean()),
            "order_book_verified_trade_rate": float(order_book_verified.mean()),
            "order_book_liquidity_trade_rate": float(order_book_liquidity.mean()),
            "delayed_exit_trades": int((trades["exit_delay_days"] > 0).sum()),
        }
    )
    return result


def run_rule_backtest(
    dataset: pd.DataFrame,
    spec: StrategySpec = DEFAULT_SPEC,
    *,
    minimum_score: float = 0.55,
    market_filter: bool = True,
):
    scored = add_rule_score(dataset)
    return _simulate_selection(
        scored,
        spec,
        score_column="rule_score",
        minimum_score=minimum_score,
        market_filter=market_filter,
    )


def _sample_training_rows(frame: pd.DataFrame, maximum: int) -> pd.DataFrame:
    if len(frame) <= maximum:
        return frame
    # Deterministic sampling across the complete time-ordered frame.
    indices = np.linspace(0, len(frame) - 1, maximum, dtype=int)
    return frame.iloc[indices]


def _quantile_threshold(series: pd.Series, quantile: float) -> Optional[float]:
    values = pd.to_numeric(series, errors="coerce").dropna()
    if values.empty:
        return None
    return float(values.quantile(quantile))


def _empirical_percentile(reference: pd.Series, values: pd.Series) -> pd.Series:
    """Map new model outputs to the trailing validation distribution."""

    reference_values = np.sort(
        pd.to_numeric(reference, errors="coerce").dropna().to_numpy(dtype=float)
    )
    numeric = pd.to_numeric(values, errors="coerce").to_numpy(dtype=float)
    if len(reference_values) == 0:
        return pd.Series(np.full(len(values), 0.5), index=values.index)
    percentiles = np.searchsorted(reference_values, numeric, side="right") / len(
        reference_values
    )
    percentiles = np.where(np.isfinite(numeric), percentiles, 0.5)
    return pd.Series(percentiles, index=values.index)


def _add_calibrated_selection_score(
    reference: pd.DataFrame, target: pd.DataFrame
) -> None:
    """Create a stable joint confidence score without looking into target labels."""

    target["selection_score"] = (
        0.60
        * _empirical_percentile(
            reference["predicted_return"], target["predicted_return"]
        )
        + 0.40
        * _empirical_percentile(
            reference["predicted_positive_probability"],
            target["predicted_positive_probability"],
        )
        - 0.25
        * _empirical_percentile(
            reference["predicted_large_loss_probability"],
            target["predicted_large_loss_probability"],
        )
    )


def _derive_precision_policy(
    validation: pd.DataFrame,
    spec: StrategySpec,
    *,
    market_filter: bool,
) -> Tuple[SelectionPolicy, Dict[str, float]]:
    """Select a sparse policy using only the trailing training validation slice.

    The search space is intentionally small.  The goal is not to maximize an
    in-sample headline number, but to find the least-complex policy that clears
    positive expected value while preferring precision and fewer positions.
    """

    if validation.empty:
        policy = SelectionPolicy()
        return policy, {"validation_trades": 0, "validation_win_rate": 0.0}

    # Expected-return rank remains the execution score.  The joint calibrated
    # score is reported as a diagnostic until it proves stable on more data.
    score_column = "predicted_return"
    return_thresholds = sorted(
        {
            value
            for q in (0.70, 0.85, 0.90)
            if (value := _quantile_threshold(validation[score_column], q))
            is not None
        }
    )
    positive_thresholds = [None]
    positive_thresholds.extend(
        sorted(
            {
                value
                for q in (0.70, 0.85)
                if (
                    value := _quantile_threshold(
                        validation["predicted_positive_probability"], q
                    )
                )
                is not None
            }
        )
    )
    loss_caps = [None]
    loss_caps.extend(
        sorted(
            {
                value
                for q in (0.50,)
                if (
                    value := _quantile_threshold(
                        validation["predicted_large_loss_probability"], q
                    )
                )
                is not None
            }
        )
    )
    regime_thresholds = [None, 0.10, 0.30]
    minimum_trades = max(12, min(24, int(validation["date"].nunique() * 0.25)))
    candidates = []

    for max_positions in (1,):
        for minimum_return in return_thresholds:
            for minimum_positive in positive_thresholds:
                for maximum_loss in loss_caps:
                    for minimum_regime in regime_thresholds:
                        policy = SelectionPolicy(
                            max_positions=max_positions,
                            minimum_predicted_return=minimum_return,
                            minimum_positive_probability=minimum_positive,
                            maximum_large_loss_probability=maximum_loss,
                            minimum_regime_score=minimum_regime,
                            score_column=score_column,
                        )
                        trades, _, metrics = _simulate_selection(
                            validation,
                            spec,
                            score_column=score_column,
                            minimum_score=minimum_return,
                            market_filter=market_filter,
                            policy=policy,
                        )
                        count = int(metrics.get("trades", 0))
                        if count < minimum_trades:
                            continue
                        win_rate = float(metrics.get("win_rate", 0.0))
                        average_return = float(metrics.get("average_net_return", 0.0))
                        profit_factor = float(metrics.get("profit_factor", 0.0))
                        robust = (
                            win_rate >= 0.55
                            and average_return > 0.0
                            and profit_factor >= 1.05
                        )
                        utility = (
                            average_return * 100.0
                            + min(win_rate, 0.65)
                            + 0.04 * min(profit_factor, 2.5)
                            - 0.015 * (max_positions - 1)
                        )
                        candidates.append(
                            (robust, utility, win_rate, count, policy, metrics)
                        )

    if not candidates:
        policy = SelectionPolicy()
        return policy, {"validation_trades": 0, "validation_win_rate": 0.0}

    candidates.sort(key=lambda item: (item[0], item[2], item[1], item[3]), reverse=True)
    robust, _, _, _, policy, metrics = candidates[0]
    if not robust:
        # A failed validation window is a valid no-trade decision.  Do not
        # force exposure merely because one weak candidate policy ranked first.
        policy = SelectionPolicy(
            max_positions=1,
            minimum_predicted_return=float("inf"),
            minimum_positive_probability=None,
            maximum_large_loss_probability=None,
            minimum_regime_score=None,
            score_column=score_column,
        )
    return policy, {
        "validation_policy_robust": bool(robust),
        "validation_trades": int(metrics.get("trades", 0)),
        "validation_win_rate": float(metrics.get("win_rate", 0.0)),
        "validation_average_net_return": float(
            metrics.get("average_net_return", 0.0)
        ),
        "validation_profit_factor": float(metrics.get("profit_factor", 0.0)),
    }


def build_precision_coverage_report(trades: pd.DataFrame) -> pd.DataFrame:
    """Summarise out-of-sample precision as increasingly selective slices."""

    columns = [
        "ranking_signal",
        "top_fraction",
        "trades",
        "win_rate",
        "target_1pct_rate",
        "average_net_return",
        "profit_factor",
    ]
    if trades.empty:
        return pd.DataFrame(columns=columns)

    rows = []
    for signal in (
        "selection_score",
        "predicted_return",
        "predicted_positive_probability",
    ):
        if signal not in trades.columns:
            continue
        numeric = pd.to_numeric(trades[signal], errors="coerce")
        for fraction in (1.0, 0.50, 0.25, 0.10):
            threshold = float(numeric.quantile(1.0 - fraction))
            selected = trades[numeric >= threshold]
            returns = pd.to_numeric(selected["net_return"], errors="coerce").dropna()
            if returns.empty:
                continue
            gross_profit = float(returns[returns > 0].sum())
            gross_loss = abs(float(returns[returns <= 0].sum()))
            rows.append(
                {
                    "ranking_signal": signal,
                    "top_fraction": fraction,
                    "trades": int(len(returns)),
                    "win_rate": float((returns > 0).mean()),
                    "target_1pct_rate": float((returns >= 0.01).mean()),
                    "average_net_return": float(returns.mean()),
                    "profit_factor": (
                        gross_profit / gross_loss if gross_loss > 0 else 0.0
                    ),
                }
            )
    return pd.DataFrame(rows, columns=columns)


def fit_final_model_and_policy(
    dataset: pd.DataFrame,
    spec: StrategySpec = DEFAULT_SPEC,
    *,
    model_kind: str = "auto",
    market_filter: bool = True,
    max_train_rows: int = 500_000,
    validation_fraction: float = 0.20,
    require_strict: bool = True,
):
    """Fit the exact model artifact and its trailing, untouched policy.

    The returned model is deliberately *not* refitted on the validation rows;
    therefore the absolute thresholds learned on validation remain calibrated
    to the exact model that is published.
    """

    data = dataset.copy()
    data["date"] = pd.to_datetime(data["date"], errors="coerce").dt.normalize()
    data = data.dropna(subset=["date", "net_return"])
    if require_strict:
        missing_controls = [
            column
            for column in ("eligible_entry", "valid_label", "strict_row")
            if column not in data.columns
        ]
        if missing_controls:
            raise ValueError(
                "生产训练数据缺少控制列: " + ", ".join(missing_controls)
            )
    for column in ("eligible_entry", "valid_label"):
        if column in data.columns:
            data = data[data[column] == 1]
    if require_strict:
        data = data[data["strict_row"].fillna(False).astype(bool)]
    data = data.sort_values(["date", "code"])
    dates = pd.Index(sorted(data["date"].unique()))
    if len(dates) < 80:
        raise ValueError("严格日期不足80个，不能拟合生产模型与独立阈值")

    # The newest signal label is embargoed.  A trailing validation period then
    # remains completely outside the model fit.
    trainable = data[data["date"] < pd.Timestamp(dates[-1])].copy()
    train_dates = pd.Index(sorted(trainable["date"].unique()))
    validation_days = max(20, int(len(train_dates) * validation_fraction))
    validation_days = min(validation_days, max(20, len(train_dates) // 3))
    validation_start = pd.Timestamp(train_dates[-validation_days])
    fit_rows = trainable[trainable["date"] < validation_start].copy()
    validation = trainable[trainable["date"] >= validation_start].copy()
    if fit_rows["date"].nunique() < 60 or len(fit_rows) < 500:
        raise ValueError("生产模型拟合区间不足")
    if validation["date"].nunique() < 20:
        raise ValueError("生产阈值验证区间不足")

    model = create_model(FEATURE_COLUMNS, kind=model_kind)
    model.fit(_sample_training_rows(fit_rows, max_train_rows))
    predictions = model.predict(validation)
    for column in predictions.columns:
        validation[column] = predictions[column]
    _add_calibrated_selection_score(validation, validation)
    policy, diagnostics = _derive_precision_policy(
        validation, spec, market_filter=market_filter
    )
    if not diagnostics.get("validation_policy_robust", False):
        raise ValueError("最新独立验证区间没有稳健正期望策略，拒绝发布")
    diagnostics.update(
        {
            "fit_rows": int(len(fit_rows)),
            "fit_start": str(fit_rows["date"].min())[:10],
            "fit_end": str(fit_rows["date"].max())[:10],
            "validation_rows": int(len(validation)),
            "validation_start": str(validation["date"].min())[:10],
            "validation_end": str(validation["date"].max())[:10],
            "embargoed_date": str(pd.Timestamp(dates[-1]))[:10],
        }
    )
    return model, policy, diagnostics, fit_rows


def run_walk_forward(
    dataset: pd.DataFrame,
    spec: StrategySpec = DEFAULT_SPEC,
    *,
    train_months: int = 12,
    test_months: int = 3,
    embargo_trading_days: int = 1,
    model_kind: str = "auto",
    minimum_predicted_return: float = 0.0,
    market_filter: bool = True,
    max_train_rows: int = 500_000,
    optimize_precision: bool = True,
    validation_fraction: float = 0.20,
    frozen_policies: Optional[Dict[str, SelectionPolicy]] = None,
):
    data = dataset.copy()
    data["date"] = pd.to_datetime(data["date"], errors="coerce").dt.normalize()
    data = data.dropna(subset=["date", "net_return"])
    if "eligible_entry" in data.columns:
        data = data[data["eligible_entry"] == 1]
    if "valid_label" in data.columns:
        data = data[data["valid_label"] == 1]
    data = data.sort_values(["date", "code"])
    unique_dates = pd.Index(sorted(data["date"].unique()))
    if len(unique_dates) < 60:
        raise ValueError("not enough dated observations for walk-forward validation")

    first_test = pd.Timestamp(unique_dates.min()) + pd.DateOffset(months=train_months)
    last_date = pd.Timestamp(unique_dates.max())
    window_start = first_test
    window_number = 0
    all_scored = []
    all_trades = []
    all_daily = []
    window_rows = []
    importance_rows = []
    rolling_capital = float(spec.initial_capital)

    while window_start <= last_date:
        test_end = window_start + pd.DateOffset(months=test_months)
        test = data[(data["date"] >= window_start) & (data["date"] < test_end)].copy()
        if test["date"].nunique() < 20:
            window_start = test_end
            continue

        earlier_dates = unique_dates[unique_dates < np.datetime64(window_start)]
        if len(earlier_dates) <= embargo_trading_days:
            window_start = test_end
            continue
        train_last_date = pd.Timestamp(earlier_dates[-(embargo_trading_days + 1)])
        train_start = window_start - pd.DateOffset(months=train_months)
        train = data[(data["date"] >= train_start) & (data["date"] <= train_last_date)].copy()
        if train["date"].nunique() < 60 or len(train) < 500:
            window_start = test_end
            continue

        train_dates = pd.Index(sorted(train["date"].unique()))
        validation_days = max(20, int(len(train_dates) * validation_fraction))
        validation_days = min(validation_days, max(20, len(train_dates) // 3))
        validation_start = pd.Timestamp(train_dates[-validation_days])
        inner_train = train[train["date"] < validation_start].copy()
        validation = train[train["date"] >= validation_start].copy()
        if inner_train["date"].nunique() < 60 or len(inner_train) < 500:
            inner_train = train.copy()
            validation = pd.DataFrame(columns=train.columns)

        train_fit = _sample_training_rows(inner_train, max_train_rows)
        model = create_model(FEATURE_COLUMNS, kind=model_kind)
        model.fit(train_fit)

        policy = SelectionPolicy(
            max_positions=1,
            minimum_predicted_return=minimum_predicted_return,
            score_column="predicted_return",
        )
        policy_validation = {
            "validation_policy_robust": False,
            "validation_trades": 0,
            "validation_win_rate": 0.0,
            "validation_average_net_return": 0.0,
            "validation_profit_factor": 0.0,
        }
        policy_key = str(test["date"].min())[:10]
        frozen_policy = (frozen_policies or {}).get(policy_key)
        if optimize_precision and not validation.empty:
            validation_predictions = model.predict(validation)
            for column in validation_predictions.columns:
                validation[column] = validation_predictions[column]
            _add_calibrated_selection_score(validation, validation)
            if frozen_policy is None:
                learned_policy, policy_validation = _derive_precision_policy(
                    validation, spec, market_filter=market_filter
                )
                learned_minimum = learned_policy.minimum_predicted_return
                if learned_minimum is None:
                    learned_minimum = minimum_predicted_return
                policy = SelectionPolicy(
                    max_positions=1,
                    minimum_predicted_return=max(
                        float(minimum_predicted_return), float(learned_minimum)
                    ),
                    minimum_positive_probability=(
                        learned_policy.minimum_positive_probability
                    ),
                    maximum_large_loss_probability=(
                        learned_policy.maximum_large_loss_probability
                    ),
                    minimum_regime_score=learned_policy.minimum_regime_score,
                    score_column=learned_policy.score_column,
                )
        if frozen_policy is not None:
            policy = frozen_policy
            policy_validation["policy_frozen_from_normal"] = True
        else:
            policy_validation["policy_frozen_from_normal"] = False

        predictions = model.predict(test)
        for column in predictions.columns:
            test[column] = predictions[column]
        if optimize_precision and not validation.empty:
            _add_calibrated_selection_score(validation, test)
        else:
            test["selection_score"] = test["predicted_return"]
        test["wf_window"] = window_number + 1

        window_number += 1
        window_trades, window_daily, window_metrics = _simulate_selection(
            test,
            spec,
            score_column=policy.score_column,
            minimum_score=policy.minimum_predicted_return,
            market_filter=market_filter,
            initial_capital=rolling_capital,
            policy=policy,
        )
        if not window_trades.empty:
            window_trades["wf_window"] = window_number
            all_trades.append(window_trades)
        if not window_daily.empty:
            window_daily["wf_window"] = window_number
            all_daily.append(window_daily)
            rolling_capital = float(window_daily["end_capital"].iloc[-1])
        window_rows.append(
            {
                "window": window_number,
                "model": model.name,
                "train_start": str(train["date"].min())[:10],
                "train_end": str(train["date"].max())[:10],
                "test_start": str(test["date"].min())[:10],
                "test_end": str(test["date"].max())[:10],
                "train_rows": int(len(train_fit)),
                "validation_start": (
                    str(validation["date"].min())[:10]
                    if not validation.empty
                    else ""
                ),
                "policy_max_positions": policy.max_positions,
                "policy_minimum_predicted_return": policy.minimum_predicted_return,
                "policy_minimum_positive_probability": policy.minimum_positive_probability,
                "policy_maximum_large_loss_probability": policy.maximum_large_loss_probability,
                "policy_minimum_regime_score": policy.minimum_regime_score,
                "policy_score_column": policy.score_column,
                **policy_validation,
                **window_metrics,
            }
        )
        importance = model.feature_importance().copy()
        importance["window"] = window_number
        importance_rows.append(importance)
        all_scored.append(test)
        window_start = test_end

    if not all_scored:
        raise ValueError("no valid walk-forward windows were produced")

    trades = pd.concat(all_trades, ignore_index=True) if all_trades else pd.DataFrame()
    daily = pd.concat(all_daily, ignore_index=True) if all_daily else pd.DataFrame()
    summary = calculate_metrics(trades, daily, spec.initial_capital)
    summary["precision_optimized"] = bool(optimize_precision)
    summary["frozen_policy_windows"] = int(
        sum(bool(row.get("policy_frozen_from_normal")) for row in window_rows)
    )
    summary["outer_scored_rows"] = int(sum(len(frame) for frame in all_scored))
    windows = pd.DataFrame(window_rows)
    if not windows.empty:
        summary["profitable_windows"] = int((windows["cumulative_return"] > 0).sum())
        summary["total_windows"] = int(len(windows))
        summary["window_consistency"] = float(
            (windows["cumulative_return"] > 0).mean()
        )
    importance = (
        pd.concat(importance_rows, ignore_index=True)
        if importance_rows
        else pd.DataFrame()
    )
    return trades, daily, windows, importance, summary
