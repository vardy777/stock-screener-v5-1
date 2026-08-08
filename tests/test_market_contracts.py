import json
import unittest
from datetime import datetime, timedelta

from v4.execution import CHINA_TZ
from v4.market_contracts import (
    ContractViolation,
    EvidenceCohort,
    MarketSnapshotV1,
    MarketStateV1,
    QuoteV1,
)


class MarketContractTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 8, 3, 14, 50, 10, tzinfo=CHINA_TZ)

    def quote(self, **changes):
        row = {
            "code": "000001", "name": "平安银行", "trade_date": "2026-08-03",
            "exchange_time": self.now - timedelta(seconds=2),
            "provider_time": self.now - timedelta(seconds=1),
            "received_at": self.now,
            "last_price": 10.0, "previous_close": 9.9,
            "bid1": 9.99, "bid1_volume": 10000,
            "ask1": 10.01, "ask1_volume": 12000,
            "volume": 123456, "amount": 1234567.0,
            "halted": False, "limit_up": False, "limit_down": False,
            "provider": "sina",
        }
        row.update(changes)
        return QuoteV1.from_mapping(row)

    def test_quote_is_versioned_and_json_serializable(self):
        quote = self.quote()
        payload = quote.to_dict()
        self.assertEqual(payload["schema_version"], "quote-v1")
        json.dumps(payload)

    def test_missing_field_wrong_type_and_naive_datetime_are_rejected(self):
        with self.assertRaisesRegex(ContractViolation, "missing fields"):
            QuoteV1.from_mapping({"code": "000001"})
        with self.assertRaisesRegex(ContractViolation, "boolean is required"):
            self.quote(halted="false")
        with self.assertRaisesRegex(ContractViolation, "timezone is required"):
            self.quote(exchange_time=datetime(2026, 8, 3, 14, 50, 8))

    def test_cross_date_and_noncausal_provider_sequence_are_rejected(self):
        with self.assertRaisesRegex(ContractViolation, "cross trade date"):
            self.quote(trade_date="2026-08-04")
        with self.assertRaisesRegex(ContractViolation, "earlier than exchange"):
            self.quote(provider_time=self.now - timedelta(seconds=3))

    def test_strict_rejects_batch_delay_but_paper_only_marks_degradation(self):
        quote = self.quote()
        args = dict(
            trade_date="2026-08-03", session="buy",
            batch_started_at=self.now - timedelta(seconds=40),
            batch_completed_at=self.now, quotes=[quote], expected_codes=1,
            maximum_batch_seconds=30,
        )
        strict = MarketSnapshotV1.build(**args)
        paper = MarketSnapshotV1.build(**args, cohort=EvidenceCohort.PAPER_ONLY)
        self.assertFalse(strict.quality.accepted)
        self.assertTrue(paper.quality.accepted)
        self.assertIn("batch_delay", paper.quality.reasons)

    def test_missing_book_halt_limit_and_future_quote_fail_closed(self):
        cases = [
            (self.quote(ask1=0, ask1_volume=0), "missing_order_book"),
            (self.quote(halted=True), "halted"),
            (self.quote(limit_up=True), "limit_locked"),
            (self.quote(
                exchange_time=self.now + timedelta(seconds=1),
                provider_time=self.now + timedelta(seconds=1),
                received_at=self.now + timedelta(seconds=1),
            ), "provider_clock_skew"),
        ]
        for quote, reason in cases:
            with self.subTest(reason=reason):
                snapshot = MarketSnapshotV1.build(
                    trade_date="2026-08-03", session="buy",
                    batch_started_at=self.now - timedelta(seconds=1),
                    batch_completed_at=self.now, quotes=[quote], expected_codes=1,
                )
                self.assertFalse(snapshot.quality.accepted)
                self.assertIn(reason, snapshot.quality.reasons)

    def test_duplicate_and_incomplete_coverage_have_explicit_reasons(self):
        snapshot = MarketSnapshotV1.build(
            trade_date="2026-08-03", session="signal",
            batch_started_at=self.now - timedelta(seconds=1),
            batch_completed_at=self.now,
            quotes=[self.quote(), self.quote()], expected_codes=3,
            require_order_book=False,
        )
        self.assertFalse(snapshot.quality.accepted)
        self.assertEqual(snapshot.quality.valid_codes, 1)
        self.assertIn("duplicate_code", snapshot.quality.reasons)
        self.assertIn("incomplete_coverage", snapshot.quality.reasons)

    def test_snapshot_and_market_state_have_deterministic_lineage_ids(self):
        snapshot = MarketSnapshotV1.build(
            trade_date="2026-08-03", session="morning",
            batch_started_at=self.now - timedelta(seconds=1),
            batch_completed_at=self.now, quotes=[self.quote()], expected_codes=1,
            require_order_book=False,
        )
        self.assertTrue(snapshot.snapshot_id.startswith("ms1-"))
        self.assertEqual(snapshot.snapshot_id, snapshot.snapshot_id)
        state = MarketStateV1.build(
            snapshot, mode="neutral", data_valid=True,
            metrics={"advance_ratio": 0.5}, analytics_version="test-v1",
        )
        self.assertEqual(state.snapshot_id, snapshot.snapshot_id)
        self.assertTrue(state.market_state_id.startswith("mstate1-"))

    def test_action_clock_never_assumes_timezone_for_naive_values(self):
        from v4.execution import TradingClock
        naive = datetime(2026, 8, 3, 14, 50, 0)
        with self.assertRaisesRegex(ValueError, "timezone-aware"):
            TradingClock.action_status("buy", now=naive)
        self.assertFalse(TradingClock.quote_is_fresh(naive, now=self.now))
        self.assertFalse(TradingClock.quote_is_fresh(self.now, now=naive))

    def test_market_state_metrics_are_deeply_immutable(self):
        snapshot = MarketSnapshotV1.build(
            trade_date="2026-08-03", session="morning",
            batch_started_at=self.now, batch_completed_at=self.now,
            quotes=[self.quote()], expected_codes=1, require_order_book=False,
        )
        state = MarketStateV1.build(
            snapshot, mode="neutral", data_valid=True,
            metrics={"nested": {"items": [1, 2]}}, analytics_version="test-v1",
        )
        with self.assertRaises(TypeError):
            state.metrics["nested"]["items"] = []
        with self.assertRaises(TypeError):
            state.metrics["nested"]["new"] = 1


if __name__ == "__main__":
    unittest.main()
