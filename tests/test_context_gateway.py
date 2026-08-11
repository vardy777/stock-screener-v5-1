import unittest
from datetime import date,timedelta

from phase1.overnight.context_gateway import build_context,build_symbol_context


def rows(end="2026-08-10",count=25):
    finish=date.fromisoformat(end); values=[]
    for offset in range(count-1,-1,-1):
        day=finish-timedelta(days=offset); price=10+(count-offset)*0.01
        values.append([day.isoformat(),str(price),str(price+0.02),str(price+0.04),str(price-0.03),"1000"])
    return values


class ContextGatewayTests(unittest.TestCase):
    def test_symbol_context_discards_future_and_converts_lots(self):
        value=rows()+[["2026-08-11","11","11","11","11","99"]]
        result,reason,future=build_symbol_context(value,"600000","2026-08-10")
        self.assertEqual((reason,future),("ok",1))
        self.assertEqual(result["context_date"],"2026-08-10")
        self.assertEqual(result["volume_mean_20"],100000.0)

    def test_full_context_requires_cross_provider_verification(self):
        codes=["600000","000001"]
        frame,metadata=build_context(codes,"2026-08-10",reference_prices={c:10.25 for c in codes},
            reference_source="snapshot",workers=2,fetcher=lambda code:rows())
        self.assertEqual(len(frame),2)
        self.assertTrue(metadata["strict_context_ready"])
        self.assertEqual(metadata["reference_match_rate"],1.0)

    def test_missing_reference_fails_closed(self):
        _,metadata=build_context(["600000"],"2026-08-10",reference_prices={},
            reference_source="missing",workers=1,fetcher=lambda code:rows())
        self.assertFalse(metadata["strict_context_ready"])

    def test_partial_reference_below_95_percent_fails_closed(self):
        codes=[f"{index:06d}" for index in range(100)]
        references={code:10.25 for code in codes[:94]}
        _,metadata=build_context(codes,"2026-08-10",reference_prices=references,
            reference_source="partial",workers=4,fetcher=lambda code:rows())
        self.assertFalse(metadata["strict_context_ready"])

if __name__=="__main__": unittest.main()
