"""Build auditable 14:50 -> next-session 09:30 execution labels.

Raw quote snapshots are kept separate from model features.  A label is only
usable when both sides are fresh, non-mock, inside their execution windows and
not pinned at the applicable price limit.  An explicit exchange calendar is
required before the result may satisfy the production research gate.
"""

from __future__ import annotations

import json
import hashlib
from pathlib import Path
from typing import Iterable, Optional, Tuple

import pandas as pd

from market_universe import filter_universe_codes
from strategy_spec import DEFAULT_SPEC, StrategySpec, TradeCostModel
from trading_calendar_contract import validate_calendar_records
from .dataset import FEATURE_COLUMNS


CHINA_TZ = "Asia/Shanghai"
CONTRACT_VERSION = "execution-labels-v1"


def _truthy(values: pd.Series) -> pd.Series:
    return values.astype(str).str.strip().str.lower().isin({"1", "true", "yes"})


def _china_timestamp(value):
    try:
        stamp = pd.Timestamp(value)
        if pd.isna(stamp):
            return pd.NaT
        if stamp.tzinfo is None:
            return stamp.tz_localize(CHINA_TZ)
        return stamp.tz_convert(CHINA_TZ)
    except (TypeError, ValueError):
        return pd.NaT


def _clock_seconds(stamp) -> Optional[int]:
    if pd.isna(stamp):
        return None
    return stamp.hour * 3600 + stamp.minute * 60 + stamp.second


