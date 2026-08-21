from datetime import datetime, timedelta

from v5.challenger import (
    STRATEGY_ID,
    challenger_root,
    paper_buy,
    project_confirmation,
    project_morning,
    projection,
    run_isolated,
)
from unittest.mock import patch
from v5.challenger_context import _context_id, save_context
from v5.contracts import AcquisitionSessionV1
from v5.core import CHINA_TZ
from v5.market_snapshot import MarketSnapshotV1, QuoteV1
from v5.market_state import MarketStateV1
from v5.storage import V5FactStore


DAY = "2026-08-21"
MORNING = datetime(2026, 8, 21, 9, 25, 10, tzinfo=CHINA_TZ)
TAIL = datetime(2026, 8, 21, 14, 50, 10, tzinfo=CHINA_TZ)


def _quote(code, price, at, *, high=None, low=9.9):
    return QuoteV1.from_mapping(
        {
            "code": code,
            "name": "挑战样本",
            "trade_date": DAY,
            "exchange_time": at - timedelta(seconds=2),
            "provider_time": at - timedelta(seconds=1),
            "received_at": at,
            "last_price": price,
            "previous_close": 10,
            "open_price": 10,
            "high_price": high or price,
            "low_price": low,
            "bid1": price - 0.01,
            "bid1_volume": 100_000,
            "ask1": price + 0.01,
            "ask1_volume": 100_000,
            "volume": 2_000_000,
            "amount": 20_000_000,
            "halted": False,
            "limit_up": False,
            "limit_down": False,
            "provider": "consensus",
        }
    )


def _snapshot(at, session, prices):
    quotes = [_quote(code, price, at) for code, price in prices.items()]
    return MarketSnapshotV1.build(
        trade_date=DAY,
        session=session,
        batch_started_at=at - timedelta(seconds=1),
        batch_completed_at=at,
        quotes=quotes,
        expected_codes=len(quotes),
    )


def _context(root, codes):
    rows = []
    for code in codes:
        history = []
        for offset in range(22):
            date = (MORNING.date() - timedelta(days=31 - offset)).isoformat()
            history.append({"date": date, "open": 9.8, "close": 10.0, "high": 10.1, "low": 9.7, "volume": 1_000_000})
        rows.append(
            {
                "code": code,
                "context_date": "2026-08-20",
                "context_prev_close": 10.0,
                "ma5": 10.0,
                "ma10": 9.9,
                "ret_5d": 0.04,
                "ret_10d": 0.08,
                "volume_mean_5": 1_100_000,
                "volume_mean_10": 1_000_000,
                "volume_ratio_5_10": 1.1,
                "volatility_10": 0.01,
                "history": history,
                "history_days": 22,
                "provider": "test",
            }
        )
    value = {
        "schema_version": "v5-challenger-context-v1",
        "strategy_id": STRATEGY_ID,
        "target_trade_date": DAY,
        "expected_previous_session": "2026-08-20",
        "provider": "test",
        "captured_at": MORNING.isoformat(),
        "universe_count": len(codes),
        "valid_context_rows": len(codes),
        "coverage": 1.0,
        "reference_comparable": len(codes),
        "reference_comparable_ratio": 1.0,
        "reference_matches": len(codes),
        "reference_match_rate": 1.0,
        "future_rows_discarded": 0,
        "reasons": {"ok": len(codes)},
        "challenger_context_ready": True,
        "research_only": True,
        "strict_sample": False,
        "rows": rows,
    }
    value["context_id"] = _context_id(value)
    save_context(root, value)


def _save_stage(root, snapshot, stage):
    store = V5FactStore(root)
    store.save_snapshot(snapshot)
    state = MarketStateV1.from_snapshot(snapshot)
    store.save_market_state(state)
    if stage == "morning":
        session = AcquisitionSessionV1.build(
            trade_date=DAY,
            stage="morning",
            requested_at=MORNING,
            expected_codes=len(snapshot.quotes),
            selected_snapshot_id=snapshot.snapshot_id,
            accepted=True,
            source_attempts=[{"source": "consensus", "complete": True, "coverage": 1.0}],
        )
        store.save_session(session)
    else:
        pointer = root / "frozen" / DAY / "signal.json"
        pointer.parent.mkdir(parents=True)
        pointer.write_text('{"snapshot_id":"' + snapshot.snapshot_id + '"}', encoding="utf-8")


def test_challenger_confirmation_is_same_day_mother_pool_subset_and_separate_ledger(tmp_path):
    _context(tmp_path, ["000001", "000002"])
    morning = _snapshot(MORNING, "morning", {"000001": 10.2, "000002": 10.3})
    _save_stage(tmp_path, morning, "morning")
    pool = project_morning(tmp_path, MORNING)
    tail = _snapshot(TAIL, "signal", {"000001": 10.4, "000002": 10.35})
    _save_stage(tmp_path, tail, "signal")
    confirmation = project_confirmation(tmp_path, TAIL)
    assert {row["code"] for row in confirmation["candidates"]} <= {row["code"] for row in pool["candidates"]}
    assert confirmation["morning_pool_id"] == pool["pool_id"]
    event = paper_buy(tmp_path, TAIL)
    assert event["outcome"] == "FILLED"
    assert (challenger_root(tmp_path) / "paper").exists()
    assert not (tmp_path / "paper").exists()
    view = projection(tmp_path, DAY)
    assert view["mode"] == "shadow_no_push" and view["account"]["positions"]


def test_challenger_failure_is_recorded_without_raising(tmp_path):
    record = run_isolated(tmp_path, "morning_pool", MORNING, lambda: (_ for _ in ()).throw(RuntimeError("context unavailable")))
    assert record["outcome"] == "FAILED"
    assert record["details"]["error_type"] == "RuntimeError"


def test_challenger_record_storage_failure_never_escapes_to_baseline(tmp_path):
    with patch("v5.challenger.record_run", side_effect=OSError("disk unavailable")):
        record = run_isolated(tmp_path, "morning_pool", MORNING, lambda: {"ok": True})
    assert record["outcome"] == "FAILED" and record["details"]["record_persisted"] is False
