import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from v4.execution import CHINA_TZ
from v4.market_contracts import MarketSnapshotV1, QuoteV1
from v4.market_gateway import SnapshotRepository
from v4.snapshot_replay import replay_frozen_chain


class DeterministicRuntime:
    def __init__(self):
        self.reference_times = []

    @staticmethod
    def _candidate(snapshot, stage):
        score = 80.0 if stage == "morning" else 82.0
        row = {
            "code": "000001", "name": "test", "rank": 1,
            "price": 10.0, "quote_time": snapshot.quotes[0].exchange_time,
            "score": score, "final_score": score,
            "score_version": (
                "v4-causal-rule-rank-v1" if stage == "morning"
                else "v4-base-plus-confirm-delta-v1"
            ),
            "v4_candidate_origin": "V4",
            "selection_stage": (
                "morning_observation" if stage == "morning"
                else "confirmation_1450"
            ),
        }
        if stage == "confirmation":
            row.update(base_score=80.0, confirm_delta=2.0, decision_score=82.0)
        return row

    def evaluate_universe(self, snapshot, *, decision_stage, reference_time, **kwargs):
        self.reference_times.append(reference_time)
        return [self._candidate(snapshot, decision_stage)]

    def evaluate_candidates(
        self, candidates, market_state, *, reference_time=None, **kwargs
    ):
        self.reference_times.append(reference_time)
        return [dict(
            item,
            v4_paper_eligible=True,
            v4_paper_block_reasons=[],
            v4_paper_policy_version="paper-top1-integrity-v1",
        ) for item in candidates]


def make_snapshot(session, completed):
    exchange = completed - timedelta(seconds=1)
    quote = QuoteV1.from_mapping({
        "code": "000001", "name": "test", "trade_date": "2026-08-03",
        "exchange_time": exchange, "provider_time": exchange,
        "received_at": completed, "last_price": 10.0,
        "previous_close": 9.9, "open_price": 9.95, "high_price": 10.1,
        "low_price": 9.9, "bid1": 9.99, "bid1_volume": 100,
        "ask1": 10.01, "ask1_volume": 100, "volume": 1000,
        "amount": 10000.0, "halted": False, "limit_up": False,
        "limit_down": False, "provider": "test",
    })
    return MarketSnapshotV1.build(
        trade_date="2026-08-03", session=session,
        batch_started_at=completed - timedelta(seconds=2),
        batch_completed_at=completed, quotes=[quote], expected_codes=1,
    )


class FrozenSnapshotReplayTests(unittest.TestCase):
    def test_replay_is_snapshot_time_based_and_deterministic(self):
        morning_time = datetime(2026, 8, 3, 9, 25, 10, tzinfo=CHINA_TZ)
        confirmation_time = datetime(2026, 8, 3, 14, 50, 10, tzinfo=CHINA_TZ)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repository = SnapshotRepository(root / "snapshots")
            morning_path = repository.save(make_snapshot("morning", morning_time))
            confirmation_path = repository.save(make_snapshot("buy", confirmation_time))
            runtime1 = DeterministicRuntime()
            first = replay_frozen_chain(
                morning_path, confirmation_path,
                journal_directory=root / "journal-1", runtime=runtime1,
            )
            runtime2 = DeterministicRuntime()
            second = replay_frozen_chain(
                morning_path, confirmation_path,
                journal_directory=root / "journal-2", runtime=runtime2,
            )

        self.assertEqual(first, second)
        self.assertEqual(first["confirmation_decision"]["outcome"], "BUY")
        self.assertTrue(first["execution_projection"]["execute_buy"])
        self.assertEqual(
            first["morning_pool"]["lineage"]["input_snapshot_id"],
            first["morning_snapshot_id"],
        )
        self.assertEqual(
            first["confirmation_decision"]["lineage"]["input_snapshot_id"],
            first["confirmation_snapshot_id"],
        )
        self.assertEqual(runtime1.reference_times, [
            morning_time, confirmation_time, confirmation_time,
        ])

    def test_replay_rejects_wrong_snapshot_sessions(self):
        timestamp = datetime(2026, 8, 3, 9, 25, 10, tzinfo=CHINA_TZ)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repository = SnapshotRepository(root / "snapshots")
            first = repository.save(make_snapshot("morning", timestamp))
            second = repository.save(make_snapshot("signal", timestamp))
            with self.assertRaisesRegex(ValueError, "morning then buy"):
                replay_frozen_chain(
                    first, second, journal_directory=root / "journal",
                    runtime=DeterministicRuntime(),
                )


if __name__ == "__main__":
    unittest.main()