def _read_session(root: Path, session: str) -> Tuple[pd.DataFrame, dict]:
    files = sorted((Path(root) / session).glob("*.csv"))
    pieces = []
    raw_rows = 0
    invalid_files = 0
    for path in files:
        try:
            manifest_path = path.with_suffix(path.suffix + ".meta.json")
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            frame = pd.read_csv(path, dtype={"code": str}, low_memory=False)
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            expected_codes = int(manifest.get("expected_codes", 0) or 0)
            coverage = float(manifest.get("coverage", 0.0) or 0.0)
            manifest_valid = bool(
                manifest.get("contract_version")
                in {"strict-execution-snapshot-v2", "strict-execution-snapshot-v3"}
                and manifest.get("evidence_cohort", "strict") == "strict"
                and manifest.get("session") == session
                and manifest.get("data_file") == path.name
                and manifest.get("data_sha256") == digest
                and len(str(manifest.get("expected_universe_sha256", ""))) == 64
                and expected_codes > 0
                and int(manifest.get("valid_rows", -1)) == len(frame)
                and coverage >= 0.95
                and manifest.get("order_book_required") is True
            )
            if not manifest_valid:
                raise ValueError("invalid strict execution manifest")
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            invalid_files += 1
            continue
        raw_rows += len(frame)
        frame["source_file"] = path.name
        frame["snapshot_expected_codes"] = expected_codes
        frame["snapshot_coverage"] = coverage
        frame["snapshot_universe_sha256"] = manifest.get(
            "expected_universe_sha256", ""
        )
        pieces.append(frame)

    stats = {
        "files": len(files),
        "invalid_files": invalid_files,
        "raw_rows": raw_rows,
        "valid_rows": 0,
        "days": 0,
        "duplicate_rows_removed": 0,
        "order_book_rows": 0,
    }
    if not pieces:
        return pd.DataFrame(), stats

    frame = pd.concat(pieces, ignore_index=True)
    required = {"code", "name", "price", "quote_time", "captured_at", "session", "is_mock", "window_valid"}
    if not required.issubset(frame.columns):
        return pd.DataFrame(), stats

    frame["code"] = frame["code"].astype(str).str.extract(r"(\d+)", expand=False).str.zfill(6)
    eligible_codes = set(filter_universe_codes(frame["code"]))
    frame = frame[frame["code"].isin(eligible_codes)].copy()
    frame["price"] = pd.to_numeric(frame["price"], errors="coerce")
    expected_source = "ask1" if session == "buy" else "bid1"
    source = frame.get(
        "execution_price_source", pd.Series("", index=frame.index)
    ).astype(str)
    frame["execution_queue_volume"] = pd.to_numeric(
        frame.get(
            "execution_queue_volume", pd.Series(float("nan"), index=frame.index)
        ),
        errors="coerce",
    )
    frame["order_book_verified"] = (
        source.eq(expected_source) & frame["execution_queue_volume"].gt(0)
    )
    frame["captured_ts"] = frame["captured_at"].map(_china_timestamp)
    frame["quote_ts"] = frame["quote_time"].map(_china_timestamp)
    frame["trade_date"] = frame["captured_ts"].map(
        lambda value: value.date().isoformat() if not pd.isna(value) else ""
    )
    frame["quote_age_seconds"] = [
        (captured - quote).total_seconds()
        if not pd.isna(captured) and not pd.isna(quote)
        else float("inf")
        for captured, quote in zip(frame["captured_ts"], frame["quote_ts"])
    ]

    clock = frame["captured_ts"].map(_clock_seconds)
    if session == "buy":
        start, end, target = 14 * 3600 + 50 * 60, 14 * 3600 + 51 * 60 + 59, 14 * 3600 + 50 * 60
    else:
        start, end, target = 9 * 3600 + 30 * 60, 9 * 3600 + 35 * 60, 9 * 3600 + 30 * 60
    frame["distance_to_target_seconds"] = (clock - target).abs()
    frame["capture_role"] = frame.get(
        "capture_role", pd.Series("strict_probe", index=frame.index)
    ).astype(str)
    # The confirmation push uses its own full-market Level-1 quote frame.  If
    # that audited frame exists, it is the causal execution reference; the
    # scheduled 14:50 probe remains a coverage/research artifact.  The first
    # confirmation is deterministic and cannot be replaced by a later rerun.
    frame["capture_role_priority"] = 1
    if session == "buy":
        frame.loc[
            frame["capture_role"].eq("decision_confirmation"),
            "capture_role_priority",
        ] = 0

    valid = (
        frame["session"].astype(str).eq(session)
        & ~_truthy(frame["is_mock"])
        & _truthy(frame["window_valid"])
        & frame["price"].gt(0)
        & frame["code"].notna()
        & frame["order_book_verified"]
        & frame["quote_age_seconds"].ge(0)
        & frame["quote_age_seconds"].le(30)
        & clock.between(start, end, inclusive="both")
        & frame["captured_ts"].map(lambda value: not pd.isna(value) and value.weekday() < 5)
    )
    if "quote_is_fresh" in frame.columns:
        valid &= _truthy(frame["quote_is_fresh"])
    if "name" in frame.columns:
        valid &= ~frame["name"].astype(str).str.contains("ST|退", na=False)
    frame = frame[valid].copy()
    before = len(frame)
    frame = (
        frame.sort_values(
            [
                "trade_date",
                "code",
                "capture_role_priority",
                "distance_to_target_seconds",
                "captured_ts",
            ]
        )
        .drop_duplicates(["trade_date", "code"], keep="first")
        .reset_index(drop=True)
    )
    stats.update(
        {
            "valid_rows": int(len(frame)),
            "days": int(frame["trade_date"].nunique()) if not frame.empty else 0,
            "duplicate_rows_removed": int(before - len(frame)),
            "order_book_rows": int(frame["order_book_verified"].sum()),
        }
    )
    return frame, stats


