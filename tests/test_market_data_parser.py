import unittest

from v3.data import DataFetcher


class MarketDataParserTests(unittest.TestCase):
    def test_sina_volume_is_already_shares_and_order_book_is_preserved(self):
        text = (
            'var hq_str_sz000001="平安银行,11.500,11.610,11.630,11.630,'
            '11.280,11.620,11.630,202497895,2318839881.310,152600,11.620,'
            '14100,11.610,380900,11.600,296300,11.590,381900,11.580,'
            '532889,11.630,2908900,11.640,930020,11.650,407800,11.660,'
            '166900,11.670,2026-07-31,16:30:00,00";'
        )
        frame = DataFetcher()._parse_sina_quotes(text)
        row = frame.iloc[0]
        self.assertEqual(int(row["volume"]), 202_497_895)
        self.assertEqual(float(row["bid1"]), 11.62)
        self.assertEqual(float(row["ask1"]), 11.63)
        self.assertEqual(int(row["bid1_volume"]), 152_600)
        self.assertEqual(int(row["ask1_volume"]), 532_889)


if __name__ == "__main__":
    unittest.main()
