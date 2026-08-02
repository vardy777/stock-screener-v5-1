import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import pandas as pd

from market_universe import is_eligible_a_share, list_universe_codes
from v3.factors import FACTOR_WEIGHTS
from v3.scorer import UltraShortScorer


class UniverseAndScoringTests(unittest.TestCase):
    def test_supported_a_share_boards_are_complete_without_b_shares(self):
        for code in (
            "000001", "001289", "002415", "003816",
            "300750", "301269", "302132",
            "600000", "601318", "603259", "605499",
        ):
            self.assertTrue(is_eligible_a_share(code), code)
        for code in ("200002", "900901", "688001", "689009", "430047", "830799"):
            self.assertFalse(is_eligible_a_share(code), code)

    def test_live_universe_comes_from_archive_not_synthetic_ranges(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            for code in ("002415", "601318", "603259", "605499", "200002"):
                (root / f"{code}.csv").touch()
            self.assertEqual(
                list_universe_codes(root),
                ["002415", "601318", "603259", "605499"],
            )

    def test_tied_factors_are_neutral_and_order_independent(self):
        rows = []
        for code in ("000001", "600000", "002415"):
            row = {"code": code}
            row.update({name: 1.0 for name in FACTOR_WEIGHTS})
            rows.append(row)
        first = UltraShortScorer().score(pd.DataFrame(rows))
        second = UltraShortScorer().score(pd.DataFrame(list(reversed(rows))))
        first_scores = first.set_index("code")["final_score"].to_dict()
        second_scores = second.set_index("code")["final_score"].to_dict()
        self.assertEqual(first_scores, second_scores)
        self.assertEqual(set(first_scores.values()), {50.0})


if __name__ == "__main__":
    unittest.main()