def _read_signal(root: Path) -> Tuple[pd.DataFrame, dict]:
    files = sorted((Path(root) / "signal").glob("*.csv"))
    pieces = []
    raw_rows = 0
    invalid_files = 0
    for path in files:
        try:
            manifest_path = path.with_suffix(path.suffix + ".meta.json")
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            frame = pd.read_csv(path, dtype={"code": str}, low_memory=False)
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            expected_codes = int(manifest.get("expected_context_codes", 0) or 0)
            coverage = float(manifest.get("strict_feature_coverage", 0.0) or 0.0)
            manifest_valid = bool(
                manifest.get("contract_version") == "strict-signal-snapshot-v2"
                and manifest.get("data_file") == path.name
                and manifest.get("data_sha256") == digest
                and len(str(manifest.get("expected_universe_sha256", ""))) == 64
                and expected_codes > 0
                and int(manifest.get("strict_feature_rows", -1)) == len(frame)
                and coverage >= 0.95
            )
            if not manifest_valid:
                raise ValueError("invalid strict signal manifest")
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            invalid_files += 1
            continue
        raw_rows += len(frame)
        frame["snapshot_expected_codes"] = expected_codes
        frame["snapshot_coverage"] = coverage
        frame["snapshot_universe_sha256"] = manifest.get(
            "expected_universe_sha256", ""
        )
        pieces.append(frame)
    stats = {
        "files": len(files),
        "invalid_files": invalid_files,
        "raw_rows": raw_rows,
        "valid_rows": 0,
        "days": 0,
        "duplicate_rows_removed": 0,
    }
    if not pieces:
        return pd.DataFrame(), stats
    frame = pd.concat(pieces, ignore_index=True)
    required = {
        "trade_date", "code", "name", "quote_time", "as_of", "session",
        "feature_mode", "window_valid", "quote_is_fresh", "is_mock",
        *FEATURE_COLUMNS,
    }
    if not required.issubset(frame.columns):
        return pd.DataFrame(), stats
    frame["code"] = frame["code"].astype(str).str.extract(r"(\d+)", expand=False).str.zfill(6)
    eligible_codes = set(filter_universe_codes(frame["code"]))
    frame = frame[frame["code"].isin(eligible_codes)].copy()
    frame = frame[~frame["name"].astype(str).str.contains("ST|退", na=False)].copy()
    frame["as_of_ts"] = frame["as_of"].map(_china_timestamp)
    frame["quote_ts"] = frame["quote_time"].map(_china_timestamp)
    frame["quote_age_seconds"] = [
        (captured - quote).total_seconds()
        if not pd.isna(captured) and not pd.isna(quote)
        else float("inf")
        for captured, quote in zip(frame["as_of_ts"], frame["quote_ts"])
    ]
    clock = frame["as_of_ts"].map(_clock_seconds)
    as_of_date = frame["as_of_ts"].map(
        lambda value: value.date().isoformat() if not pd.isna(value) else ""
    )
    numeric = frame[FEATURE_COLUMNS].apply(pd.to_numeric, errors="coerce")
    frame[FEATURE_COLUMNS] = numeric
    valid = (
        frame["session"].astype(str).eq("signal")
        & frame["feature_mode"].astype(str).eq("strict_pre_1450")
        & ~_truthy(frame["is_mock"])
        & _truthy(frame["window_valid"])
        & _truthy(frame["quote_is_fresh"])
        & frame["trade_date"].astype(str).eq(as_of_date)
        & frame["quote_age_seconds"].ge(0)
        & frame["quote_age_seconds"].le(30)
        & clock.between(14 * 3600 + 49 * 60, 14 * 3600 + 49 * 60 + 59)
        & frame[FEATURE_COLUMNS].notna().all(axis=1)
    )
    frame = frame[valid].copy()
    before = len(frame)
    frame = (
        frame.sort_values(["trade_date", "code", "as_of_ts"])
        .drop_duplicates(["trade_date", "code"], keep="last")
        .reset_index(drop=True)
    )
    stats.update(
        {
            "valid_rows": int(len(frame)),
            "days": int(frame["trade_date"].nunique()) if not frame.empty else 0,
            "duplicate_rows_removed": int(before - len(frame)),
        }
    )
    return frame, stats


