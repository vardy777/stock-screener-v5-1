import json
import unittest
from pathlib import Path

from scripts.project_status import REQUIRED_FILES, build_report, load_state, runtime_observation
import tempfile


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
        self.assertFalse(state["hard_gates"]["broker_or_live_trading_allowed"])
        self.assertTrue(state["schedule"]["eleven_tasks_registered"])
        self.assertTrue(state["schedule"]["paper_tasks_registered"])
        self.assertFalse(state["schedule"]["broker_tasks_registered"])
        self.assertEqual(state["notifications"]["owner"], "v5")

    def test_runtime_status_prefers_newer_non_strict_recovery_without_promoting_it(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);pool=root/"v5/data/morning_pools/2026-08-18/p.json";pool.parent.mkdir(parents=True);pool.write_text(json.dumps({"trade_date":"2026-08-18","created_at":"2026-08-18T09:25:10+08:00","candidates":[]}),encoding="utf-8")
            recovery=root/"v5/data/recovery_observations/2026-08-21/r.json";recovery.parent.mkdir(parents=True);recovery.write_text(json.dumps({"trade_date":"2026-08-21","observed_at":"2026-08-21T13:02:00+08:00","snapshot_id":"ms1-test","candidates":[{}]}),encoding="utf-8")
            receipt=root/"v5/data/recovery_notifications/2026-08-21/r.json";receipt.parent.mkdir(parents=True);receipt.write_text(json.dumps({"outcome":"ACCEPTED"}),encoding="utf-8")
            value=runtime_observation(root)
            self.assertEqual(value["kind"],"non_strict_recovery_observation")
            self.assertFalse(value["strict_0925_sample"])
            self.assertEqual(value["notification_outcome"],"ACCEPTED")


if __name__ == "__main__":
    unittest.main()
