#!/usr/bin/env python3
"""Capture the full-market feature vector during 14:49:00-14:49:59."""

import json
import hashlib
import sys
from pathlib import Path

import pandas as pd

BASE = Path(__file__).resolve().parent.parent
ROOT = BASE.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(BASE))

from overnight.dataset import FEATURE_COLUMNS
from overnight.live_features import compute_live_features, save_signal_features
from v4.calendar import TradingCalendar
from v4.execution import TradingClock
from v4.feature_store import LiveFeatureStore
from v4.market_gateway import MarketDataGateway
from v4.replay_contracts import FeatureContextV1
from v4.snapshot_frame import snapshot_frame


def main() -> int:
    started_at = TradingClock.now()
    status = TradingClock.action_status("signal", now=started_at)
    if not status.allowed:
        if TradingCalendar().is_open(started_at.date()) is not True:
            print(f"非开放交易日，跳过信号采集: {started_at.date().isoformat()}")
            return 0
        print(f"拒绝采集: {status.reason}")
        return 2
    context_path = BASE / "data" / "overnight" / "live_feature_context.csv.gz"
    metadata_path = context_path.with_suffix(context_path.suffix + ".meta.json")
    if not context_path.exists() or not metadata_path.exists():
        print("拒绝采集: 实时特征上下文不存在")
        return 2
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    previous = TradingCalendar().previous_open(started_at.date())
    if (
        not metadata.get("strict_context_ready", False)
        or previous is None
        or metadata.get("expected_previous_session") != previous.isoformat()
    ):
        print("拒绝采集: 上下文未达到95%覆盖或不是上一交易日")
        return 2
    context = pd.read_csv(context_path, dtype={"code": str})
    snapshot = MarketDataGateway().fetch_snapshot(
        context["code"].tolist(), session="signal", now=started_at,
        minimum_coverage=0.95, require_order_book=False,
    )
    quotes = snapshot_frame(snapshot)
    fetch_report = {
        "gateway": "MarketDataGateway", "snapshot_id": snapshot.snapshot_id,
        "expected_codes": snapshot.quality.expected_codes,
        "quote_rows": len(snapshot.quotes),
        "quote_coverage": snapshot.quality.coverage,
        "minimum_coverage": snapshot.policy.minimum_coverage,
        "attempt_count": 1,
    }
    captured_at = TradingClock.now()
    completed_status = TradingClock.action_status("signal", now=captured_at)
    if not completed_status.allowed:
        print("拒绝发布: 全市场行情抓取完成时已离开14:49严格窗口")
        return 2
    features = compute_live_features(quotes, context, as_of=captured_at)
    coverage = len(features) / len(context) if len(context) else 0.0
    if coverage < 0.95:
        print(f"拒绝发布: 严格实时特征覆盖率仅{coverage*100:.1f}%")
        return 1
    output = (
        BASE / "data" / "execution_snapshots" / "strict" / "signal"
        / f"{captured_at:%Y-%m-%d_%H%M%S}.csv"
    )
    manifest = {
        "contract_version": "strict-signal-snapshot-v2",
        "captured_at": captured_at.isoformat(timespec="seconds"),
        "expected_context_codes": int(len(context)),
        "strict_feature_rows": int(len(features)),
        "strict_feature_coverage": float(coverage),
        "minimum_coverage": 0.95,
        "causal_quote_time_required": True,
        "expected_universe_sha256": hashlib.sha256(
            "\n".join(sorted(context["code"].astype(str).str.zfill(6))).encode("utf-8")
        ).hexdigest(),
        "fetch": fetch_report,
        "input_snapshot_id": snapshot.snapshot_id,
    }
    save_signal_features(features, output, manifest)
    rows = {
        str(row["code"]).zfill(6): {name: row[name] for name in FEATURE_COLUMNS}
        for row in features.to_dict("records")
    }
    LiveFeatureStore.publish(rows, as_of=captured_at)
    replay_context = FeatureContextV1.build(
        trade_date=captured_at.date().isoformat(),
        expected_previous_session=previous.isoformat(),
        feature_as_of=captured_at,
        previous_context=context.to_dict("records"),
        confirmation_features=rows,
        input_snapshot_id=snapshot.snapshot_id,
    )
    replay_context.save(
        ROOT / "v4" / "data" / "replay_context"
        / f"{captured_at.date().isoformat()}.json"
    )
    print(
        f"严格信号特征 {len(features)} 行，覆盖率{coverage*100:.2f}%，"
        f"抓取{fetch_report['attempt_count']}次，已保存: {output}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