def _load_calendar(path: Optional[Path], observed_dates: Iterable[str]):
    if path is not None and Path(path).exists():
        frame = pd.read_csv(path)
        verified, sessions, _ = validate_calendar_records(
            frame.to_dict("records"), require_complete_year=True
        )
        dates = sorted(
            pd.to_datetime(
                pd.Series([key for key, is_open in sessions.items() if is_open]),
                errors="coerce",
            ).dropna().dt.date
        )
        return dates, bool(verified), str(Path(path))
    dates = sorted(pd.to_datetime(pd.Series(list(observed_dates)), errors="coerce").dropna().dt.date)
    return dates, False, "observed_snapshot_sessions"


def _next_session_map(open_dates) -> dict:
    return {
        current.isoformat(): following.isoformat()
        for current, following in zip(open_dates, open_dates[1:])
    }


def _price_limit_rate(code: str) -> float:
    return 0.20 if str(code).zfill(6).startswith(("300", "301")) else 0.10


def _cost_labels(frame: pd.DataFrame, spec: StrategySpec) -> pd.DataFrame:
    costs = TradeCostModel(spec)
    budget = spec.position_budget(spec.initial_capital)
    rows = []
    for row in frame.to_dict("records"):
        shares = costs.max_affordable_shares(
            float(row["buy_reference"]), budget, apply_buy_slippage=True
        )
        if shares <= 0:
            continue
        cash = costs.round_trip(
            float(row["buy_reference"]),
            float(row["sell_reference"]),
            shares,
            apply_slippage=True,
        )
        buy_queue = float(row.get("execution_queue_volume_buy", 0) or 0)
        sell_queue = float(row.get("execution_queue_volume_sell", 0) or 0)
        liquidity_verified = buy_queue >= shares and sell_queue >= shares
        row.update(
            {
                "shares_at_100k": shares,
                "buy_fill": cash["buy_fill"],
                "sell_fill": cash["sell_fill"],
                "cash_out": cash["cash_out"],
                "cash_in": cash["cash_in"],
                "total_fees": cash["total_fees"],
                "gross_return": cash["gross_return"],
                "net_return": cash["net_return"],
                "target_1pct": int(cash["net_return"] >= spec.target_net_return),
                "large_loss": int(cash["net_return"] <= spec.large_loss_threshold),
                "order_book_liquidity_verified": bool(liquidity_verified),
                "valid_label": int(
                    bool(row.get("valid_label", False)) and liquidity_verified
                ),
            }
        )
        rows.append(row)
    return pd.DataFrame(rows)


