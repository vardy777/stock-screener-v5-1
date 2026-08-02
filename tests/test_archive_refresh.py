import unittest

import pandas as pd

from phase1.overnight.archive_refresh import (
    detect_volume_unit,
    merge_archive,
    normalise_volume_to_shares,
    validate_archive,
)


class ArchiveRefreshTests(unittest.TestCase):
    @staticmethod
    def _frame(times, closes):
        return pd.DataFrame(
            {
                "date": times,
                "open": closes,
                "high": closes,
                "low": closes,
                "close": closes,
                "volume": [100] * len(times),
                "amount": [0] * len(times),
                "pct_chg": [0] * len(times),
            }
        )

    def test_incomplete_session_is_rejected(self):
        frame = self._frame(["2026-07-31 10:30:00"], [10.0])
        valid, reason = validate_archive(frame, "2026-07-31")
        self.assertFalse(valid)
        self.assertEqual(reason, "incomplete_expected_session")

    def test_new_bar_replaces_partial_bar_and_preserves_history(self):
        existing = self._frame(
            ["2026-07-30 15:00:00", "2026-07-31 10:30:00"],
            [9.8, 10.0],
        )
        recent = self._frame(
            ["2026-07-31 10:30:00", "2026-07-31 15:00:00"],
            [10.1, 10.2],
        )
        merged = merge_archive(existing, recent)
        valid, reason = validate_archive(merged, "2026-07-31")
        self.assertTrue(valid, reason)
        self.assertEqual(len(merged), 3)
        self.assertEqual(float(merged.iloc[1]["close"]), 10.1)

    def test_legacy_volume_x100_is_converted_once(self):
        frame = pd.DataFrame({"volume": [3_852_515_500, 2_603_972_100, 0]})
        self.assertEqual(detect_volume_unit(frame["volume"]), "legacy_x100")
        converted, reason = normalise_volume_to_shares(frame)
        self.assertEqual(reason, "converted")
        self.assertEqual(converted["volume"].tolist(), [38_525_155, 26_039_721, 0])
        unchanged, second_reason = normalise_volume_to_shares(converted)
        self.assertEqual(second_reason, "already_shares")
        self.assertEqual(unchanged["volume"].tolist(), converted["volume"].tolist())


if __name__ == "__main__":
    unittest.main()
