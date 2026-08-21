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
        self.assertEqual(state["schema_version"], "project-state-v2")
        self.assertEqual(state["project"], "a-share-overnight-v5")
        self.assertEqual(state["production_status"], "research_locked")
        self.assertFalse(state["broker_orders_enabled"])

    def test_project_report_is_consistent(self):
        report = build_report()
        self.assertTrue(report["ok"], json.dumps(report, ensure_ascii=False))
        self.assertEqual(report["v3_import_violations"], [])
        self.assertEqual(report["governance_issues"], [])

    def test_context_files_are_strict_utf8_without_replacement_characters(self):
        for name in UTF8_CONTEXT_FILES:
            text = (ROOT / name).read_bytes().decode("utf-8", errors="strict")
            self.assertNotIn("\ufffd", text, name)

    def test_v5_production_state_preserves_research_gate_and_live_truth(self):
        state = load_state()
        self.assertEqual(state["live_evidence"]["complete_successful_days"], 0)
        self.assertEqual(state["quality"]["strategy_effectiveness"], "unproven")
        self.assertFalse(state["hard_gates"]["model_publication_allowed"])
        self.assertFalse(state["hard_gates"]["paper_or_live_cutover_allowed"])
        self.assertTrue(state["schedule"]["nine_safe_tasks_registered"])
        self.assertFalse(state["schedule"]["paper_or_broker_tasks_registered"])
        self.assertEqual(state["notifications"]["owner"], "v5")


if __name__ == "__main__":
    unittest.main()