def build_execution_labels(
    snapshot_root: Path,
    spec: StrategySpec = DEFAULT_SPEC,
    *,
    universe_codes: Optional[Iterable[str]] = None,
    calendar_path: Optional[Path] = None,
) -> Tuple[pd.DataFrame, dict]:
    """Pair strict buy/sell snapshots and return labels plus a QA manifest."""

    buy, buy_stats = _read_session(Path(snapshot_root), "buy")
    sell, sell_stats = _read_session(Path(snapshot_root), "sell")
    signal, signal_stats = _read_signal(Path(snapshot_root))
    observed = set(buy.get("trade_date", pd.Series(dtype=str))) | set(
        sell.get("trade_date", pd.Series(dtype=str))
    )
    open_dates, calendar_verified, calendar_source = _load_calendar(
        calendar_path, observed
    )
    next_session = _next_session_map(open_dates)

    universe = set(filter_universe_codes(universe_codes or []))
    expected_universe = int(
        pd.to_numeric(
            buy.get("snapshot_expected_codes", pd.Series(dtype=float)),
            errors="coerce",
        ).max()
        if not buy.empty and "snapshot_expected_codes" in buy.columns
        else len(universe)
    )
    buy_coverage_by_day = (
        buy.groupby("trade_date")["snapshot_coverage"].min()
        if not buy.empty and "snapshot_coverage" in buy.columns
        else pd.Series(dtype=float)
    )

    if buy.empty or sell.empty or not next_session:
        labels = pd.DataFrame()
    else:
        left = buy.copy()
        left["sell_date"] = left["trade_date"].map(next_session)
        left = left.dropna(subset=["sell_date"])
        labels = left.merge(
            sell,
            left_on=["sell_date", "code"],
            right_on=["trade_date", "code"],
            how="inner",
            suffixes=("_buy", "_sell"),
        )
        if not labels.empty:
            signal_columns = [
                "trade_date", "code", "feature_mode", "context_date",
                *FEATURE_COLUMNS,
            ]
            available_signal = signal[
                [column for column in signal_columns if column in signal.columns]
            ].copy()
            if not available_signal.empty:
                available_signal.rename(
                    columns={
                        "trade_date": "signal_date",
                        "feature_mode": "feature_mode_signal",
                    },
                    inplace=True,
                )
                labels = labels.merge(
                    available_signal,
                    left_on=["trade_date_buy", "code"],
                    right_on=["signal_date", "code"],
                    how="left",
                )
            labels["date"] = pd.to_datetime(labels["trade_date_buy"])
            labels["buy_reference"] = labels["price_buy"].astype(float)
            labels["sell_reference"] = labels["price_sell"].astype(float)
            buy_prev = pd.to_numeric(
                labels["prev_close_buy"]
                if "prev_close_buy" in labels.columns
                else pd.Series(float("nan"), index=labels.index),
                errors="coerce",
            )
            sell_prev = pd.to_numeric(
                labels["prev_close_sell"]
                if "prev_close_sell" in labels.columns
                else pd.Series(float("nan"), index=labels.index),
                errors="coerce",
            )
            rates = labels["code"].map(_price_limit_rate)
            labels["buy_fillability_verified"] = (
                buy_prev.notna()
                & buy_prev.gt(0)
                & labels["buy_reference"].lt(buy_prev * (1 + rates - 0.005))
            )
            labels["sell_fillability_verified"] = (
                sell_prev.notna()
                & sell_prev.gt(0)
                & labels["sell_reference"].gt(sell_prev * (1 - rates + 0.005))
            )
            labels["order_book_verified"] = (
                labels.get(
                    "order_book_verified_buy",
                    pd.Series(False, index=labels.index),
                ).fillna(False).astype(bool)
                & labels.get(
                    "order_book_verified_sell",
                    pd.Series(False, index=labels.index),
                ).fillna(False).astype(bool)
            )
            labels["valid_label"] = (
                labels["buy_fillability_verified"]
                & labels["sell_fillability_verified"]
                & labels["order_book_verified"]
            ).astype(int)
            labels["execution_mode"] = "snapshot_14_50"
            labels["exit_mode"] = "snapshot_09_30"
            labels["exit_delay_days"] = 0
            labels["exact_buy"] = True
            labels["exact_sell"] = True
            labels["calendar_verified"] = bool(calendar_verified)
            labels["feature_mode"] = labels.get(
                "feature_mode_signal", pd.Series("missing", index=labels.index)
            ).fillna("missing")
            labels["strict_feature"] = (
                labels["feature_mode"].eq("strict_pre_1450")
                & labels[[column for column in FEATURE_COLUMNS if column in labels.columns]]
                .notna()
                .all(axis=1)
            )
            keep = [
                "date", "sell_date", "code", "name_buy", "buy_reference",
                "sell_reference", "quote_time_buy", "quote_time_sell",
                "captured_at_buy", "captured_at_sell", "execution_mode",
                "capture_role_buy", "capture_role_sell",
                "source_file_buy", "source_file_sell",
                "snapshot_expected_codes_buy", "snapshot_expected_codes_sell",
                "snapshot_coverage_buy", "snapshot_coverage_sell",
                "snapshot_universe_sha256_buy", "snapshot_universe_sha256_sell",
                "exit_mode", "exit_delay_days", "exact_buy", "exact_sell",
                "calendar_verified", "buy_fillability_verified",
                "sell_fillability_verified", "valid_label",
                "order_book_verified", "order_book_verified_buy",
                "order_book_verified_sell", "execution_price_source_buy",
                "execution_price_source_sell", "execution_queue_volume_buy",
                "execution_queue_volume_sell",
                "feature_mode", "context_date", "strict_feature",
                *FEATURE_COLUMNS,
            ]
            labels = _cost_labels(labels[[col for col in keep if col in labels.columns]], spec)

    paired_rows = int(len(labels))
    usable_rows = int(labels["valid_label"].sum()) if not labels.empty else 0
    strict_feature_rows = int(labels["strict_feature"].sum()) if not labels.empty else 0
    order_book_rows = int(labels["order_book_verified"].sum()) if not labels.empty else 0
    liquidity_rows = int(
        labels["order_book_liquidity_verified"].sum()
    ) if not labels.empty else 0
    strict_usable_rows = int(
        (
            labels["valid_label"].eq(1)
            & labels["strict_feature"].fillna(False).astype(bool)
            & labels["calendar_verified"].fillna(False).astype(bool)
            & labels["order_book_verified"].fillna(False).astype(bool)
            & labels["order_book_liquidity_verified"].fillna(False).astype(bool)
        ).sum()
    ) if not labels.empty else 0
    paired_rate = paired_rows / len(buy) if len(buy) else 0.0
    point_in_time_universe_verified = bool(
        paired_rows
        and "snapshot_universe_sha256_buy" in labels.columns
        and "snapshot_universe_sha256_sell" in labels.columns
        and labels["snapshot_universe_sha256_buy"].astype(str).str.len().eq(64).all()
        and labels["snapshot_universe_sha256_sell"].astype(str).str.len().eq(64).all()
    )
    point_in_time_names_verified = bool(paired_rows)
    metadata = {
        "contract_version": CONTRACT_VERSION,
        "snapshot_root": str(Path(snapshot_root)),
        "calendar_source": calendar_source,
        "calendar_verified": bool(calendar_verified),
        "expected_universe_codes": expected_universe,
        "buy": buy_stats,
        "sell": sell_stats,
        "signal": signal_stats,
        "paired_rows": paired_rows,
        "usable_label_rows": usable_rows,
        "strict_usable_rows": strict_usable_rows,
        "unmatched_buy_rows": int(max(0, len(buy) - paired_rows)),
        "paired_buy_rate": float(paired_rate),
        "minimum_buy_universe_coverage": float(buy_coverage_by_day.min())
        if not buy_coverage_by_day.empty
        else 0.0,
        "exact_buy_rate": 1.0 if paired_rows else 0.0,
        "exact_sell_rate": 1.0 if paired_rows else 0.0,
        "proxy_trade_rate": 0.0 if paired_rows else 1.0,
        # Execution labels alone do not prove that model features were frozen
        # before 14:50.  That is a separate mandatory contract.
        "strict_feature_rate": strict_feature_rows / paired_rows if paired_rows else 0.0,
        "order_book_verified_rate": order_book_rows / paired_rows if paired_rows else 0.0,
        "order_book_liquidity_rate": liquidity_rows / paired_rows if paired_rows else 0.0,
        "point_in_time_universe_verified": point_in_time_universe_verified,
        "point_in_time_security_name_verified": point_in_time_names_verified,
        "strict_dataset_ready": bool(
            paired_rows
            and strict_usable_rows > 0
            and calendar_verified
            and paired_rate >= 0.95
            and (float(buy_coverage_by_day.min()) if not buy_coverage_by_day.empty else 0.0) >= 0.95
            and strict_feature_rows / paired_rows >= 0.95
            and order_book_rows / paired_rows >= 0.95
            and point_in_time_universe_verified
            and point_in_time_names_verified
        ),
    }
    return labels, metadata


def save_execution_labels(
    labels: pd.DataFrame, metadata: dict, output: Path
) -> None:
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    labels.to_csv(temporary, index=False, compression="gzip")
    temporary.replace(output)
    meta_path = output.with_suffix(output.suffix + ".meta.json")
    meta_temporary = meta_path.with_suffix(meta_path.suffix + ".tmp")
    with meta_temporary.open("w", encoding="utf-8") as handle:
        json.dump(metadata, handle, ensure_ascii=False, indent=2)
    meta_temporary.replace(meta_path)
