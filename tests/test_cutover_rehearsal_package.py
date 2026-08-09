import unittest
from pathlib import Path
from v4.cutover_rehearsal import FAULTS,full_frozen_rehearsal,rehearse_fault
from v4.cutover_authorization_package import build_package

ROOT=Path(__file__).resolve().parents[1]
class CutoverRehearsalPackageTests(unittest.TestCase):
    def test_complete_fault_matrix_is_fail_safe_and_read_only(self):
        report=full_frozen_rehearsal(); self.assertTrue(report["passed"])
        self.assertEqual({x["fault"] for x in report["fault_matrix"]},set(FAULTS))
        self.assertFalse(report["production_mutated"]); self.assertFalse(report["network_called"])
        self.assertIn("verify_no_dual_writers",report["rollback"])
    def test_unknown_fault_is_rejected(self):
        with self.assertRaisesRegex(ValueError,"unknown fault"): rehearse_fault("MAGIC")
    def test_package_never_self_authorizes_even_when_other_gates_pass(self):
        package=build_package(ROOT,live_acceptance={"passed":True},offline_acceptance={"passed":True})
        self.assertFalse(package["apply_allowed"]); self.assertFalse(package["ready_for_authorization"])
        self.assertFalse(package["production_mutated"]); self.assertFalse(package["gates"]["explicit_user_authorization"])
        self.assertTrue(all(x["enabled"] is False for x in package["task_definitions"]["definitions"]))
if __name__=="__main__": unittest.main()
