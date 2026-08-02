"""Prepare and capture the strict feature vector frozen before 14:50."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional, Tuple

import numpy as np
import pandas as pd

from .dataset import FEATURE_COLUMNS, is_eligible_code


CHINA_TZ = "Asia/Shanghai"
CONTEXT_VERSION = "live-feature-context-v1"


def _stamp(value):
    try:
        parsed = pd.Timestamp(value)
        if pd.isna(parsed):
            return pd.NaT
        if parsed.tzinfo is None:
            return parsed.tz_localize(CHINA_TZ)
        return parsed.tz_convert(CHINA_TZ)
    except (TypeError, ValueError):
        return pd.NaT


def build_symbol_context(path: Path, expected_previous_session: str) -> Tuple[dict, str]:
    code = path.stem.zfill(6)
    if not is_eligible_code(code):
        return {}, "ineligible"
    try:
        raw = pd.read_csv(path)
    except Exception:
        return {}, "invalid_file"
    required = {"date", "open", "high", "low", "close", "volume"}
    if not required.issubset(raw.columns):
        return {}, "invalid_schema"
    raw = raw.copy()
    raw["timestamp"] = pd.to_datetime(raw["date"], errors="coerce")
    for column in ("open", "high", "low", "close", "volume"):
        raw[column] = pd.to_numeric(raw[column], errors="coerce")
    raw = raw.dropna(subset=["timestamp", "open", "close", "volume"])
    raw = raw[(raw["open"] > 0) & (raw["close"] > 0)].sort_values("timestamp")
    if raw.empty:
        return {}, "empty"
    raw["trade_date"] = raw["timestamp"].dt.normalize()
    daily = raw.groupby("trade_date", sort=True).agg(
        day_open=("open", "first"),
        day_close=("close", "last"),
        day_volume=("volume", "sum"),
        last_timestamp=("timestamp", "max"),
    )
    # Only a day whose archive reaches 15:00 may seed the next session.
    daily = daily[daily["last_timestamp"].dt.time >= pd.Timestamp("15:00").time()]
    expected = pd.Timestamp(expected_previous_session).normalize()
    daily = daily[daily.index <= expected]
    if daily.empty or daily.index.max() != expected:
        return {}, "stale_previous_session"
    if len(daily) < 22:
        return {}, "insufficient_history"

    close = daily["day_close"].astype(float)
    volume = daily["day_volume"].astype(float)
    overnight = daily["day_open"].astype(float) / close.shift(1) - 1.0
    returns = close.pct_change(fill_method=None)
    current = float(close.iloc[-1])
    result = {
        "code": code,
        "context_date": expected.date().isoformat(),
        "context_prev_close": current,
        "volume_mean_20": float(volume.iloc[-20:].mean()),
        "ma5_base": float(close.iloc[-5:].mean()),
        "ma10_base": float(close.iloc[-10:].mean()),
        "ma20_base": float(close.iloc[-20:].mean()),
        "ret_1d": current / float(close.iloc[-2]) - 1.0,
        "ret_3d": current / float(close.iloc[-4]) - 1.0,
        "ret_5d": current / float(close.iloc[-6]) - 1.0,
        "ret_10d": current / float(close.iloc[-11]) - 1.0,
        "ret_20d": current / float(close.iloc[-21]) - 1.0,
        "volatility_20": float(returns.iloc[-20:].std(ddof=0)),
        "overnight_mean_20": float(overnight.dropna().iloc[-20:].mean()),
        "overnight_hit_1pct_20": float(
            (overnight.dropna().iloc[-20:] >= 0.01).mean()
        ),
        "history_days": int(len(daily)),
    }
    if not all(np.isfinite(value) for key, value in result.items() if key not in {"code", "context_date"}):
        return {}, "non_finite"
    return result, "ok"


def build_live_feature_context(
    daily_dir: Path,
    expected_previous_session: str,
    *,
    max_stocks: Optional[int] = None,
    progress_every: int = 250,
) -> Tuple[pd.DataFrame, dict]:
    daily_dir = Path(daily_dir)
    volume_contract_path = daily_dir / ".volume_unit_contract.json"
    try:
        volume_contract = json.loads(
            volume_contract_path.read_text(encoding="utf-8")
        )
    except (OSError, ValueError, TypeError):
        volume_contract = {}
    volume_unit_verified = bool(
        volume_contract.get("complete")
        and volume_contract.get("volume_unit") == "shares"
    )
    paths = [
        path
        for path in sorted(daily_dir.glob("*.csv"))
        if is_eligible_code(path.stem)
    ]
    if max_stocks is not None:
        paths = paths[: max(0, int(max_stocks))]
    rows = []
    reasons = {}
    for index, path in enumerate(paths, start=1):
        row, reason = build_symbol_context(path, expected_previous_session)
        reasons[reason] = reasons.get(reason, 0) + 1
        if row:
            rows.append(row)
        if progress_every and index % progress_every == 0:
            print(f"  feature context: {index}/{len(paths)} files")
    context = pd.DataFrame(rows)
    coverage = len(context) / len(paths) if paths else 0.0
    metadata = {
        "context_version": CONTEXT_VERSION,
        "expected_previous_session": expected_previous_session,
        "files_considered": len(paths),
        "valid_context_rows": int(len(context)),
        "coverage": float(coverage),
        "reasons": reasons,
        "volume_unit": volume_contract.get("volume_unit", "unknown"),
        "volume_unit_verified": volume_unit_verified,
        "strict_context_ready": bool(
            paths and coverage >= 0.95 and volume_unit_verified
        ),
    }
    return context, metadata


def save_live_feature_context(context: pd.DataFrame, metadata: dict, output: Path) -> None:
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    context.to_csv(temporary, index=False, compression="gzip")
    temporary.replace(output)
    meta = output.with_suffix(output.suffix + ".meta.json")
    meta_temporary = meta.with_suffix(meta.suffix + ".tmp")
    with meta_temporary.open("w", encoding="utf-8") as handle:
        json.dump(metadata, handle, ensure_ascii=False, indent=2)
    meta_temporary.replace(meta)


def compute_live_features(
    quotes: pd.DataFrame,
    context: pd.DataFrame,
    *,
    as_of,
) -> pd.DataFrame:
    """Join fresh 14:49 quotes with the previous-session feature context."""

    if quotes is None or quotes.empty or context is None or context.empty:
        return pd.DataFrame()
    current = _stamp(as_of)
    if pd.isna(current) or not (
        current.hour == 14 and current.minute == 49 and current.second <= 59
    ):
        return pd.DataFrame()
    required = {"code", "price", "prev_close", "open", "high", "low", "volume", "quote_time"}
    if not required.issubset(quotes.columns):
        return pd.DataFrame()
    live = quotes.copy()
    live["code"] = live["code"].astype(str).str.zfill(6)
    for column in ("price", "prev_close", "open", "high", "low", "volume"):
        live[column] = pd.to_numeric(live[column], errors="coerce")
    live["quote_ts"] = live["quote_time"].map(_stamp)
    live["quote_age_seconds"] = live["quote_ts"].map(
        lambda value: (current - value).total_seconds()
        if not pd.isna(value)
        else float("inf")
    )
    live = live[
        live["price"].gt(0)
        & live["prev_close"].gt(0)
        & live["quote_age_seconds"].ge(0)
        & live["quote_age_seconds"].le(30)
    ].copy()
    merged = live.merge(context, on="code", how="inner")
    if merged.empty:
        return merged
    # A mismatch indicates stale context, an adjustment event or a unit/source
    # problem.  Do not silently force the two sources together.
    previous_difference = (
        merged["prev_close"] / merged["context_prev_close"] - 1.0
    ).abs()
    merged = merged[previous_difference <= 0.005].copy()
    merged["signal_return"] = merged["price"] / merged["prev_close"] - 1.0
    merged["gap_return"] = merged["open"] / merged["prev_close"] - 1.0
    merged["signal_range"] = (merged["high"] - merged["low"]) / merged["prev_close"]
    span = merged["high"] - merged["low"]
    merged["signal_close_position"] = np.where(
        span > 0, (merged["price"] - merged["low"]) / span, 0.5
    )
    merged["volume_ratio_20"] = merged["volume"] / (merged["volume_mean_20"] * 0.75)
    for days in (5, 10, 20):
        merged[f"price_to_ma{days}"] = merged["price"] / merged[f"ma{days}_base"] - 1.0
    merged["market_mean_signal_return"] = float(merged["signal_return"].mean())
    merged["market_breadth"] = float((merged["signal_return"] > 0).mean())
    merged["market_mean_gap"] = float(merged["gap_return"].mean())
    merged["as_of"] = current.isoformat()
    merged["trade_date"] = current.date().isoformat()
    merged["session"] = "signal"
    merged["feature_mode"] = "strict_pre_1450"
    merged["window_valid"] = True
    merged["quote_is_fresh"] = True
    merged["is_mock"] = False
    merged = merged.replace([np.inf, -np.inf], np.nan).dropna(subset=FEATURE_COLUMNS)
    columns = [
        "trade_date", "code", "name", "quote_time", "as_of", "session",
        "feature_mode", "context_date", "window_valid", "quote_is_fresh",
        "is_mock", *FEATURE_COLUMNS,
    ]
    return merged[[column for column in columns if column in merged.columns]].copy()


def save_signal_features(
    frame: pd.DataFrame, output: Path, metadata: Optional[dict] = None
) -> None:
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    frame.to_csv(temporary, index=False)
    temporary.replace(output)
    if metadata is not None:
        manifest = output.with_suffix(output.suffix + ".meta.json")
        manifest_temporary = manifest.with_suffix(manifest.suffix + ".tmp")
        manifest_temporary.write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        manifest_temporary.replace(manifest)
