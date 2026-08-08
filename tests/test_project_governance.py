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

    def test_reopened_p1_p2_status_matches_documented_reality(self):
        state = load_state()
        self.assertEqual(state["active_phase"], "P1")
        self.assertEqual(state["p1_validation"]["engineering_status"], "reopened_incomplete")
        self.assertEqual(state["p2_validation"]["engineering_status"], "reopened_blocked_by_p1")
        self.assertEqual(state["phase_status"]["P2"], "pending")
        modules = (ROOT / "docs" / "MODULES.md").read_text(encoding="utf-8")
        self.assertNotIn("P1完成", modules)
        self.assertNotIn("P2完成", modules)


if __name__ == "__main__":
    unittest.main()
