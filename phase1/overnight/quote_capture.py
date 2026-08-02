"""Resilient, auditable full-market quote collection inside strict windows."""

from __future__ import annotations

import time
from typing import Callable, Iterable, Optional, Tuple

import pandas as pd

from v4.execution import TradingClock


def _normalise(
    frame: Optional[pd.DataFrame],
    expected: set[str],
    action: str,
    *,
    now,
) -> pd.DataFrame:
    if frame is None or frame.empty or "code" not in frame.columns:
        return pd.DataFrame()
    result = frame.copy()
    result["code"] = (
        result["code"].astype(str).str.extract(r"(\d+)", expand=False).str.zfill(6)
    )
    result = result[result["code"].isin(expected)]
    required = {"price", "quote_time"}
    if action == "buy":
        required.update({"ask1", "ask1_volume"})
    elif action == "sell":
        required.update({"bid1", "bid1_volume"})
    if not required.issubset(result.columns):
        return pd.DataFrame()
    result["price"] = pd.to_numeric(result["price"], errors="coerce")
    result = result[result["price"].gt(0)]
    if action in {"buy", "sell"}:
        price_column = "ask1" if action == "buy" else "bid1"
        volume_column = "ask1_volume" if action == "buy" else "bid1_volume"
        result[price_column] = pd.to_numeric(result[price_column], errors="coerce")
        result[volume_column] = pd.to_numeric(result[volume_column], errors="coerce")
        result = result[
            result[price_column].gt(0) & result[volume_column].gt(0)
        ]
    result = result[
        result["quote_time"].map(
            lambda value: TradingClock.quote_is_fresh(value, now=now)
        )
    ]
    return result.drop_duplicates("code", keep="last").reset_index(drop=True)


def fetch_quotes_with_retries(
    fetcher,
    codes: Iterable[str],
    action: str,
    *,
    minimum_coverage: float = 0.95,
    maximum_attempts: int = 3,
    retry_delay_seconds: float = 0.5,
    require_window: bool = True,
    now_fn: Callable = TradingClock.now,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> Tuple[pd.DataFrame, dict]:
    """Retry only missing symbols while the strict action window remains open."""

    expected = {
        str(code).strip().zfill(6) for code in codes if str(code).strip()
    }
    combined = pd.DataFrame()
    attempts = []
    started_at = now_fn()
    for attempt in range(1, max(1, int(maximum_attempts)) + 1):
        current = now_fn()
        status = TradingClock.action_status(action, now=current)
        if require_window and not status.allowed:
            attempts.append(
                {
                    "attempt": attempt,
                    "requested": 0,
                    "received": 0,
                    "reason": status.reason,
                }
            )
            break
        seen = set(combined.get("code", pd.Series(dtype=str)).astype(str))
        requested = sorted(expected - seen)
        if not requested:
            break
        response = _normalise(
            fetcher.batch_fetch_quotes(requested), expected, action, now=current
        )
        if not response.empty:
            combined = _normalise(
                pd.concat([combined, response], ignore_index=True),
                expected,
                action,
                now=current,
            )
        coverage = len(combined) / len(expected) if expected else 0.0
        attempts.append(
            {
                "attempt": attempt,
                "requested": len(requested),
                "received": int(len(response)),
                "cumulative_rows": int(len(combined)),
                "coverage": float(coverage),
            }
        )
        if coverage >= minimum_coverage or attempt >= maximum_attempts:
            break
        if retry_delay_seconds > 0:
            sleep_fn(retry_delay_seconds)

    completed_at = now_fn()
    final_status = TradingClock.action_status(action, now=completed_at)
    coverage = len(combined) / len(expected) if expected else 0.0
    report = {
        "action": action,
        "started_at": started_at.isoformat(timespec="seconds"),
        "completed_at": completed_at.isoformat(timespec="seconds"),
        "expected_codes": len(expected),
        "quote_rows": int(len(combined)),
        "quote_coverage": float(coverage),
        "minimum_coverage": float(minimum_coverage),
        "attempt_count": len(attempts),
        "attempts": attempts,
        "window_allowed_at_end": bool(final_status.allowed),
        "window_required": bool(require_window),
        "window_end_reason": final_status.reason,
    }
    return combined, report
