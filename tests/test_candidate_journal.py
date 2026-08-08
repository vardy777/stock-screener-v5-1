import tempfile
import unittest
from pathlib import Path

from v4.candidate_journal import CandidateJournal


class CandidateJournalTests(unittest.TestCase):
    def test_confirmation_is_linked_to_morning_pool(self):
        with tempfile.TemporaryDirectory() as directory:
            journal = CandidateJournal(Path(directory))
            morning = [{
                "code": "000001", "rank": 2, "score": 86,
                "quote_time": "2026-08-05 09:25:01", "v4_candidate_origin": "V4",
            }]
            journal.save_morning("2026-08-05", morning, {"data_valid": True})
            journal.save_confirmation("2026-08-05", [{
                "code": "000001", "rank": 1, "score": 90,
                "v4_candidate_origin": "V4",
            }], {"data_valid": True})
            row = journal.load("2026-08-05")["confirmation"]["candidates"][0]
            self.assertTrue(row["morning_pool_member"])
            self.assertEqual(row["morning_rank"], 2)
            self.assertEqual(row["linkage_status"], "confirmed_from_morning_pool")

    def test_confirmation_outside_pool_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            journal = CandidateJournal(Path(directory))
            journal.save_morning("2026-08-05", [{
                "code": "000001", "v4_candidate_origin": "V4",
            }], {})
            with self.assertRaises(ValueError):
                journal.save_confirmation("2026-08-05", [{"code": "000002"}], {})

    def test_empty_morning_pool_is_still_a_valid_observation(self):
        with tempfile.TemporaryDirectory() as directory:
            journal = CandidateJournal(Path(directory))
            journal.save_morning("2026-08-05", [], {"data_valid": True})
            self.assertTrue(journal.has_morning("2026-08-05"))
            self.assertEqual(journal.morning_candidates("2026-08-05"), [])


if __name__ == "__main__":
    unittest.main()
