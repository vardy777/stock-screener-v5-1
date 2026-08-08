"""Independent verification of strict capture artifacts and manifests."""

from __future__ import annotations

import json
import hashlib
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from .dataset import FEATURE_COLUMNS


CHINA_TZ = "Asia/Shanghai"


def _truthy(values: pd.Series) -> pd.Series:
    return values.astype(str).str.strip().str.lower().isin({"1", "true", "yes"})


def _safe_float(value, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_int(value, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _in_session_window(values: pd.Series, session: str, trade_date: str) -> bool:
    try:
        expected_date = date.fromisoformat(trade_date)
    except (TypeError, ValueError):
        return False
    parsed = pd.to_datetime(values, errors="coerce", utc=True)
    if parsed.isna().any():
        return False
    local = parsed.dt.tz_convert(CHINA_TZ)
    seconds = local.dt.hour * 3600 + local.dt.minute * 60 + local.dt.second
    windows = {
        "signal": (14 * 3600 + 49 * 60, 14 * 3600 + 49 * 60 + 59),
        "buy": (14 * 3600 + 50 * 60, 14 * 3600 + 51 * 60 + 59),
        "sell": (9 * 3600 + 30 * 60, 9 * 3600 + 35 * 60),
    }
    start, end = windows[session]
    return bool(
        local.dt.date.eq(expected_date).all()
        and seconds.between(start, end).all()
    )


def evaluate_capture_session(root: Path, session: str, trade_date: str) -> dict:
    if session not in {"signal", "buy", "sell"}:
        raise ValueError(f"unsupported capture session: {session}")
    root = Path(root)
    # P1 stores new strict evidence under an explicit cohort directory.  Keep
    # accepting a caller that already points at the cohort root for replaying
    # pre-P1 fixtures and read-only historical archives.
    if (root / "strict").is_dir():
        root = root / "strict"
    files = sorted((root / session).glob(f"{trade_date}_*.csv"))
    candidates = []
    for path in files:
        manifest_path = path.with_suffix(path.suffix + ".meta.json")
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            frame = pd.read_csv(path, dtype={"code": str}, low_memory=False)
        except (OSError, ValueError, TypeError):
            candidates.append(
                {"file": path.name, "passed": False, "reason": "invalid_file_or_manifest"}
            )
            continue
        expected = _safe_int(
            manifest.get("expected_codes")
            or manifest.get("expected_context_codes")
            or 0
        )
        reported_coverage = _safe_float(
            manifest.get("coverage", manifest.get("strict_feature_coverage", 0.0))
        )
        actual_coverage = len(frame) / expected if expected else 0.0
        required = {
            "code", "name", "quote_time",
            "captured_at" if session in {"buy", "sell"} else "as_of",
        }
        schema_ok = required.issubset(frame.columns)
        capture_column = "captured_at" if session in {"buy", "sell"} else "as_of"
        if schema_ok:
            captured = pd.to_datetime(frame[capture_column], errors="coerce", utc=True)
            quoted = pd.to_datetime(frame["quote_time"], errors="coerce", utc=True)
            age = (captured - quoted).dt.total_seconds()
            causal = bool(age.notna().all() and age.between(0, 30).all())
            window_ok = _in_session_window(frame[capture_column], session, trade_date)
        else:
            causal = False
            window_ok = False
        codes = frame.get("code", pd.Series(dtype=str)).astype(str).str.zfill(6)
        codes_ok = bool(
            len(codes) == len(frame)
            and codes.str.fullmatch(r"\d{6}").all()
            and not codes.duplicated().any()
        )
        names_ok = bool(
            "name" in frame.columns
            and frame["name"].astype(str).str.strip().ne("").all()
            and not frame["name"].astype(str).str.contains("ST|退", na=False).any()
        )
        manifest_capture = pd.Series([manifest.get("captured_at")])
        manifest_window_ok = _in_session_window(
            manifest_capture, session, trade_date
        )
        manifest_rows = _safe_int(
            manifest.get("valid_rows")
            or manifest.get("strict_feature_rows")
            or 0
        )
        try:
            artifact_hash = hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError:
            artifact_hash = ""
        artifact_ok = bool(
            manifest.get("data_file") == path.name
            and len(str(manifest.get("data_sha256", ""))) == 64
            and manifest.get("data_sha256") == artifact_hash
            and len(str(manifest.get("expected_universe_sha256", ""))) == 64
        )
        manifest_ok = bool(
            manifest.get("causal_quote_time_required") is True
            and manifest_window_ok
            and manifest_rows == len(frame)
            and artifact_ok
        )
        if session in {"buy", "sell"}:
            expected_source = "ask1" if session == "buy" else "bid1"
            book_ok = bool(
                {
                    "price", "execution_price_source", "execution_queue_volume",
                    "order_book_verified", "session", "window_valid",
                    "quote_is_fresh", "is_mock",
                }
                .issubset(frame.columns)
                and pd.to_numeric(frame["price"], errors="coerce").gt(0).all()
                and frame["execution_price_source"].astype(str).eq(expected_source).all()
                and pd.to_numeric(
                    frame["execution_queue_volume"], errors="coerce"
                ).gt(0).all()
                and _truthy(frame["order_book_verified"]).all()
                and frame["session"].astype(str).eq(session).all()
                and _truthy(frame["window_valid"]).all()
                and _truthy(frame["quote_is_fresh"]).all()
                and (~_truthy(frame["is_mock"])).all()
                and manifest.get("contract_version")
                in {"strict-execution-snapshot-v2", "strict-execution-snapshot-v3"}
                and manifest.get("session") == session
                and manifest.get("order_book_required") is True
                and _safe_int(manifest.get("order_book_verified_rows", 0))
                == len(frame)
            )
        else:
            book_ok = True
            feature_values = frame.reindex(columns=FEATURE_COLUMNS).apply(
                pd.to_numeric, errors="coerce"
            )
            schema_ok = schema_ok and bool(
                {
                    "trade_date", "session", "feature_mode", "window_valid",
                    "quote_is_fresh", "is_mock", *FEATURE_COLUMNS,
                }
                .issubset(frame.columns)
                and frame["trade_date"].astype(str).eq(trade_date).all()
                and frame["session"].astype(str).eq("signal").all()
                and frame["feature_mode"].astype(str).eq("strict_pre_1450").all()
                and _truthy(frame["window_valid"]).all()
                and _truthy(frame["quote_is_fresh"]).all()
                and (~_truthy(frame["is_mock"])).all()
                and np.isfinite(feature_values.to_numpy(dtype=float)).all()
                and manifest.get("contract_version")
                == "strict-signal-snapshot-v2"
            )
        coverage = min(reported_coverage, actual_coverage)
        passed = bool(
            len(frame) > 0
            and schema_ok
            and causal
            and window_ok
            and codes_ok
            and names_ok
            and manifest_ok
            and book_ok
            and coverage >= 0.95
        )
        candidates.append(
            {
                "file": path.name,
                "manifest": manifest_path.name,
                "rows": int(len(frame)),
                "expected": expected,
                "coverage": float(coverage),
                "schema_ok": bool(schema_ok),
                "causal": causal,
                "window_ok": window_ok,
                "codes_ok": codes_ok,
                "names_ok": names_ok,
                "manifest_ok": manifest_ok,
                "artifact_hash_ok": artifact_ok,
                "order_book_ok": book_ok,
                "passed": passed,
            }
        )
    passed_candidates = [item for item in candidates if item.get("passed")]
    best = max(
        passed_candidates or candidates,
        key=lambda item: item.get("coverage", 0.0),
        default={},
    )
    return {
        "session": session,
        "trade_date": trade_date,
        "files_found": len(files),
        "passed": bool(passed_candidates),
        "best": best,
        "candidates": candidates,
    }
