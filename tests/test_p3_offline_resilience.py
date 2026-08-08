import json
import multiprocessing
import os
import tempfile
import time
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from strategy_spec import TradeCostModel
from v4.execution import CHINA_TZ
from v4.p3_account import OfflineExecutionJournal, OfflineOrderJournal, OfflinePaperLedger
from v4.p3_contracts import PaperContractViolation, PaperExecutionResultV1, PaperFillV1, PaperOrderIntentV1
from v4.p3_execution import OfflineExecutionEngine
from v4.p3_migration import LegacyAccountValidator


SNAPSHOT = "ms1-" + "e" * 64


def make_intent(side, code, decision, at, eligible, *, shares=100, price=10.0):
    return PaperOrderIntentV1.build(
        decision_id=decision, side=side, code=code, name="offline",
        trade_date=at.date(), created_at=at, reference_price=price,
        shares=shares, cash_budget=20_000, market_snapshot_id=SNAPSHOT,
        eligible_sell_date=eligible,
    )


def make_fill(order, at, price):
    model = TradeCostModel()
    costs = model.buy_cash_required(price, order.shares) if order.side == "BUY" else model.sell_cash_received(price, order.shares)
    return PaperFillV1.build(order, filled_at=at, fill_price=price, costs=costs)


def concurrent_append(args):
    directory, raw = args
    return OfflinePaperLedger(Path(directory)).append(PaperFillV1.from_mapping(raw))


def crash_at_boundary(stage, directory, raw_order, raw_fill):
    root = Path(directory)
    order = PaperOrderIntentV1.from_mapping(raw_order)
    fill = PaperFillV1.from_mapping(raw_fill)
    if stage == "before_order":
        os._exit(91)
    OfflineOrderJournal(root).append(order)
    if stage == "after_order":
        os._exit(92)
    OfflinePaperLedger(root).append(fill)
    if stage == "after_fill":
        os._exit(93)
    OfflineExecutionJournal(root).append(PaperExecutionResultV1.build(
        intent_id=order.intent_id, recorded_at=fill.filled_at, outcome="FILLED",
        reason_code="FILLED", fill_id=fill.fill_id))
    os._exit(94)


