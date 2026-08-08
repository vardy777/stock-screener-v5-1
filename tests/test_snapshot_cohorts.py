import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from v4.execution import CHINA_TZ
from v3.snapshot_compat import build_daily_quality_report, capture_frame


class SnapshotCohortTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 8, 3, 14, 50, 10, tzinfo=CHINA_TZ)

    def row(self, **changes):
        value = {
            "code": "000001", "name": "测试股票", "price": 10.0,
            "prev_close": 9.9, "bid1": 9.99, "bid1_volume": 10000,
            "ask1": 10.01, "ask1_volume": 12000,
            "volume": 100000, "amount": 1000000.0,
            "quote_time": self.now.isoformat(), "is_mock": False,
            "halted": False, "limit_up": False, "limit_down": False,
        }
        value.update(changes)
        return value

    def test_strict_and_paper_only_are_physically_isolated(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            with patch("v3.snapshot_compat.SNAPSHOT_ROOT", root):
                strict = capture_frame(
                    pd.DataFrame([self.row()]), "buy", now=self.now,
                    expected_codes=["000001"], require_order_book=True,
                )
                paper = capture_frame(
                    pd.DataFrame([self.row()]), "buy", now=self.now,
                    expected_codes=["000001", "000002"], require_order_book=True,
                    evidence_cohort="paper_only", capture_role="paper_execution",
                )
            self.assertEqual(strict.parent, root / "strict" / "buy")
            self.assertEqual(paper.parent, root / "paper_only" / "buy")
            self.assertFalse(list((root / "strict" / "buy").glob("*paper*")))
            strict_manifest = json.loads(
                strict.with_suffix(strict.suffix + ".meta.json").read_text("utf-8")
            )
            paper_manifest = json.loads(
                paper.with_suffix(paper.suffix + ".meta.json").read_text("utf-8")
            )
            self.assertEqual(strict_manifest["evidence_cohort"], "strict")
            self.assertEqual(paper_manifest["evidence_cohort"], "paper_only")
            self.assertIn("incomplete_coverage", paper_manifest["quality"]["reasons"])

    def test_rejected_capture_writes_quality_report_but_no_evidence_csv(self):
        cases = [
            ([self.row(name="ST测试")], "ineligible_name"),
            ([self.row(ask1=0, ask1_volume=0)], "missing_order_book"),
            ([self.row(limit_up=True)], "limit_locked"),
            ([self.row(), self.row()], "duplicate_code"),
        ]
        for rows, expected_reason in cases:
            with self.subTest(reason=expected_reason), tempfile.TemporaryDirectory() as temp_dir:
                root = Path(temp_dir)
                with patch("v3.snapshot_compat.SNAPSHOT_ROOT", root):
                    output = capture_frame(
                        pd.DataFrame(rows), "buy", now=self.now,
                        expected_codes=["000001"], require_order_book=True,
                    )
                self.assertIsNone(output)
                self.assertFalse((root / "strict" / "buy").exists())
                reports = list((root / "quality" / "strict" / "buy").glob("*.json"))
                self.assertEqual(len(reports), 1)
                report = json.loads(reports[0].read_text("utf-8"))
                reasons = report["quality"].get("reasons", [])
                rejected = report.get("rejected_rows", {})
                self.assertTrue(
                    expected_reason in reasons or expected_reason in rejected,
                    (expected_reason, reasons, rejected),
                )

    def test_naive_capture_clock_is_rejected_not_assumed(self):
        with self.assertRaisesRegex(ValueError, "timezone-aware"):
            capture_frame(
                pd.DataFrame([self.row()]), "buy",
                now=datetime(2026, 8, 3, 14, 50, 10),
            )

    def test_daily_report_keeps_cohorts_separate(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            with patch("v3.snapshot_compat.SNAPSHOT_ROOT", root):
                capture_frame(
                    pd.DataFrame([self.row()]), "buy", now=self.now,
                    expected_codes=["000001"], require_order_book=True,
                )
                capture_frame(
                    pd.DataFrame([self.row()]), "buy", now=self.now,
                    expected_codes=["000001", "000002"], require_order_book=True,
                    evidence_cohort="paper_only",
                )
                report = build_daily_quality_report("2026-08-03", root=root)
            self.assertFalse(report["cohorts_merged"])
            self.assertEqual(report["cohorts"]["strict"]["accepted"], 1)
            self.assertEqual(report["cohorts"]["paper_only"]["accepted"], 1)
            self.assertTrue((root / "quality" / "daily" / "2026-08-03.json").exists())


if __name__ == "__main__":
    unittest.main()
