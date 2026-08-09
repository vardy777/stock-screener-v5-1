import tempfile,unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock,patch

from v4.execution import CHINA_TZ
from v4.replay_contracts import FeatureContextV1,PREVIOUS_CONTEXT_COLUMNS
from v4 import p5_sources
from v4.decision_production import P2DecisionProducer

class IntegrationHardeningTests(unittest.TestCase):
    def test_p2_producer_has_no_account_or_compatibility_facade(self):
        gateway=MagicMock(); gateway.fetch_snapshot.return_value=SimpleNamespace(quotes=[object()])
        journal=MagicMock(); runtime=MagicMock(); runtime.evaluate_universe.return_value=[]
        service=MagicMock(); service.publish_morning.return_value={"pool_id":"mp-test"}
        now=datetime(2026,8,10,9,25,tzinfo=CHINA_TZ)
        with patch("v4.decision_production.TradingClock.now",return_value=now), \
             patch("v4.decision_production.analyze_market",return_value={"market_state":{"data_valid":True}}), \
             patch("v4.decision_production.DecisionChainService",return_value=service):
            result=P2DecisionProducer(gateway=gateway,journal=journal,runtime=runtime,universe_codes=["000001"]).produce("morning")
        self.assertEqual(result["pool_id"],"mp-test")
        gateway.fetch_snapshot.assert_called_once()
        service.publish_morning.assert_called_once()

    def test_feature_context_binds_market_snapshot(self):
        previous={name:("000001" if name=="code" else "2026-08-07" if name=="context_date" else 1.0) for name in PREVIOUS_CONTEXT_COLUMNS}
        from phase1.overnight.dataset import FEATURE_COLUMNS
        features={"000001":{name:1.0 for name in FEATURE_COLUMNS}}
        context=FeatureContextV1.build(trade_date="2026-08-10",expected_previous_session="2026-08-07",
            feature_as_of=datetime(2026,8,10,14,49,tzinfo=CHINA_TZ),previous_context=[previous],
            confirmation_features=features,input_snapshot_id="ms1-abc")
        self.assertEqual(context.to_dict()["input_snapshot_id"],"ms1-abc")

    def test_non_trading_day_has_expected_idle_heartbeat(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(p5_sources.TradingCalendar,"is_open",return_value=False):
            model=p5_sources.P5ReadOnlySources(Path(directory)).build(generated_at=datetime(2026,8,9,12,tzinfo=CHINA_TZ))
            self.assertEqual(model.operations["heartbeat_status"],"IDLE_NON_TRADING_DAY")
            self.assertNotIn("HEARTBEAT_STALE",{issue["reason_code"] for issue in model.issues})

if __name__=="__main__": unittest.main()
