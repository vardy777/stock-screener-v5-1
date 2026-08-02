"""Safely refresh the recent tail of the 60-minute research archive."""

from __future__ import annotations

from pathlib import Path
from typing import Tuple

import pandas as pd


ARCHIVE_COLUMNS = (
    "date", "open", "high", "low", "close", "volume", "amount", "pct_chg"
)


def validate_archive(frame: pd.DataFrame, expected_session: str) -> Tuple[bool, str]:
    """Require a sane schema and a completed 15:00 bar for the target session."""

    if frame is None or frame.empty:
        return False, "empty"
    if not set(ARCHIVE_COLUMNS).issubset(frame.columns):
        return False, "invalid_schema"
    timestamps = pd.to_datetime(frame["date"], errors="coerce")
    if timestamps.isna().any():
        return False, "invalid_timestamp"
    expected = pd.Timestamp(expected_session).normalize()
    expected_rows = timestamps[timestamps.dt.normalize().eq(expected)]
    if expected_rows.empty:
        return False, "missing_expected_session"
    if expected_rows.max().time() < pd.Timestamp("15:00").time():
        return False, "incomplete_expected_session"
    numeric = frame[list(ARCHIVE_COLUMNS[1:6])].apply(pd.to_numeric, errors="coerce")
    if numeric.isna().any().any() or (numeric[["open", "high", "low", "close"]] <= 0).any().any():
        return False, "invalid_prices"
    return True, "ok"


def merge_archive(existing: pd.DataFrame, recent: pd.DataFrame) -> pd.DataFrame:
    """Merge by bar timestamp, preferring the newly fetched, completed record."""

    pieces = [frame for frame in (existing, recent) if frame is not None and not frame.empty]
    if not pieces:
        return pd.DataFrame(columns=ARCHIVE_COLUMNS)
    merged = pd.concat(pieces, ignore_index=True)
    merged["_timestamp"] = pd.to_datetime(merged["date"], errors="coerce")
    merged = (
        merged.dropna(subset=["_timestamp"])
        .drop_duplicates("_timestamp", keep="last")
        .sort_values("_timestamp")
        .drop(columns="_timestamp")
        .reset_index(drop=True)
    )
    return merged


def save_archive_atomic(frame: pd.DataFrame, path: Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    frame.to_csv(temporary, index=False)
    temporary.replace(path)


def detect_volume_unit(values: pd.Series) -> str:
    """Identify the legacy erroneous x100 scale without using price outcomes."""

    numeric = pd.to_numeric(values, errors="coerce").dropna()
    numeric = numeric[numeric > 0]
    if numeric.empty:
        return "unknown"
    rounded = numeric.round().astype("int64")
    multiple_rate = float((rounded % 100 == 0).mean())
    return "legacy_x100" if multiple_rate >= 0.98 else "shares"


def normalise_volume_to_shares(frame: pd.DataFrame) -> Tuple[pd.DataFrame, str]:
    if "volume" not in frame.columns:
        return frame.copy(), "invalid_schema"
    unit = detect_volume_unit(frame["volume"])
    result = frame.copy()
    if unit == "legacy_x100":
        numeric = pd.to_numeric(result["volume"], errors="coerce")
        if numeric.isna().any() or (numeric < 0).any():
            return frame.copy(), "invalid_volume"
        result["volume"] = (numeric / 100.0).round().astype("int64")
        return result, "converted"
    if unit == "shares":
        return result, "already_shares"
    return result, "unknown"
