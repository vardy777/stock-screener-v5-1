import json
import tempfile
import unittest
from pathlib import Path

from v4.legacy_decision_audit import audit_legacy_journal


class LegacyDecisionAuditTests(unittest.TestCase):
    def test_detects_false_link_block_without_rewriting_source(self):
        payload = {
            "trade_date": "2026-08-07",
            "morning": {"candidates": [{"code": "600397"}]},
            "confirmation": {"candidates": [{
                "code": "600397", "morning_score": 91.84, "score": 77.5,
                "v4_paper_block_reasons": ["未通过09:25母池链路确认"],
            }]},
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "2026-08-07.json"
            path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            before = path.read_bytes()
            report = audit_legacy_journal(path)
            after = path.read_bytes()
        self.assertEqual(before, after)
        self.assertTrue(report["confirmation_is_morning_subset"])
        self.assertEqual(report["false_link_block_codes"], ["600397"])
        self.assertFalse(report["promotable_to_v1"])


if __name__ == "__main__":
    unittest.main()
