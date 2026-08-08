import hashlib,json,tempfile,unittest,zipfile
from datetime import datetime,timedelta
from pathlib import Path

import pandas as pd

from phase1.overnight.dataset import FEATURE_COLUMNS
from v4.execution import CHINA_TZ
from v4.p6_research_audit import audit_strict_dataset,audit_walk_forward
from v4.p7_release_audit import audit_release_bundle
from v4.p8_backup import BackupViolation,create_backup,restore_to_empty,verify_backup


class P6ResearchAuditTests(unittest.TestCase):
    def frame(self):
        rows=[]
        for day in range(100):
            for code in range(5):
                row={x:0.01 for x in FEATURE_COLUMNS}
                row.update({"date":f"2026-01-{1+day%28:02d}T{day//28:02d}:00:00","code":f"{code+day*5:06d}",
                    "strict_row":True,"exact_buy":True,"exact_sell":True,"feature_mode":"strict_pre_1450",
                    "calendar_verified":True,"order_book_verified":True,"order_book_liquidity_verified":True,"net_return":.01})
                rows.append(row)
        return pd.DataFrame(rows)

    def metadata(self):
        return {"dataset_mode":"strict","strict_dataset_ready":True,"point_in_time_universe_verified":True,
                "point_in_time_security_name_verified":True,"calendar_verified":True,"volume_unit_verified":True,
                "minimum_buy_universe_coverage":.97,"dataset_sha256":"d"*64}

    def test_strict_dataset_passes_only_with_all_point_in_time_controls(self):
        passed=audit_strict_dataset(self.frame(),self.metadata()); self.assertTrue(passed["passed"]); self.assertTrue(passed["audit_id"].startswith("sda1-"))
        bad=self.frame(); bad.loc[0,"strict_row"]=False; bad.loc[1,"signal_return"]=float("nan")
        failed=audit_strict_dataset(bad,{**self.metadata(),"point_in_time_security_name_verified":False})
        self.assertFalse(failed["passed"]); self.assertIn("NON_STRICT:strict_row",failed["reasons"]); self.assertIn("NON_FINITE_VALUES",failed["reasons"])

    def test_walk_forward_and_stress_must_share_frozen_strict_lineage(self):
        normal={"trades":500,"win_rate_ci_low_95":.51,"profit_factor":1.2,"window_consistency":.7,
                "max_drawdown":-.1,"dataset_mode":"strict","proxy_trade_rate":0,"dataset_sha256":"d"*64}
        stress={"dataset_sha256":"d"*64,"stress_policy_frozen":True,"cumulative_return":.01,
                "profit_factor":1.01,"total_windows":4,"frozen_policy_windows":4}
        self.assertTrue(audit_walk_forward(normal,stress)["passed"])
        failed=audit_walk_forward({**normal,"trades":499},{**stress,"dataset_sha256":"e"*64})
        self.assertFalse(failed["passed"]); self.assertIn("INSUFFICIENT_OOS_TRADES",failed["reasons"]); self.assertIn("DATASET_LINEAGE_MISMATCH",failed["reasons"])


class P7ReleaseAuditTests(unittest.TestCase):
    @staticmethod
    def write(path,value): path.write_text(json.dumps(value,sort_keys=True),encoding="utf-8")
    @staticmethod
    def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()

    def test_release_audit_binds_model_to_both_accepted_report_files(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); model=root/"model"; model.mkdir(); normal=root/"normal.json"; stress=root/"stress.json"
            self.write(normal,{"acceptance_pass":True}); self.write(stress,{"stress_policy_frozen":True})
            width=len(FEATURE_COLUMNS); schema=hashlib.sha256(json.dumps(FEATURE_COLUMNS,separators=(",",":")).encode()).hexdigest()
            artifact=model/"overnight_ridge.json"; policy=model/"selection_policy.json"; training=model/"training_info.json"
            self.write(artifact,{"feature_columns":FEATURE_COLUMNS,"medians":[0]*width,"means":[0]*width,"scales":[1]*width,
                "return_coef":[0]*(width+1),"positive_coef":[0]*(width+1),"hit_coef":[0]*(width+1),"loss_coef":[0]*(width+1)})
            self.write(policy,{"contract_version":"v4-selection-policy-v1","feature_columns":FEATURE_COLUMNS,"max_positions":1,
                "minimum_predicted_return":0,"minimum_positive_probability":None,"maximum_large_loss_probability":None,"minimum_regime_score":None,"score_column":"predicted_return"})
            self.write(training,{"model":"ridge","research_only":False,"dataset_mode":"strict","strict_dataset_ready":True,
                "point_in_time_universe_verified":True,"point_in_time_security_name_verified":True,"feature_columns":FEATURE_COLUMNS,
                "feature_schema_sha256":schema,"dataset_sha256":"d"*64,"normal_report_sha256":self.sha(normal),"stress_report_sha256":self.sha(stress)})
            self.write(model/"published_model.json",{"contract_version":"v4-published-model-v1","model_file":artifact.name,"model_sha256":self.sha(artifact),
                "policy_file":policy.name,"policy_sha256":self.sha(policy),"training_info_file":training.name,"training_info_sha256":self.sha(training),
                "dataset_sha256":"d"*64,"feature_schema_sha256":schema})
            self.assertTrue(audit_release_bundle(model,normal,stress)["passed"])
            stress.write_text("{}",encoding="utf-8"); result=audit_release_bundle(model,normal,stress)
            self.assertFalse(result["passed"]); self.assertIn("STRESS_REPORT_LINEAGE_MISMATCH",result["reasons"]); self.assertFalse(result["changes_production_status"])


class P8BackupTests(unittest.TestCase):
    def test_content_addressed_backup_restore_and_idempotence(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); source=root/"source"; source.mkdir(); (source/"a.json").write_text('{"x":1}',encoding="utf-8"); (source/"nested").mkdir(); (source/"nested"/"b.txt").write_text("中",encoding="utf-8")
            at=datetime(2026,8,8,23,tzinfo=CHINA_TZ); first=create_backup(source,root/"backups",created_at=at); second=create_backup(source,root/"backups",created_at=at)
            self.assertEqual(first,second); self.assertTrue(verify_backup(first)["passed"])
            restored=restore_to_empty(first,root/"restored"); self.assertTrue(restored["passed"]); self.assertEqual((root/"restored"/"nested"/"b.txt").read_text("utf-8"),"中")

    def test_corrupt_backup_and_nonempty_restore_fail_closed(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td); source=root/"source"; source.mkdir(); (source/"a").write_text("1")
            backup=create_backup(source,root/"backups",created_at=datetime(2026,8,8,tzinfo=CHINA_TZ))
            raw=bytearray(backup.read_bytes()); raw[-10]^=0xFF; backup.write_bytes(raw)
            self.assertFalse(verify_backup(backup)["passed"])
            target=root/"target"; target.mkdir(); (target/"keep").write_text("x")
            with self.assertRaises(BackupViolation): restore_to_empty(backup,target)
            file_target=root/"file-target"; file_target.write_text("x")
            with self.assertRaises(BackupViolation): restore_to_empty(backup,file_target)

if __name__=="__main__": unittest.main()
