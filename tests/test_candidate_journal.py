import tempfile
import unittest
from pathlib import Path

from v4.candidate_journal import CandidateJournal

MARKET = {"data_valid": True, "snapshot_id": "ms1-" + "a" * 64,
          "market_state_id": "mstate1-" + "b" * 64}


class CandidateJournalTests(unittest.TestCase):
    def test_confirmation_is_linked_to_morning_pool(self):
        with tempfile.TemporaryDirectory() as directory:
            journal = CandidateJournal(Path(directory))
            morning = [{
                "code": "000001", "rank": 2, "score": 86,
                "quote_time": "2026-08-05 09:25:01", "v4_candidate_origin": "V4",
            }]
            journal.save_morning("2026-08-05", morning, MARKET)
            journal.save_confirmation("2026-08-05", [{
                "code": "000001", "rank": 1, "score": 90,
                "v4_candidate_origin": "V4", "v4_paper_policy_version": "test-policy-v1",
            }], MARKET)
            row = journal.load("2026-08-05")["confirmation"]["candidates"][0]
            self.assertTrue(row["morning_pool_member"])
            self.assertEqual(row["morning_rank"], 2)
            self.assertEqual(row["linkage_status"], "confirmed_from_morning_pool")

    def test_confirmation_outside_pool_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            journal = CandidateJournal(Path(directory))
            journal.save_morning("2026-08-05", [{
                "code": "000001", "v4_candidate_origin": "V4",
            }], MARKET)
            with self.assertRaises(ValueError):
                journal.save_confirmation("2026-08-05", [{"code": "000002"}], MARKET)

    def test_empty_morning_pool_is_still_a_valid_observation(self):
        with tempfile.TemporaryDirectory() as directory:
            journal = CandidateJournal(Path(directory))
            journal.save_morning("2026-08-05", [], MARKET)
            self.assertTrue(journal.has_morning("2026-08-05"))
            self.assertEqual(journal.morning_candidates("2026-08-05"), [])

    def test_morning_and_confirmation_are_immutable_but_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            journal = CandidateJournal(Path(directory))
            morning = [{
                "code": "000001", "rank": 1, "score": 80,
                "v4_candidate_origin": "V4",
            }]
            first = journal.save_morning("2026-08-05", morning, MARKET)
            second = journal.save_morning("2026-08-05", morning, MARKET)
            self.assertEqual(first["morning"]["pool_id"], second["morning"]["pool_id"])
            with self.assertRaisesRegex(ValueError, "immutable"):
                journal.save_morning("2026-08-05", [], MARKET)

            final = [{
                "code": "000001", "rank": 1, "score": 80,
                "v4_candidate_origin": "V4", "v4_paper_eligible": True,
                "v4_paper_block_reasons": [],
                "v4_paper_policy_version": "test-policy-v1",
            }]
            journal.save_confirmation("2026-08-05", final, MARKET)
            saved = journal.load("2026-08-05")["confirmation"]
            self.assertEqual(saved["outcome"], "BUY")
            self.assertEqual(saved["reason_codes"], ["eligible_top1"])
            journal.save_confirmation("2026-08-05", final, MARKET)
            blocked = dict(final[0], v4_paper_eligible=False,
                           v4_paper_block_reasons=["规则分低于80"])
            with self.assertRaisesRegex(ValueError, "immutable"):
                journal.save_confirmation("2026-08-05", [blocked], MARKET)

    def test_missing_morning_is_persisted_as_blocked_decision(self):
        with tempfile.TemporaryDirectory() as directory:
            journal = CandidateJournal(Path(directory))
            first = journal.save_missing_morning_confirmation(
                "2026-08-05", MARKET
            )
            second = journal.save_missing_morning_confirmation(
                "2026-08-05", MARKET
            )
            decision = first["confirmation"]
            self.assertEqual(decision["outcome"], "BLOCKED")
            self.assertEqual(decision["reason_codes"], ["missing_morning_pool"])
            self.assertEqual(
                decision["decision_id"], second["confirmation"]["decision_id"]
            )
            with self.assertRaisesRegex(ValueError, "after confirmation"):
                journal.save_morning("2026-08-05", [], MARKET)


if __name__ == "__main__":
    unittest.main()
