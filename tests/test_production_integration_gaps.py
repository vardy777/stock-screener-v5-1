import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from v4.execution import CHINA_TZ
from v4 import production_task_runner as runner
from v4 import push
from v4.scripts import morning_push


class _Response:
    def __init__(self, payload): self.payload = payload
    def __enter__(self): return self
    def __exit__(self, *_): return False
    def read(self): return json.dumps(self.payload).encode()


class ProductionIntegrationGapTests(unittest.TestCase):
    def test_terminal_feature_failure_still_allows_empty_confirmation(self):
        now=datetime(2026,8,10,14,50,20,tzinfo=CHINA_TZ)
        outputs={
            "feature_freeze":{"status":"FAILED"},
            "morning_decision":{"status":"SUCCEEDED"},
        }
        with (
            tempfile.TemporaryDirectory() as temporary,
            patch.object(runner,"ROOT",Path(temporary)),
            patch.object(runner,"require_authorized_owner"),
            patch.object(runner,"_latest",side_effect=lambda task,day: outputs.get(task,{})),
            patch.object(runner,"_entity",return_value=("cd-test",{"decision_id":"cd-test"},("mp-test",))),
            patch.object(runner.subprocess,"run",return_value=SimpleNamespace(returncode=0,stdout="",stderr="")),
        ):
            result=runner.run("confirmation_decision",authorization_file="unused",now=now)
        self.assertEqual(result["status"],"SUCCEEDED")

    def test_maintenance_runs_after_terminal_health_failure(self):
        now=datetime(2026,8,10,15,10,tzinfo=CHINA_TZ)
        with (
            tempfile.TemporaryDirectory() as temporary,
            patch.object(runner,"ROOT",Path(temporary)),
            patch.object(runner,"require_authorized_owner"),
            patch.object(runner,"_latest",return_value={"status":"FAILED"}),
            patch.object(runner,"_entity",return_value=("maintenance-test",{"passed":True},())),
            patch.object(runner.subprocess,"run",return_value=SimpleNamespace(returncode=0,stdout="",stderr="")),
        ):
            result=runner.run("maintenance",authorization_file="unused",now=now)
        self.assertEqual(result["status"],"SUCCEEDED")

    def test_failed_task_can_retry_same_day_and_heartbeat_tracks_latest(self):
        now=datetime(2026,8,10,9,25,tzinfo=CHINA_TZ)
        with (
            tempfile.TemporaryDirectory() as temporary,
            patch.object(runner,"ROOT",Path(temporary)),
            patch.object(runner,"require_authorized_owner"),
            patch.object(runner,"_entity",return_value=("mp-test",{"pool_id":"mp-test"},())),
            patch.object(runner.subprocess,"run",side_effect=[SimpleNamespace(returncode=7,stdout="",stderr="bad"),SimpleNamespace(returncode=0,stdout="ok",stderr="")]) as execute,
        ):
            first=runner.run("morning_decision",authorization_file="unused",now=now)
            second=runner.run("morning_decision",authorization_file="unused",now=now)
            third=runner.run("morning_decision",authorization_file="unused",now=now)
            self.assertEqual((first["status"],first["attempt"]),("FAILED",1))
            self.assertEqual((second["status"],second["attempt"]),("SUCCEEDED",2))
            self.assertEqual(third["output_id"],second["output_id"])
            self.assertEqual(execute.call_count,2)
            root=Path(temporary)/"v4/data/p4/outputs/2026-08-10/morning_decision"
            self.assertTrue((root/"attempt-0001.json").exists())
            self.assertTrue((root/"attempt-0002.json").exists())
            heartbeat=json.loads((Path(temporary)/"v4/data/p4/heartbeat.json").read_text(encoding="utf-8"))
            self.assertEqual((heartbeat["status"],heartbeat["task_status"]),("ALIVE","SUCCEEDED"))

    def test_notification_attempts_are_immutable_and_lineage_bound(self):
        with (
            tempfile.TemporaryDirectory() as temporary,
            patch.object(push,"PUSH_RECEIPT_PATH",Path(temporary)/"push_receipts.json"),
            patch.object(push,"PUSHPLUS_TOKEN","token"),
            patch.object(push.urllib.request,"urlopen",side_effect=[_Response({"code":500,"msg":"no"}),_Response({"code":200,"data":"request-2"})]) as request,
        ):
            self.assertTrue(push.send_wechat("title","payload",message_key="v4-morning:2026-08-10",
                parent_entity_id="mp-test",attempts=2,retry_delay_seconds=0))
            receipt=push.load_notification_receipt("v4-morning:2026-08-10")
            self.assertEqual((receipt.outcome,receipt.parent_entity_id,receipt.transport_request_id),("ACCEPTED","mp-test","request-2"))
            history=sorted((Path(temporary)/"notifications").glob("*/attempt-*.json"))
            self.assertEqual(len(history),2)
            self.assertEqual(json.loads(history[0].read_text(encoding="utf-8"))["outcome"],"REJECTED")
            self.assertTrue(push.send_wechat("title","payload",message_key="v4-morning:2026-08-10",parent_entity_id="mp-test"))
            self.assertFalse(push.send_wechat("title","changed",message_key="v4-morning:2026-08-10",parent_entity_id="mp-test"))
            self.assertEqual(request.call_count,2)

    def test_push_positions_are_read_only_from_p3_ledger(self):
        ledger=SimpleNamespace(snapshot=lambda:{"positions":[{"code":"000001"}]})
        with patch.object(morning_push,"OfflinePaperLedger",return_value=ledger) as factory:
            self.assertEqual(morning_push._p3_positions(),[{"code":"000001"}])
            self.assertTrue(str(factory.call_args.args[0]).replace("\\","/").endswith("v4/data/p3"))

    def test_p5_handler_is_configured_for_per_request_data_reads(self):
        source=(Path(__file__).resolve().parents[1]/"v4/p5_dashboard.py").read_text(encoding="utf-8")
        self.assertIn("P5ReadOnlySources(Path(self.data_dir)).build()",source)
        self.assertNotIn("Handler.model=P5ReadOnlySources",source)


if __name__=="__main__": unittest.main()
