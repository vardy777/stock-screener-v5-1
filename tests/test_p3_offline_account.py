import tempfile
import unittest
import json
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from datetime import date

from strategy_spec import TradeCostModel
from v4.execution import CHINA_TZ
from v4.p3_account import OfflinePaperLedger
from v4.p3_contracts import (
    PaperContractViolation, PaperFillV1, PaperOrderIntentV1, PaperRoundTripV1,
)
from v4.p3_execution import OfflineExecutionEngine, OfflineIntentFactory
from tests.snapshot_factory import snapshot_from_frame
import pandas as pd


SNAPSHOT = "ms1-" + "a" * 64
DECISION = "cd-" + "b" * 24


def intent(
    side, trade_date, created_at, *, eligible="2026-08-04", shares=1000,
    cash_budget=33_333.33,
):
    return PaperOrderIntentV1.build(
        decision_id=DECISION, side=side, code="000001", name="测试",
        trade_date=trade_date, created_at=created_at, reference_price=10.0,
        shares=shares, cash_budget=cash_budget,
        market_snapshot_id=SNAPSHOT, eligible_sell_date=eligible,
    )


def fill(order, at, price):
    costs = TradeCostModel()
    values = (
        costs.buy_cash_required(price, order.shares)
        if order.side == "BUY"
        else costs.sell_cash_received(price, order.shares)
    )
    return PaperFillV1.build(order, filled_at=at, fill_price=price, costs=values)


