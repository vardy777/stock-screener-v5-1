"""Fail-closed P6 audits for strict datasets and evaluation reports."""

from __future__ import annotations

import hashlib
import json
import math
from typing import Mapping

import numpy as np
import pandas as pd

from phase1.overnight.dataset import FEATURE_COLUMNS


STRICT_CONTROL_COLUMNS = (
    "date", "code", "strict_row", "exact_buy", "exact_sell", "feature_mode",
    "calendar_verified", "order_book_verified", "order_book_liquidity_verified",
    "net_return",
)


def _digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=False).encode("utf-8")).hexdigest()


def audit_strict_dataset(frame: pd.DataFrame, metadata: Mapping) -> dict:
    reasons: list[str] = []
    missing = [x for x in (*STRICT_CONTROL_COLUMNS, *FEATURE_COLUMNS) if x not in frame.columns]
    if missing:
        reasons.append("MISSING_COLUMNS:" + ",".join(missing))
    if frame.empty:
        reasons.append("EMPTY_DATASET")
    if not missing and not frame.empty:
        dates = pd.to_datetime(frame["date"], errors="coerce")
        if dates.isna().any(): reasons.append("INVALID_DATE")
        if frame.duplicated(["date", "code"]).any(): reasons.append("DUPLICATE_DATE_CODE")
        flags = ("strict_row", "exact_buy", "exact_sell", "calendar_verified",
                 "order_book_verified", "order_book_liquidity_verified")
        for name in flags:
            if not frame[name].fillna(False).astype(bool).all(): reasons.append("NON_STRICT:" + name)
        if not frame["feature_mode"].eq("strict_pre_1450").all(): reasons.append("NON_STRICT:feature_mode")
        numeric = frame[[*FEATURE_COLUMNS, "net_return"]].apply(pd.to_numeric, errors="coerce")
        if not np.isfinite(numeric.to_numpy(dtype=float)).all(): reasons.append("NON_FINITE_VALUES")
    expected_meta = {
        "dataset_mode": "strict", "strict_dataset_ready": True,
        "point_in_time_universe_verified": True,
        "point_in_time_security_name_verified": True,
        "calendar_verified": True, "volume_unit_verified": True,
    }
    for key, expected in expected_meta.items():
        if metadata.get(key) != expected: reasons.append("METADATA_GATE:" + key)
    coverage = metadata.get("minimum_buy_universe_coverage", 0)
    try:
        if float(coverage) < .95: reasons.append("COVERAGE_BELOW_95_PERCENT")
    except (TypeError, ValueError): reasons.append("INVALID_COVERAGE")
    facts = {"rows": int(len(frame)), "dates": int(frame["date"].nunique()) if "date" in frame else 0,
             "codes": int(frame["code"].nunique()) if "code" in frame else 0,
             "metadata_dataset_sha256": str(metadata.get("dataset_sha256", ""))}
    return {"schema_version": "strict-dataset-audit-v1", "passed": not reasons,
            "reasons": reasons, "facts": facts, "audit_id": "sda1-" + _digest({"reasons": reasons, "facts": facts})[:24]}


def audit_walk_forward(normal: Mapping, stress: Mapping) -> dict:
    reasons=[]
    def finite(name, value):
        try: return math.isfinite(float(value))
        except (TypeError, ValueError): reasons.append("INVALID_METRIC:"+name); return False
    trades=int(normal.get("trades",0) or 0)
    if trades < 500: reasons.append("INSUFFICIENT_OOS_TRADES")
    metrics={"win_rate_ci_low_95":.50,"profit_factor":1.20,"window_consistency":.70}
    for name, floor in metrics.items():
        value=normal.get(name)
        if finite(name,value) and float(value) < floor: reasons.append("THRESHOLD_FAILED:"+name)
    drawdown=normal.get("max_drawdown")
    if finite("max_drawdown",drawdown) and float(drawdown) < -.12: reasons.append("THRESHOLD_FAILED:max_drawdown")
    if normal.get("dataset_mode") != "strict" or float(normal.get("proxy_trade_rate",1) or 0) != 0:
        reasons.append("NON_STRICT_NORMAL_REPORT")
    if normal.get("dataset_sha256") != stress.get("dataset_sha256") or not normal.get("dataset_sha256"):
        reasons.append("DATASET_LINEAGE_MISMATCH")
    if not stress.get("stress_policy_frozen"): reasons.append("STRESS_POLICY_NOT_FROZEN")
    if float(stress.get("cumulative_return",-1) or 0) <= 0 or float(stress.get("profit_factor",0) or 0) < 1:
        reasons.append("STRESS_FAILED")
    total=int(stress.get("total_windows",0) or 0); frozen=int(stress.get("frozen_policy_windows",0) or 0)
    if total < 3 or frozen != total: reasons.append("INCOMPLETE_FROZEN_WINDOWS")
    facts={"trades":trades,"windows":total,"dataset_sha256":normal.get("dataset_sha256","")}
    return {"schema_version":"walk-forward-audit-v1","passed":not reasons,"reasons":reasons,
            "facts":facts,"audit_id":"wfa1-"+_digest({"reasons":reasons,"facts":facts})[:24]}
