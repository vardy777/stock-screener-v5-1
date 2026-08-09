import json,tempfile,unittest
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo

from v4.p3_initialization import initialize_once
from v4.p4_deployment import full_offline_task_manifest,render_disabled_task_definitions
from v4.production_adapter import run_disabled
from v4.production_gate import ProductionGateError,require_authorized_owner

ROOT=Path(__file__).resolve().parents[1]
NOW=datetime(2026,8,10,9,25,tzinfo=ZoneInfo("Asia/Shanghai"))

def authorization(path):
    value={"schema_version":"production-authorization-v1","apply_allowed":True,
      "authorization_id":"auth-test-only","owners":{"paper_account":"P3","task_receipts":"P4"},
      "writers":[{"resource":"paper_account","owner":"P3","active":True},
                 {"resource":"task_receipts","owner":"P4","active":True}]}
    path.write_text(json.dumps(value),encoding="utf-8"); return path

class ProductionPreparationTests(unittest.TestCase):
    def test_manifest_is_complete_executable_and_disabled(self):
        value=full_offline_task_manifest(ROOT); self.assertEqual(len(value["tasks"]),9)
        self.assertTrue(all("p4_task_adapter.py" in x["command"] for x in value["tasks"]))
        self.assertTrue(all(x["enabled"] is False for x in value["tasks"]))
        definitions=render_disabled_task_definitions(ROOT)
        self.assertFalse(definitions["apply_allowed"]); self.assertFalse(definitions["registration_performed"])
        self.assertTrue(all(x["enabled"] is False for x in definitions["definitions"]))

    def test_adapter_is_blocked_without_authorization_or_bound_implementation(self):
        first=run_disabled("morning_decision",trade_date="2026-08-10",now=NOW)
        self.assertEqual((first.status,first.reason_code),("BLOCKED","PRODUCTION_ADAPTER_DISABLED"))
        with tempfile.TemporaryDirectory() as td:
            auth=authorization(Path(td)/"auth.json")
            second=run_disabled("morning_decision",trade_date="2026-08-10",authorization_file=auth,now=NOW)
            self.assertEqual(second.reason_code,"PRODUCTION_IMPLEMENTATION_UNBOUND")

    def test_dual_writer_authorization_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            path=authorization(Path(td)/"auth.json"); value=json.loads(path.read_text())
            value["writers"].append({"resource":"paper_account","owner":"legacy","active":True})
            path.write_text(json.dumps(value),encoding="utf-8")
            with self.assertRaisesRegex(ProductionGateError,"SINGLE_WRITER_GATE_FAILED"):
                require_authorized_owner(path,resource="paper_account",owner="P3")

    def test_p3_initialization_is_create_once_and_detects_orphan_ledger(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); auth=authorization(root/"auth.json"); account=root/"account"
            first=initialize_once(account,authorization_file=auth); second=initialize_once(account,authorization_file=auth)
            self.assertEqual(first,second); self.assertTrue((account/"paper_ledger.json").is_file())
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); auth=authorization(root/"auth.json"); account=root/"account"; account.mkdir()
            (account/"paper_ledger.json").write_text("{}")
            with self.assertRaisesRegex(RuntimeError,"WITHOUT_INITIALIZATION_MARKER"):
                initialize_once(account,authorization_file=auth)

if __name__=="__main__": unittest.main()