class P3OfflineAccountTests(unittest.TestCase):
    def setUp(self):
        self.buy_time = datetime(2026, 8, 3, 14, 50, 20, tzinfo=CHINA_TZ)
        self.sell_time = datetime(2026, 8, 4, 9, 30, 20, tzinfo=CHINA_TZ)

    def test_entities_are_deterministic_and_reject_naive_time(self):
        first = intent("BUY", "2026-08-03", self.buy_time)
        second = intent("BUY", "2026-08-03", self.buy_time)
        self.assertEqual(first, second)
        with self.assertRaisesRegex(PaperContractViolation, "timezone"):
            intent("BUY", "2026-08-03", datetime(2026, 8, 3, 14, 50))

    def test_fill_is_idempotent_and_cash_is_reconciled(self):
        order = intent("BUY", "2026-08-03", self.buy_time)
        bought = fill(order, self.buy_time, 10.0)
        with tempfile.TemporaryDirectory() as directory:
            ledger = OfflinePaperLedger(Path(directory))
            self.assertTrue(ledger.append(bought))
            self.assertFalse(ledger.append(bought))
            snapshot = ledger.snapshot()
        self.assertEqual(snapshot["fill_count"], 1)
        self.assertAlmostEqual(snapshot["cash"], 100_000 + bought.cash_flow, 6)
        self.assertEqual(snapshot["positions"][0]["fill_id"], bought.fill_id)

    def test_round_trip_charges_fees_and_enforces_t_plus_one(self):
        bought = fill(intent("BUY", "2026-08-03", self.buy_time), self.buy_time, 10.0)
        sell_order = intent("SELL", "2026-08-04", self.sell_time)
        sold = fill(sell_order, self.sell_time, 10.2)
        result = PaperRoundTripV1.build(bought, sold)
        self.assertAlmostEqual(result.net_pnl, sold.cash_flow + bought.cash_flow, 6)
        self.assertGreater(result.total_fees, 0)

        early_time = datetime(2026, 8, 3, 14, 51, tzinfo=CHINA_TZ)
        with self.assertRaisesRegex(PaperContractViolation, "sell before"):
            intent("SELL", "2026-08-03", early_time)

    def test_one_third_cap_and_duplicate_decision_are_hard_gates(self):
        oversized = fill(
            intent(
                "BUY", "2026-08-03", self.buy_time, shares=3400,
                cash_budget=40_000,
            ),
            self.buy_time, 10.0,
        )
        with tempfile.TemporaryDirectory() as directory:
            ledger = OfflinePaperLedger(Path(directory))
            with self.assertRaisesRegex(PaperContractViolation, "one-third"):
                ledger.append(oversized)

            valid = fill(intent("BUY", "2026-08-03", self.buy_time), self.buy_time, 10.0)
            ledger.append(valid)
            conflicting = PaperFillV1.build(
                intent("BUY", "2026-08-03", self.buy_time),
                filled_at=self.buy_time, fill_price=10.01,
                costs=TradeCostModel().buy_cash_required(10.01, 1000),
            )
            with self.assertRaisesRegex(PaperContractViolation, "already filled"):
                ledger.append(conflicting)

    def test_fill_cannot_exceed_frozen_intent_budget(self):
        order = intent(
            "BUY", "2026-08-03", self.buy_time, shares=1000,
            cash_budget=9_000,
        )
        with self.assertRaisesRegex(PaperContractViolation, "cash budget"):
            fill(order, self.buy_time, 10.0)

    def test_ledger_rebuilds_same_state_from_append_only_fills(self):
        bought = fill(intent("BUY", "2026-08-03", self.buy_time), self.buy_time, 10.0)
        sold = fill(intent("SELL", "2026-08-04", self.sell_time), self.sell_time, 10.2)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ledger = OfflinePaperLedger(root)
            ledger.append(bought)
            ledger.append(sold)
            first = ledger.snapshot()
            second = OfflinePaperLedger(root).snapshot()
            round_trips = ledger.round_trips()
        self.assertEqual(first, second)
        self.assertEqual(first["positions"], [])
        self.assertEqual(len(round_trips), 1)

    def test_ledger_rejects_tampered_fill_on_reload(self):
        bought = fill(intent("BUY", "2026-08-03", self.buy_time), self.buy_time, 10.0)
        with tempfile.TemporaryDirectory() as directory:
            ledger = OfflinePaperLedger(Path(directory))
            ledger.append(bought)
            row = json.loads(ledger.path.read_text(encoding="utf-8"))
            row["cash_flow"] = -1.0
            ledger.path.write_text(json.dumps(row) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(PaperContractViolation, "content hash"):
                ledger.snapshot()

    def test_atomic_write_failure_preserves_existing_ledger(self):
        bought = fill(intent("BUY", "2026-08-03", self.buy_time), self.buy_time, 10.0)
        sold = fill(intent("SELL", "2026-08-04", self.sell_time), self.sell_time, 10.2)
        with tempfile.TemporaryDirectory() as directory:
            ledger = OfflinePaperLedger(Path(directory))
            ledger.append(bought)
            before = ledger.path.read_bytes()
            with patch.object(Path, "replace", side_effect=OSError("disk failure")):
                with self.assertRaisesRegex(OSError, "disk failure"):
                    ledger.append(sold)
            self.assertEqual(ledger.path.read_bytes(), before)
            self.assertEqual(OfflinePaperLedger(Path(directory)).snapshot()["fill_count"], 1)

    def test_reconciliation_matches_cash_positions_and_round_trips(self):
        bought = fill(intent("BUY", "2026-08-03", self.buy_time), self.buy_time, 10.0)
        sold = fill(intent("SELL", "2026-08-04", self.sell_time), self.sell_time, 10.2)
        with tempfile.TemporaryDirectory() as directory:
            ledger = OfflinePaperLedger(Path(directory))
            ledger.append(bought)
            ledger.append(sold)
            report = ledger.reconcile()
        self.assertTrue(report["passed"], report["checks"])
        self.assertTrue(report["checks"]["flat_pnl_matches_cash"])


class FakeCalendar:
    verified = True

    def __init__(self, next_session):
        self.next_session = next_session

    def next_open(self, day):
        return self.next_session


class P3OfflineExecutionTests(unittest.TestCase):
    def test_buy_intent_uses_verified_next_open_session(self):
        now = datetime(2026, 8, 7, 14, 50, 20, tzinfo=CHINA_TZ)
        snapshot = snapshot_from_frame(pd.DataFrame([{
            "code": "000001", "name": "测试", "price": 10.0,
            "ask1": 10.01, "quote_time": now.isoformat(),
        }]), session="buy")
        decision = {
            "decision_id": DECISION, "outcome": "BUY",
            "candidates": [{
                "code": "000001", "name": "测试", "rank": 1,
                "v4_paper_eligible": True,
            }],
        }
        order = OfflineIntentFactory(
            calendar=FakeCalendar(date(2026, 8, 10))
        ).buy_from_decision(decision, snapshot, created_at=now)
        self.assertEqual(order.eligible_sell_date, "2026-08-10")
        self.assertLessEqual(order.cash_budget, 100_000 / 3 + 0.01)

        with self.assertRaisesRegex(PaperContractViolation, "next session"):
            OfflineIntentFactory(calendar=FakeCalendar(None)).buy_from_decision(
                decision, snapshot, created_at=now
            )
        unverified = FakeCalendar(date(2026, 8, 10))
        unverified.verified = False
        with self.assertRaisesRegex(PaperContractViolation, "verified trading calendar"):
            OfflineIntentFactory(calendar=unverified).buy_from_decision(
                decision, snapshot, created_at=now
            )

    def test_batch_failure_is_isolated_and_success_is_committed(self):
        at = datetime(2026, 8, 3, 14, 50, 20, tzinfo=CHINA_TZ)
        valid = intent("BUY", "2026-08-03", at)
        with tempfile.TemporaryDirectory() as directory:
            ledger = OfflinePaperLedger(Path(directory))
            result = OfflineExecutionEngine(ledger).execute(
                [valid, object()], filled_at=at
            )
            snapshot = ledger.snapshot()
        self.assertFalse(result["success"])
        self.assertEqual(result["filled"], 1)
        self.assertEqual(result["failed"], 1)
        self.assertEqual(snapshot["fill_count"], 1)

    def test_complete_offline_buy_next_session_sell_replay(self):
        buy_at = datetime(2026, 8, 7, 14, 50, 20, tzinfo=CHINA_TZ)
        sell_at = datetime(2026, 8, 10, 9, 30, 20, tzinfo=CHINA_TZ)
        buy_snapshot = snapshot_from_frame(pd.DataFrame([{
            "code": "000001", "name": "测试", "price": 10.0,
            "ask1": 10.01, "quote_time": buy_at.isoformat(),
        }]), session="buy")
        decision = {
            "decision_id": DECISION, "outcome": "BUY",
            "candidates": [{"code": "000001", "name": "测试", "rank": 1,
                            "v4_paper_eligible": True}],
        }
        factory = OfflineIntentFactory(calendar=FakeCalendar(date(2026, 8, 10)))
        buy_order = factory.buy_from_decision(
            decision, buy_snapshot, created_at=buy_at
        )
        sell_snapshot = snapshot_from_frame(pd.DataFrame([{
            "code": "000001", "name": "测试", "price": 10.2,
            "bid1": 10.19, "quote_time": sell_at.isoformat(),
        }]), session="sell")
        with tempfile.TemporaryDirectory() as directory:
            ledger = OfflinePaperLedger(Path(directory))
            engine = OfflineExecutionEngine(ledger)
            self.assertTrue(engine.execute([buy_order], filled_at=buy_at)["success"])
            position = ledger.snapshot()["positions"][0]
            sell_order = factory.sell_from_position(
                position, sell_snapshot, created_at=sell_at
            )
            self.assertTrue(engine.execute([sell_order], filled_at=sell_at)["success"])
            report = ledger.reconcile()
            trips = ledger.round_trips()
        self.assertTrue(report["passed"], report["checks"])
        self.assertEqual(len(trips), 1)
        self.assertEqual(trips[0]["buy_fill_id"].split("-")[0], "pf")


if __name__ == "__main__":
    unittest.main()