class P3OfflineResilienceTests(unittest.TestCase):
    def test_one_thousand_round_trips_have_exact_cent_cash_chain_and_bounded_runtime(self):
        start = datetime(2026, 1, 1, 14, 50, tzinfo=CHINA_TZ)
        started = time.perf_counter()
        with tempfile.TemporaryDirectory() as directory:
            ledger = OfflinePaperLedger(Path(directory))
            for index in range(1000):
                buy_at = start + timedelta(days=index * 2)
                sell_at = buy_at + timedelta(days=1, hours=-5, minutes=-20)
                decision = "cd-" + f"{index:024x}"
                buy = make_intent("BUY", "000001", decision, buy_at, sell_at.date())
                sell = make_intent("SELL", "000001", decision, sell_at, sell_at.date())
                ledger.append(make_fill(buy, buy_at, 10.0017))
                ledger.append(make_fill(sell, sell_at, 10.0139))
            report = ledger.reconcile()
            payload = json.loads(ledger.path.read_text(encoding="utf-8"))
            ledger_bytes = ledger.path.stat().st_size
        elapsed = time.perf_counter() - started
        self.assertTrue(report["passed"], report)
        self.assertEqual(report["round_trip_count"], 1000)
        self.assertEqual(payload["event_count"], 2000)
        self.assertEqual(report["cash_fen"], round(report["cash"] * 100))
        self.assertLess(elapsed, 180.0)
        self.assertLess(ledger_bytes, 4_000_000)

    def test_three_symbols_interleave_close_and_reopen(self):
        buy_at = datetime(2026, 8, 3, 14, 50, tzinfo=CHINA_TZ)
        sell_at = datetime(2026, 8, 4, 9, 30, tzinfo=CHINA_TZ)
        with tempfile.TemporaryDirectory() as directory:
            ledger = OfflinePaperLedger(Path(directory))
            buys = []
            for index, code in enumerate(("000001", "000002", "000003")):
                decision = "cd-" + str(index + 1) * 24
                order = make_intent("BUY", code, decision, buy_at, sell_at.date())
                buys.append(order); ledger.append(make_fill(order, buy_at, 10 + index))
            for index in (1, 0, 2):
                order = make_intent("SELL", buys[index].code, buys[index].decision_id, sell_at, sell_at.date(), price=10 + index)
                ledger.append(make_fill(order, sell_at, 10.1 + index))
            reopen_at = datetime(2026, 8, 4, 14, 50, tzinfo=CHINA_TZ)
            reopen = make_intent("BUY", "000002", "cd-" + "a" * 24, reopen_at, "2026-08-05")
            ledger.append(make_fill(reopen, reopen_at, 11.2))
            report = ledger.reconcile()
            positions = ledger.snapshot()["positions"]
        self.assertTrue(report["passed"], report)
        self.assertEqual(positions[0]["decision_id"], reopen.decision_id)

    def test_multiprocess_ledger_appends_do_not_lose_updates(self):
        at = datetime(2026, 8, 3, 14, 50, tzinfo=CHINA_TZ)
        with tempfile.TemporaryDirectory() as directory:
            raws = []
            for index in range(3):
                order = make_intent("BUY", f"00000{index + 1}", "cd-" + str(index + 1) * 24, at, "2026-08-04")
                raws.append(make_fill(order, at, 10).to_dict())
            context = multiprocessing.get_context("spawn")
            with context.Pool(3) as pool:
                self.assertEqual(pool.map(concurrent_append, [(directory, row) for row in raws]), [True] * 3)
            ledger = OfflinePaperLedger(Path(directory))
            self.assertEqual(ledger.snapshot()["fill_count"], 3)
            self.assertTrue(ledger.reconcile()["passed"])

    def test_storage_failure_is_persisted_and_reported_retryable(self):
        at = datetime(2026, 8, 3, 14, 50, tzinfo=CHINA_TZ)
        order = make_intent("BUY", "000001", "cd-" + "1" * 24, at, "2026-08-04")
        with tempfile.TemporaryDirectory() as directory:
            ledger = OfflinePaperLedger(Path(directory)); engine = OfflineExecutionEngine(ledger)
            with patch.object(ledger, "append", side_effect=OSError("disk full")):
                result = engine.execute([order], filled_at=at)
            report = engine.recovery_report()
            self.assertEqual(result["results"][0]["reason_code"], "STORAGE_FAILURE")
            self.assertEqual(report["retryable_intent_ids"], [order.intent_id])
            self.assertEqual(len(report["pending_intents"]), 1)
            self.assertEqual(OfflineExecutionJournal(Path(directory)).results()[0]["outcome"], "REJECTED")
            self.assertTrue(engine.retry_pending(filled_at=at)["success"])
            self.assertEqual(engine.recovery_report()["pending_intents"], [])
            self.assertEqual(engine.recovery_report()["status"], "CLEAN")

    def test_fill_commit_survives_execution_receipt_write_failure(self):
        at = datetime(2026, 8, 3, 14, 50, tzinfo=CHINA_TZ)
        order = make_intent("BUY", "000001", "cd-" + "4" * 24, at, "2026-08-04")
        with tempfile.TemporaryDirectory() as directory:
            ledger = OfflinePaperLedger(Path(directory)); engine = OfflineExecutionEngine(ledger)
            with patch.object(engine.execution_journal, "append", side_effect=PermissionError("readonly")):
                result = engine.execute([order], filled_at=at)
            restarted = OfflineExecutionEngine(OfflinePaperLedger(Path(directory)))
            report = restarted.recovery_report()
        self.assertFalse(result["success"])
        self.assertEqual(report["filled_intent_ids"], [order.intent_id])
        self.assertEqual(report["pending_intents"], [])

    def test_order_written_fill_missing_is_visible_after_restart(self):
        at = datetime(2026, 8, 3, 14, 50, tzinfo=CHINA_TZ)
        order = make_intent("BUY", "000001", "cd-" + "2" * 24, at, "2026-08-04")
        with tempfile.TemporaryDirectory() as directory:
            OfflineOrderJournal(Path(directory)).append(order)
            restarted = OfflineExecutionEngine(OfflinePaperLedger(Path(directory)))
            self.assertEqual(restarted.recovery_report()["pending_intents"][0]["intent_id"], order.intent_id)

    def test_forced_process_crash_matrix_recovers_every_commit_boundary(self):
        at = datetime(2026, 8, 3, 14, 50, tzinfo=CHINA_TZ)
        context = multiprocessing.get_context("spawn")
        for index, stage in enumerate(("before_order", "after_order", "after_fill", "after_result")):
            with self.subTest(stage=stage), tempfile.TemporaryDirectory() as directory:
                order = make_intent("BUY", "000001", "cd-" + str(index + 5) * 24, at, "2026-08-04")
                filled = make_fill(order, at, 10.0)
                process = context.Process(target=crash_at_boundary, args=(stage, directory, order.to_dict(), filled.to_dict()))
                process.start(); process.join(15)
                self.assertFalse(process.is_alive())
                engine = OfflineExecutionEngine(OfflinePaperLedger(Path(directory)))
                report = engine.recovery_report()
                if stage == "before_order":
                    self.assertEqual(report["status"], "CLEAN")
                elif stage == "after_order":
                    self.assertEqual(len(report["pending_intents"]), 1)
                    self.assertTrue(engine.retry_pending(filled_at=at)["success"])
                    self.assertEqual(engine.recovery_report()["status"], "CLEAN")
                elif stage == "after_fill":
                    self.assertEqual(report["missing_result_intent_ids"], [order.intent_id])
                    repaired = engine.repair_audit_gaps()
                    self.assertEqual(len(repaired["repaired_result_ids"]), 1)
                    self.assertEqual(repaired["recovery"]["status"], "CLEAN")
                else:
                    self.assertEqual(report["status"], "CLEAN")

    def test_read_only_legacy_validator_never_mutates_or_cuts_over(self):
        payload = {"capital": 89000.0, "initial_capital": 100000.0,
                   "positions": [{"code": "000001", "shares": 1000, "buy_price": 11.0}],
                   "history": [], "daily_pnl": []}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "legacy.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            before = path.read_bytes(); report = LegacyAccountValidator().validate(path)
            self.assertEqual(path.read_bytes(), before)
        self.assertTrue(report["passed"], report)
        self.assertTrue(report["read_only_verified"])
        self.assertFalse(report["migration_performed"])
        self.assertIn("legacy_fee_model_position:0", report["warnings"])

    def test_permission_and_corrupt_journal_fail_closed(self):
        at = datetime(2026, 8, 3, 14, 50, tzinfo=CHINA_TZ)
        order = make_intent("BUY", "000001", "cd-" + "3" * 24, at, "2026-08-04")
        with tempfile.TemporaryDirectory() as directory:
            journal = OfflineOrderJournal(Path(directory))
            with patch("v4.p3_account.atomic_json_write", side_effect=PermissionError("denied")):
                with self.assertRaises(PermissionError):
                    journal.append(order)
            journal.path.write_text("{broken", encoding="utf-8")
            with self.assertRaisesRegex(PaperContractViolation, "invalid JSON"):
                journal.intents()


if __name__ == "__main__":
    unittest.main()
