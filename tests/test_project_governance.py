import json
import unittest
from pathlib import Path

from scripts.project_status import REQUIRED_FILES, build_report, load_state


ROOT = Path(__file__).resolve().parents[1]
UTF8_CONTEXT_FILES = (
    "PROJECT.md",
    "AGENTS.md",
    "docs/project-state.json",
    "docs/ROADMAP.md",
    "docs/ARCHITECTURE.md",
    "docs/MODULES.md",
    "docs/CHANGELOG.md",
    "v4/README.md",
)


class ProjectGovernanceTests(unittest.TestCase):
    def test_required_context_files_exist(self):
        self.assertEqual(
            [name for name in REQUIRED_FILES if not (ROOT / name).exists()], []
        )

    def test_project_state_schema_and_phase_are_valid(self):
        state = load_state()
        self.assertEqual(state["schema_version"], "project-state-v1")
        self.assertIn(state["active_phase"], state["phase_status"])
        self.assertEqual(state["phase_status"][state["active_phase"]], "in_progress")
        self.assertEqual(state["production_status"], "research_locked")
        self.assertFalse(state["paper_contract"]["broker_orders_enabled"])

    def test_project_report_is_consistent(self):
        report = build_report()
        self.assertTrue(report["ok"], json.dumps(report, ensure_ascii=False))
        self.assertEqual(report["v3_import_violations"], [])

    def test_context_files_are_strict_utf8_without_replacement_characters(self):
        for name in UTF8_CONTEXT_FILES:
            text = (ROOT / name).read_bytes().decode("utf-8", errors="strict")
            self.assertNotIn("\ufffd", text, name)

    def test_later_phases_are_offline_only_while_p1_p2_live_validation_is_pending(self):
        state = load_state()
        self.assertEqual(state["active_phase"], "P6")
        self.assertEqual(state["p1_validation"]["engineering_status"], "offline_completed")
        self.assertEqual(state["p1_validation"]["live_window_status"], "pending_real_windows")
        self.assertEqual(state["p2_validation"]["engineering_status"], "offline_completed")
        self.assertEqual(state["p2_validation"]["live_window_status"], "pending_real_windows")
        self.assertEqual(
            state["phase_status"]["P2"], "offline_completed_live_pending"
        )
        self.assertEqual(state["phase_status"]["P3"], "in_progress")
        p3 = state["p3_validation"]
        self.assertEqual(p3["operating_mode"], "offline_only")
        self.assertFalse(p3["scheduling_enabled"])
        self.assertFalse(p3["daily_paper_production_connected"])
        self.assertFalse(p3["completion_allowed"])
        p4 = state["p4_validation"]
        self.assertEqual(p4["operating_mode"], "offline_only")
        self.assertFalse(p4["windows_tasks_registered_by_p4"])
        self.assertFalse(p4["real_pushplus_called"])
        self.assertFalse(p4["production_entrypoints_connected"])
        self.assertFalse(p4["completion_allowed"])
        p5 = state["p5_validation"]
        self.assertEqual(p5["operating_mode"], "offline_preview_only")
        self.assertFalse(p5["existing_8898_connected"])
        self.assertFalse(p5["mutation_endpoints_enabled"])
        self.assertFalse(p5["production_cutover_allowed"])
        self.assertEqual(state["phase_status"]["P5"], "offline_completed_cutover_pending")
        self.assertFalse(state["p6_validation"]["production_evaluation_allowed"])
        self.assertFalse(state["p7_validation"]["production_publication_allowed"])
        self.assertFalse(state["p8_validation"]["production_data_backup_performed"])
        self.assertFalse(state["p8_validation"]["production_restore_performed"])
        self.assertFalse(state["p8_validation"]["historical_archive_performed"])
        cutover=state["cutover_preparation"]
        self.assertTrue(cutover["live_window_acceptance_available"])
        self.assertTrue(cutover["writer_inventory_required"])
        self.assertFalse(cutover["apply_allowed"])
        self.assertFalse(cutover["tasks_modified"])
        self.assertFalse(cutover["account_migrated"])
        self.assertFalse(cutover["dashboard_switched"])
        self.assertEqual(cutover["unified_offline_acceptance_status"],"passed_247_tests_no_production_mutation")
        self.assertEqual(cutover["legacy_2026_08_07_window_projection"],"failed_as_expected_not_valid_live_evidence")
        modules = (ROOT / "docs" / "MODULES.md").read_text(encoding="utf-8")
        self.assertNotIn("P1完成", modules)
        self.assertNotIn("P2完成", modules)


if __name__ == "__main__":
    unittest.main()
