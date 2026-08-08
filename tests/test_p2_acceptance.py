import json
import tempfile
import unittest
from pathlib import Path

from v4.p2_acceptance import validate_p2_session


class P2AcceptanceTests(unittest.TestCase):
    def test_acceptance_requires_same_ids_in_entities_consumers_and_logs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            journal_dir = root / "journal"
            log_dir = root / "logs"
            journal_dir.mkdir()
            log_dir.mkdir()
            chain = {
                "trade_date": "2026-08-10",
                "morning": {
                    "schema_version": "morning-pool-v1", "pool_id": "mp-abc",
                    "candidate_codes": ["000001"], "candidates": [],
                },
                "confirmation": {
                    "schema_version": "confirmation-decision-v1",
                    "decision_id": "cd-abc", "morning_pool_id": "mp-abc",
                    "candidate_codes": ["000001"], "outcome": "BUY",
                    "reason_codes": ["eligible_top1"],
                    "candidates": [{
                        "code": "000001", "linkage_status": "confirmed_from_morning_pool",
                        "v4_paper_eligible": True, "v4_paper_block_reasons": [],
                        "v4_paper_policy_version": "paper-top1-integrity-v1",
                    }],
                },
            }
            (journal_dir / "2026-08-10.json").write_text(
                json.dumps(chain), encoding="utf-8"
            )
            (log_dir / "scheduled_push_morning.log").write_text(
                "2026-08-10 pool_id=mp-abc", encoding="utf-8"
            )
            (log_dir / "scheduled_push_afternoon.log").write_text(
                "2026-08-10 decision_id=cd-abc outcome=BUY", encoding="utf-8"
            )
            report = validate_p2_session(
                "2026-08-10", journal_dir=journal_dir, log_dir=log_dir
            )
            self.assertTrue(report["passed"], report)
            chain["confirmation"]["decision_id"] = "cd-other"
            (journal_dir / "2026-08-10.json").write_text(
                json.dumps(chain), encoding="utf-8"
            )
            failed = validate_p2_session(
                "2026-08-10", journal_dir=journal_dir, log_dir=log_dir
            )
            self.assertFalse(failed["passed"])
            self.assertFalse(failed["checks"]["afternoon_push_same_id"])


if __name__ == "__main__":
    unittest.main()
