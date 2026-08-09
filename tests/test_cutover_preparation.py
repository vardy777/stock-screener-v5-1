import hashlib,json,tempfile,unittest
from datetime import datetime
from pathlib import Path

from v4.cutover_readiness import build_cutover_readiness,task_diff,validate_writer_inventory
from v4.live_window_acceptance import WINDOWS,derive_project_evidence,validate_live_window_chain,write_acceptance_report,write_evidence_once
from v4.offline_rehearsal import ORDER,rehearse,successful_empty_cycle
from v4.operations_preflight import audit_log_retention,operational_preflight
from v4.p4_deployment import full_offline_task_manifest
from scripts.offline_acceptance import build,secret_scan

ROOT=Path(__file__).resolve().parents[1]


class LiveWindowAcceptanceTests(unittest.TestCase):
    def evidence(self,day,name):
        value={"schema_version":"live-window-evidence-v1","status":"PASSED","trade_date":day,
               "observed_at":f"{day}T14:50:20+08:00","snapshot_id":"ms1-test","fresh_quote_coverage":.97,
               "strict_cohort_separated":True}
        if name=="morning_0925": value.update(pool_id="mp-test",candidate_codes=["000001"])
        if name=="feature_1449": value.update(feature_context_id="fc1-test")
        if name=="confirmation_1450": value.update(decision_id="cd-test",morning_pool_id="mp-test",feature_context_id="fc1-test",candidate_codes=["000001"])
        if name=="sell_0930": value.update(source_trade_date=day,trade_date="2026-08-11",observed_at="2026-08-11T09:30:20+08:00")
        return value

    def test_complete_chain_is_content_addressed_and_sources_are_not_modified(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); day="2026-08-10"; directory=root/day; directory.mkdir()
            paths=[]
            for name in WINDOWS:
                path=directory/f"{name}.json"; path.write_text(json.dumps(self.evidence(day,name)),encoding="utf-8"); paths.append(path)
            before={p:hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
            first=validate_live_window_chain(day,root); second=validate_live_window_chain(day,root)
            self.assertTrue(first["passed"]); self.assertEqual(first,second); self.assertEqual(before,{p:hashlib.sha256(p.read_bytes()).hexdigest() for p in paths})
            out=write_acceptance_report(first,root/"reports"/"acceptance.json"); self.assertTrue(out.is_file())

    def test_missing_stale_wrong_subset_and_merged_cohort_fail_closed(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); day="2026-08-10"; directory=root/day; directory.mkdir()
            for name in WINDOWS:
                value=self.evidence(day,name)
                if name=="confirmation_1450": value["candidate_codes"]=["600000"]; value["strict_cohort_separated"]=False
                if name=="feature_1449": value["fresh_quote_coverage"]=.5
                (directory/f"{name}.json").write_text(json.dumps(value),encoding="utf-8")
            (directory/"sell_0930.json").unlink()
            report=validate_live_window_chain(day,root); self.assertFalse(report["passed"])
            reasons={r for x in report["checks"]+report["lineage"] for r in x.get("reasons",[]) if isinstance(r,str)}
            self.assertIn("COVERAGE_BELOW_95_PERCENT",reasons)
            self.assertFalse(next(x for x in report["lineage"] if x["name"]=="candidate_subset")["passed"])

    def test_project_derivation_does_not_fabricate_missing_window_evidence(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); journals=root/"journals"; logs=root/"logs"; snapshots=root/"snapshots"
            journals.mkdir(); logs.mkdir(); snapshots.mkdir()
            values=derive_project_evidence("2026-08-10","2026-08-11",journal_dir=journals,log_dir=logs,snapshot_root=snapshots)
            self.assertEqual(set(values),set(WINDOWS)); self.assertTrue(all(x["status"]=="FAILED" for x in values.values()))
            self.assertEqual(values["sell_0930"]["snapshot_id"],""); self.assertEqual(values["sell_0930"]["observed_at"],"")

    def test_window_evidence_is_create_once_and_idempotent(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/"window.json"; value={"schema_version":"live-window-evidence-v1","status":"PASSED"}
            write_evidence_once(value,path); first=path.read_bytes(); write_evidence_once(value,path); self.assertEqual(first,path.read_bytes())
            with self.assertRaisesRegex(ValueError,"immutable"): write_evidence_once({**value,"status":"FAILED"},path)


class CutoverReadinessTests(unittest.TestCase):
    def test_plan_is_never_applicable_without_explicit_authorization(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); account=root/"account.json"
            account.write_text(json.dumps({"capital":100000,"initial_capital":100000,"positions":[],"history":[]}),encoding="utf-8")
            expected=full_offline_task_manifest(ROOT)["tasks"]
            installed=[{"task_name":x["windows_task_name"],"command":x["command"],"at":x["at"]} for x in expected]
            report=build_cutover_readiness(project_root=ROOT,live_acceptance={"passed":True},legacy_account_path=account,
                installed_tasks=installed,backup_verification={"passed":True},writers=[
                    {"resource":"candidate_decision","owner":"P2","active":True},
                    {"resource":"paper_account","owner":"legacy_production","active":True},
                    {"resource":"task_receipts","owner":"legacy_phase1_scripts","active":True}])
            self.assertFalse(report["ready"]); self.assertFalse(report["apply_allowed"]); self.assertFalse(report["production_mutated"])
            self.assertEqual([x["passed"] for x in report["gates"]],[True,True,True,True,True,False])
            self.assertIn("verify_no_dual_writers",report["rollback"])

    def test_task_diff_detects_missing_different_and_extra(self):
        report=task_diff(ROOT,[{"task_name":"AStock-V4-Morning-Decision-0925","command":"wrong","at":"09:25:00"},{"task_name":"legacy_extra"}])
        self.assertFalse(report["passed"]); states={x["status"] for x in report["rows"]}; self.assertTrue({"MISSING","DIFFERENT"}.issubset(states)); self.assertEqual(report["extra_tasks"],["legacy_extra"])

    def test_task_diff_accepts_full_executable_command_containing_contract_tokens(self):
        expected=full_offline_task_manifest(ROOT)["tasks"]
        installed=[{"task_name":x["windows_task_name"],"at":x["at"],"command":f'C:/python.exe C:/project/{x["command"]}'} for x in expected]
        self.assertTrue(task_diff(ROOT,installed)["passed"])

    def test_writer_inventory_rejects_dual_writer_and_validates_target_owner(self):
        dual=[{"resource":"paper_account","owner":"legacy_production","active":True},{"resource":"paper_account","owner":"P3","active":True}]
        self.assertFalse(validate_writer_inventory(dual)["passed"])
        target=[{"resource":"candidate_decision","owner":"P2","active":True},{"resource":"paper_account","owner":"P3","active":True},{"resource":"task_receipts","owner":"P4","active":True}]
        self.assertTrue(validate_writer_inventory(target,target=True)["passed"])


class RehearsalAndOperationsTests(unittest.TestCase):
    def test_successful_cycle_and_failure_matrix(self):
        self.assertTrue(successful_empty_cycle()["passed"])
        for event,status,reason in (("MORNING_NOTIFIED","FAILED","NOTIFICATION_NOT_CONFIRMED"),("BUY_TERMINAL","OUTCOME_UNKNOWN","BUY_REQUIRES_RECOVERY"),("SELL_TERMINAL","FAILED","SELL_REQUIRES_RECOVERY")):
            rows=[{"event":name,"status":status if name==event else "SUCCEEDED"} for name in ORDER]
            result=rehearse(rows); self.assertFalse(result["passed"]); self.assertTrue(any(reason in x for x in result["reasons"]))
        wrong=rehearse([{"event":"FEATURE_FROZEN","status":"SUCCEEDED"}]); self.assertFalse(wrong["passed"]); self.assertTrue(any("ORDER_VIOLATION" in x for x in wrong["reasons"]))

    def test_operational_preflight_is_read_only(self):
        report=operational_preflight(ROOT,minimum_free_gib=0); self.assertTrue(report["passed"]); self.assertTrue(report["read_only"]); self.assertFalse(report["production_mutated"])

    def test_unified_offline_acceptance_has_no_false_secret_alarm(self):
        self.assertEqual(secret_scan(),[])
        report=build(run_tests=False); self.assertTrue(report["passed"]); self.assertFalse(report["production_mutated"]); self.assertFalse(report["tests"]["run"])

    def test_log_retention_audit_only_reports_candidates(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); logs=root/"v4"/"logs"; logs.mkdir(parents=True); path=logs/"large.log"; path.write_text("12345")
            before=hashlib.sha256(path.read_bytes()).hexdigest(); report=audit_log_retention(root,max_bytes=1,retention_days=0,
                now=datetime(2030,1,1,tzinfo=__import__('datetime').timezone.utc))
            self.assertTrue(report["logs"][0]["rotation_candidate"]); self.assertTrue(report["logs"][0]["retention_candidate"])
            self.assertFalse(report["mutation_performed"]); self.assertEqual(before,hashlib.sha256(path.read_bytes()).hexdigest())

    def test_inventory_and_cutover_scripts_contain_no_task_mutation_commands(self):
        exporter=(ROOT/"scripts"/"export_v4_runtime_inventory.ps1").read_text(encoding="utf-8")
        for forbidden in ("Register-ScheduledTask","Unregister-ScheduledTask","Set-ScheduledTask","Disable-ScheduledTask","Enable-ScheduledTask"):
            self.assertNotIn(forbidden,exporter)

if __name__=="__main__": unittest.main()
