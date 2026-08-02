"""Build a point-in-time dataset for the 14:50 -> next-open strategy.

The existing archive contains 60-minute bars labelled by bar end time. It
cannot reproduce a 14:50 fill exactly. For those files we use only bars known
by 14:49:59 to create features and use the 15:00 close as an explicitly marked
execution proxy. A future minute-bar archive is detected automatically and
uses the first 14:50-14:51 bar instead.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import time
from pathlib import Path
from typing import Iterable, Optional, Tuple

import numpy as np
import pandas as pd

from strategy_spec import DEFAULT_SPEC, StrategySpec


FEATURE_COLUMNS = [
    "signal_return",
    "gap_return",
    "signal_range",
    "signal_close_position",
    "volume_ratio_20",
    "ret_1d",
    "ret_3d",
    "ret_5d",
    "ret_10d",
    "ret_20d",
    "price_to_ma5",
    "price_to_ma10",
    "price_to_ma20",
    "volatility_20",
    "overnight_mean_20",
    "overnight_hit_1pct_20",
    "market_mean_signal_return",
    "market_breadth",
    "market_mean_gap",
]

SIGNAL_CUTOFF = time(14, 49, 59)
PRECISE_BUY_START = time(14, 50, 0)
PRECISE_BUY_END = time(14, 51, 59)


def is_eligible_code(code: str) -> bool:
    code = str(code).zfill(6)
    return not code.startswith(("688", "8", "4"))


def _rolling_ratio(current: pd.Series, history: pd.Series, window: int) -> pd.Series:
    base = history.rolling(window, min_periods=window).mean()
    return current / base - 1.0


def _add_cost_labels(frame: pd.DataFrame, spec: StrategySpec) -> pd.DataFrame:
    """Vectorised all-in cash flows at the configured position cap."""

    result = frame.copy()
    budget = spec.position_budget(spec.initial_capital)
    buy_fill = result["buy_reference"].astype(float) * (1.0 + spec.buy_slippage_rate)
    sell_fill = result["sell_reference"].astype(float) * (1.0 - spec.sell_slippage_rate)

    shares = (
        np.floor(budget / (buy_fill * spec.lot_size)) * spec.lot_size
    ).fillna(0).astype(int)

    # One board lot is enough to cover fees in almost all cases, but iterate
    # until every all-in purchase respects the one-third position cap.
    for _ in range(4):
        buy_notional = buy_fill * shares
        buy_commission = np.maximum(
            buy_notional * spec.fees.commission_rate,
            np.where(shares > 0, spec.fees.minimum_commission, 0.0),
        )
        buy_transfer = buy_notional * spec.fees.transfer_fee_rate
        cash_out = buy_notional + buy_commission + buy_transfer
        too_large = (shares > 0) & (cash_out > budget + 1e-8)
        if not bool(too_large.any()):
            break
        shares.loc[too_large] -= spec.lot_size

    buy_notional = buy_fill * shares
    sell_notional = sell_fill * shares
    buy_commission = np.maximum(
        buy_notional * spec.fees.commission_rate,
        np.where(shares > 0, spec.fees.minimum_commission, 0.0),
    )
    sell_commission = np.maximum(
        sell_notional * spec.fees.commission_rate,
        np.where(shares > 0, spec.fees.minimum_commission, 0.0),
    )
    buy_transfer = buy_notional * spec.fees.transfer_fee_rate
    sell_transfer = sell_notional * spec.fees.transfer_fee_rate
    stamp_duty = sell_notional * spec.fees.stamp_duty_rate
    cash_out = buy_notional + buy_commission + buy_transfer
    cash_in = sell_notional - sell_commission - sell_transfer - stamp_duty
    pnl = cash_in - cash_out

    result["shares_at_100k"] = shares
    result["buy_fill"] = buy_fill
    result["sell_fill"] = sell_fill
    result["cash_out"] = cash_out
    result["cash_in"] = cash_in
    result["total_fees"] = (
        buy_commission + sell_commission + buy_transfer + sell_transfer + stamp_duty
    )
    result["gross_return"] = sell_fill / buy_fill - 1.0
    result["net_return"] = np.where(shares > 0, pnl / cash_out, np.nan)
    result["target_1pct"] = (result["net_return"] >= spec.target_net_return).astype(int)
    result["large_loss"] = (
        result["net_return"] <= spec.large_loss_threshold
    ).astype(int)
    return result


def _resolve_exit_references(daily: pd.DataFrame, price_limit_rate: float) -> pd.DataFrame:
    """Conservative exit handling for limit-down opens and corporate actions."""

    result = daily.copy()
    opens = result["day_open"].to_numpy(dtype=float)
    highs = result["day_high"].to_numpy(dtype=float)
    closes = result["day_close"].to_numpy(dtype=float)
    count = len(result)
    sell_reference = np.full(count, np.nan)
    exit_mode = np.full(count, "missing_next_day", dtype=object)
    exit_delay_days = np.zeros(count, dtype=int)
    exit_at_lower_limit = np.zeros(count, dtype=int)
    valid_label = np.zeros(count, dtype=int)
    corporate_action_suspected = np.zeros(count, dtype=int)

    for idx in range(count - 1):
        next_idx = idx + 1
        overnight_gap = opens[next_idx] / closes[idx] - 1.0
        # Gaps beyond the applicable daily limit normally indicate an ex-right,
        # listing/resumption event or bad raw data. Those labels require a
        # point-in-time corporate-action calendar and are not treated as trades.
        if abs(overnight_gap) > price_limit_rate + 0.03:
            corporate_action_suspected[idx] = 1
            exit_mode[idx] = "excluded_corporate_action"
            sell_reference[idx] = opens[next_idx]
            continue

        valid_label[idx] = 1
        sell_reference[idx] = opens[next_idx]
        exit_mode[idx] = "next_open_proxy"
        if overnight_gap > -price_limit_rate + 0.005:
            continue

        exit_at_lower_limit[idx] = 1
        # If price traded away from the lower-limit open, exact first-fill data
        # is unavailable; next close is a conservative same-day proxy.
        if highs[next_idx] > opens[next_idx] * 1.002:
            sell_reference[idx] = closes[next_idx]
            exit_mode[idx] = "limit_down_intraday_close_proxy"
            continue

        # One-price limit-down: carry until the first subsequent day that is not
        # locked. This prevents an impossible 09:30 sale from entering results.
        cursor = next_idx + 1
        found = False
        while cursor < count:
            gap = opens[cursor] / closes[cursor - 1] - 1.0
            locked = (
                gap <= -price_limit_rate + 0.005
                and highs[cursor] <= opens[cursor] * 1.002
            )
            if not locked:
                sell_reference[idx] = opens[cursor]
                exit_delay_days[idx] = cursor - next_idx
                exit_mode[idx] = "deferred_open_after_limit_down"
                found = True
                break
            cursor += 1
        if not found:
            sell_reference[idx] = np.nan
            valid_label[idx] = 0
            exit_mode[idx] = "unresolved_limit_down"

    result["sell_reference"] = sell_reference
    result["exit_mode"] = exit_mode
    result["exit_delay_days"] = exit_delay_days
    result["exit_at_lower_limit"] = exit_at_lower_limit
    result["corporate_action_suspected"] = corporate_action_suspected
    result["valid_label"] = valid_label
    return result


def build_symbol_frame(
    path: Path,
    spec: StrategySpec = DEFAULT_SPEC,
    *,
    min_history: int = 20,
) -> pd.DataFrame:
    code = path.stem.zfill(6)
    if not is_eligible_code(code):
        return pd.DataFrame()

    try:
        raw = pd.read_csv(path)
    except Exception:
        return pd.DataFrame()
    required = {"date", "open", "high", "low", "close", "volume"}
    if not required.issubset(raw.columns):
        return pd.DataFrame()

    raw = raw.copy()
    raw["timestamp"] = pd.to_datetime(raw["date"], errors="coerce")
    for col in ("open", "high", "low", "close", "volume"):
        raw[col] = pd.to_numeric(raw[col], errors="coerce")
    raw = raw.dropna(subset=["timestamp", "open", "high", "low", "close"])
    raw = raw[(raw["open"] > 0) & (raw["close"] > 0)].sort_values("timestamp")
    if raw.empty:
        return pd.DataFrame()
    raw["trade_date"] = raw["timestamp"].dt.normalize()
    raw["clock"] = raw["timestamp"].dt.time

    full = raw.groupby("trade_date", sort=True).agg(
        day_open=("open", "first"),
        day_high=("high", "max"),
        day_low=("low", "min"),
        day_close=("close", "last"),
        day_volume=("volume", "sum"),
        bars=("close", "size"),
        last_timestamp=("timestamp", "max"),
    )

    known = raw[raw["clock"] <= SIGNAL_CUTOFF]
    signal = known.groupby("trade_date", sort=True).agg(
        signal_open=("open", "first"),
        signal_high=("high", "max"),
        signal_low=("low", "min"),
        signal_price=("close", "last"),
        signal_volume=("volume", "sum"),
        signal_timestamp=("timestamp", "max"),
    )

    precise = raw[
        (raw["clock"] >= PRECISE_BUY_START) & (raw["clock"] <= PRECISE_BUY_END)
    ]
    precise_buy = precise.groupby("trade_date", sort=True).agg(
        precise_buy_reference=("close", "first"),
        precise_buy_timestamp=("timestamp", "first"),
    )

    daily = full.join(signal, how="left").join(precise_buy, how="left")
    daily["last_clock"] = daily["last_timestamp"].dt.time
    daily = daily[daily["last_clock"] >= PRECISE_BUY_START].copy()
    if daily.empty:
        return pd.DataFrame()

    has_precise = daily["precise_buy_reference"].notna()
    daily["buy_reference"] = daily["precise_buy_reference"].where(
        has_precise, daily["day_close"]
    )
    daily["execution_mode"] = np.where(
        has_precise, "minute_14_50", "close_proxy_15_00"
    )
    daily["feature_mode"] = np.where(
        has_precise, "strict_pre_1450", "hourly_signal_proxy"
    )
    daily["exact_buy"] = has_precise
    daily["proxy_minutes"] = np.where(has_precise, 0, 10)
    price_limit_rate = 0.20 if code.startswith(("300", "301")) else 0.10
    daily = _resolve_exit_references(daily, price_limit_rate)
    daily["exact_sell"] = False
    daily["calendar_verified"] = False
    daily["order_book_verified"] = False
    daily["order_book_liquidity_verified"] = False
    daily["strict_row"] = False

    previous_close = daily["day_close"].shift(1)
    previous_volume = daily["day_volume"].shift(1)
    previous_overnight = daily["day_open"] / previous_close - 1.0

    daily["signal_return"] = daily["signal_price"] / previous_close - 1.0
    daily["gap_return"] = daily["day_open"] / previous_close - 1.0
    daily["signal_range"] = (
        daily["signal_high"] - daily["signal_low"]
    ) / previous_close
    signal_span = daily["signal_high"] - daily["signal_low"]
    daily["signal_close_position"] = np.where(
        signal_span > 0,
        (daily["signal_price"] - daily["signal_low"]) / signal_span,
        0.5,
    )
    daily["volume_ratio_20"] = daily["signal_volume"] / (
        previous_volume.rolling(20, min_periods=20).mean() * 0.75
    )

    for days in (1, 3, 5, 10, 20):
        daily[f"ret_{days}d"] = previous_close / previous_close.shift(days) - 1.0
    for days in (5, 10, 20):
        daily[f"price_to_ma{days}"] = _rolling_ratio(
            daily["signal_price"], previous_close, days
        )
    previous_returns = previous_close.pct_change(fill_method=None)
    daily["volatility_20"] = previous_returns.rolling(
        20, min_periods=20
    ).std(ddof=0)
    daily["overnight_mean_20"] = previous_overnight.shift(1).rolling(
        20, min_periods=20
    ).mean()
    daily["overnight_hit_1pct_20"] = (
        (previous_overnight.shift(1) >= spec.target_net_return)
        .rolling(20, min_periods=20)
        .mean()
    )

    daily["history_days"] = np.arange(len(daily))
    daily["code"] = code
    daily["price_limit_rate"] = price_limit_rate
    # A stock already at its upper price limit is generally not buyable at
    # 14:50. Keeping it would create the classic "buy every limit-up close"
    # backtest illusion. Five-per-cent ST limits require historical name/status
    # data, which the current archive does not contain and is reported as a
    # remaining limitation.
    daily["entry_at_limit"] = (
        daily["signal_return"] >= price_limit_rate - 0.005
    ).astype(int)
    daily["eligible_entry"] = (
        (daily["buy_reference"] >= spec.minimum_stock_price)
        & (daily["buy_reference"] <= spec.maximum_stock_price)
        & (daily["entry_at_limit"] == 0)
    ).astype(int)
    daily.index.name = "date"
    result = daily.reset_index()
    result = result[
        (result["history_days"] >= min_history)
        & result["signal_price"].notna()
        & result["buy_reference"].notna()
        & result["sell_reference"].notna()
    ].copy()
    if result.empty:
        return result
    return _add_cost_labels(result, spec)


def add_market_features(dataset: pd.DataFrame) -> pd.DataFrame:
    result = dataset.copy()
    grouped = result.groupby("date", sort=False)
    result["market_mean_signal_return"] = grouped["signal_return"].transform("mean")
    result["market_breadth"] = grouped["signal_return"].transform(
        lambda values: float((values > 0).mean())
    )
    result["market_mean_gap"] = grouped["gap_return"].transform("mean")
    return result


def merge_execution_labels(
    dataset: pd.DataFrame,
    labels: Optional[pd.DataFrame],
    spec: StrategySpec = DEFAULT_SPEC,
) -> pd.DataFrame:
    """Override proxy prices with audited snapshot labels where keys match.

    The feature contract remains independent: an exact execution pair does not
    make a row strict when its signal features came from the hourly proxy.
    """

    result = dataset.copy()
    if labels is None or labels.empty or result.empty:
        return result
    exact = labels.copy()
    exact["date"] = pd.to_datetime(exact["date"], errors="coerce").dt.normalize()
    exact["code"] = exact["code"].astype(str).str.zfill(6)
    result["date"] = pd.to_datetime(result["date"], errors="coerce").dt.normalize()
    result["code"] = result["code"].astype(str).str.zfill(6)
    columns = [
        "date", "code", "buy_reference", "sell_reference", "execution_mode",
        "exit_mode", "exit_delay_days", "valid_label", "exact_buy",
        "exact_sell", "calendar_verified", "buy_fillability_verified",
        "sell_fillability_verified", "feature_mode", *FEATURE_COLUMNS,
        "order_book_verified", "order_book_liquidity_verified",
    ]
    exact = exact[[column for column in columns if column in exact.columns]]
    merged = result.merge(exact, on=["date", "code"], how="left", suffixes=("", "_snapshot"))
    matched = merged.get("buy_reference_snapshot", pd.Series(index=merged.index, dtype=float)).notna()
    for column in columns[2:]:
        snapshot = f"{column}_snapshot"
        if snapshot not in merged.columns:
            continue
        if column not in merged.columns:
            merged[column] = merged[snapshot]
        else:
            merged.loc[matched, column] = merged.loc[matched, snapshot]
        merged.drop(columns=[snapshot], inplace=True)
    merged["strict_row"] = (
        merged["exact_buy"].fillna(False).astype(bool)
        & merged["exact_sell"].fillna(False).astype(bool)
        & merged["feature_mode"].eq("strict_pre_1450")
        & merged["calendar_verified"].fillna(False).astype(bool)
        & merged["order_book_verified"].fillna(False).astype(bool)
        & merged["order_book_liquidity_verified"].fillna(False).astype(bool)
        & merged["valid_label"].eq(1)
    )
    return _add_cost_labels(merged, spec)


def build_dataset(
    daily_dir: Path,
    spec: StrategySpec = DEFAULT_SPEC,
    *,
    max_stocks: Optional[int] = None,
    codes: Optional[Iterable[str]] = None,
    progress_every: int = 250,
    execution_labels: Optional[pd.DataFrame] = None,
    execution_metadata: Optional[dict] = None,
) -> Tuple[pd.DataFrame, dict]:
    daily_dir = Path(daily_dir)
    try:
        volume_contract = json.loads(
            (daily_dir / ".volume_unit_contract.json").read_text(encoding="utf-8")
        )
    except (OSError, ValueError, TypeError):
        volume_contract = {}
    volume_unit_verified = bool(
        volume_contract.get("complete")
        and volume_contract.get("volume_unit") == "shares"
    )
    paths = sorted(daily_dir.glob("*.csv"))
    if codes is not None:
        wanted = {str(code).zfill(6) for code in codes}
        paths = [path for path in paths if path.stem.zfill(6) in wanted]
    paths = [path for path in paths if is_eligible_code(path.stem)]
    if max_stocks is not None:
        paths = paths[: max(0, int(max_stocks))]

    pieces = []
    failures = 0
    for idx, path in enumerate(paths, start=1):
        frame = build_symbol_frame(path, spec)
        if frame.empty:
            failures += 1
        else:
            pieces.append(frame)
        if progress_every and idx % progress_every == 0:
            print(f"  dataset: {idx}/{len(paths)} files")

    if not pieces:
        return pd.DataFrame(), {
            "files_considered": len(paths),
            "files_loaded": 0,
            "files_empty_or_invalid": failures,
        }

    dataset = pd.concat(pieces, ignore_index=True)
    dataset = merge_execution_labels(dataset, execution_labels, spec)
    dataset = add_market_features(dataset)
    dataset = dataset.sort_values(["date", "code"]).reset_index(drop=True)
    execution_counts = dataset["execution_mode"].value_counts().to_dict()
    metadata = {
        "files_considered": len(paths),
        "files_loaded": len(pieces),
        "files_empty_or_invalid": failures,
        "rows": int(len(dataset)),
        "start_date": str(dataset["date"].min())[:10],
        "end_date": str(dataset["date"].max())[:10],
        "execution_modes": {str(k): int(v) for k, v in execution_counts.items()},
        "strict_1450_rows": int(dataset["exact_buy"].fillna(False).sum()),
        "strict_sell_rows": int(dataset["exact_sell"].fillna(False).sum()),
        "strict_feature_rows": int(dataset["feature_mode"].eq("strict_pre_1450").sum()),
        "strict_rows": int(dataset["strict_row"].fillna(False).sum()),
        "order_book_rows": int(
            dataset["order_book_verified"].fillna(False).astype(bool).sum()
        ),
        "order_book_liquidity_rows": int(
            dataset["order_book_liquidity_verified"].fillna(False).astype(bool).sum()
        ),
        "proxy_rows": int((~dataset["strict_row"].fillna(False).astype(bool)).sum()),
        "eligible_rows": int(dataset["eligible_entry"].sum()),
        "limit_up_entry_rows": int(dataset["entry_at_limit"].sum()),
        "limit_down_exit_rows": int(dataset["exit_at_lower_limit"].sum()),
        "corporate_action_rows_excluded": int(
            dataset["corporate_action_suspected"].sum()
        ),
        "historical_st_status_available": False,
        "strategy_spec": spec.to_dict(),
        "feature_columns": FEATURE_COLUMNS,
        "volume_unit": volume_contract.get("volume_unit", "unknown"),
        "volume_unit_verified": volume_unit_verified,
        "calendar_verified": bool((execution_metadata or {}).get("calendar_verified", False)),
        "minimum_buy_universe_coverage": float(
            (execution_metadata or {}).get("minimum_buy_universe_coverage", 0.0)
        ),
        "strict_dataset_ready": bool(
            len(dataset) > 0
            and volume_unit_verified
            and dataset["strict_row"].fillna(False).all()
        ),
        "execution_label_metadata": execution_metadata or {},
    }
    return dataset, metadata


def save_dataset(dataset: pd.DataFrame, metadata: dict, cache_path: Path) -> None:
    cache_path = Path(cache_path)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = cache_path.with_suffix(cache_path.suffix + ".tmp")
    dataset.to_csv(temporary, index=False, compression="gzip")
    temporary.replace(cache_path)
    metadata_path = cache_path.with_suffix(cache_path.suffix + ".meta.json")
    metadata_temporary = metadata_path.with_suffix(metadata_path.suffix + ".tmp")
    with metadata_temporary.open("w", encoding="utf-8") as handle:
        json.dump(metadata, handle, ensure_ascii=False, indent=2)
    metadata_temporary.replace(metadata_path)


def load_or_build_dataset(
    daily_dir: Path,
    cache_path: Path,
    spec: StrategySpec = DEFAULT_SPEC,
    *,
    rebuild: bool = False,
    max_stocks: Optional[int] = None,
) -> Tuple[pd.DataFrame, dict]:
    cache_path = Path(cache_path)
    metadata_path = cache_path.with_suffix(cache_path.suffix + ".meta.json")
    if cache_path.exists() and not rebuild:
        dataset = pd.read_csv(cache_path, parse_dates=["date"], low_memory=False)
        metadata = {}
        if metadata_path.exists():
            with metadata_path.open("r", encoding="utf-8") as handle:
                metadata = json.load(handle)
        return dataset, metadata

    dataset, metadata = build_dataset(
        Path(daily_dir), spec, max_stocks=max_stocks
    )
    if not dataset.empty:
        save_dataset(dataset, metadata, cache_path)
    return dataset, metadata
