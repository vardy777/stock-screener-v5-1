import ast
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class P2ArchitectureTests(unittest.TestCase):
    def test_consumers_do_not_generate_or_reinterpret_decisions(self):
        consumers = (
            ROOT / "v4" / "dashboard.py",
            ROOT / "v4" / "scripts" / "morning_push.py",
            ROOT / "v4" / "scripts" / "afternoon_push.py",
        )
        forbidden = {"screen_today", "evaluate_universe", "evaluate_candidates", "adaptive_strategy_decision"}
        violations = []
        for path in consumers:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Call):
                    name = node.func.attr if isinstance(node.func, ast.Attribute) else (
                        node.func.id if isinstance(node.func, ast.Name) else ""
                    )
                    if name in forbidden:
                        violations.append(f"{path.name}:{node.lineno}:{name}")
                if isinstance(node, (ast.Import, ast.ImportFrom)):
                    if any(alias.name == "adaptive_strategy_decision" for alias in node.names):
                        violations.append(f"{path.name}:{node.lineno}:adaptive import")
        self.assertEqual(violations, [])

    def test_runtime_state_contains_diagnostics_not_candidate_entities(self):
        source = (ROOT / "v4" / "runtime.py").read_text(encoding="utf-8")
        self.assertNotIn('diagnostic["candidates"]', source)
        self.assertNotIn('diagnostic["candidate_codes"]', source)
        self.assertIn('diagnostic["derived_only"] = True', source)

    def test_dashboard_state_has_no_candidate_business_role(self):
        source = (ROOT / "v4" / "simulation.py").read_text(encoding="utf-8")
        self.assertNotIn("dashboard_state.json", source)
        self.assertNotIn("_save_candidates", source)
        self.assertNotIn("load_candidates_from_file", source)

    def test_replay_starts_from_validated_snapshot_repository(self):
        source = (ROOT / "v4" / "snapshot_replay.py").read_text(encoding="utf-8")
        self.assertIn("SnapshotRepository", source)
        self.assertEqual(source.count("repository.load("), 2)
        self.assertIn("persist=False", source)
        self.assertIn("persist_diagnostics=False", source)
        self.assertIn("FeatureContextV1.load", source)
        self.assertNotIn("LiveFeatureStore", source)
        self.assertNotIn("CONTEXT_PATH", source)

    def test_legacy_scheduled_push_entry_produces_then_projects(self):
        source = (ROOT / "phase1" / "scripts" / "run_scheduled_push.ps1").read_text(
            encoding="utf-8"
        )
        producer = source.index('Script = "v4\\scripts\\decision_job.py"')
        consumer = source.index("Script = $pushScript")
        self.assertLess(producer, consumer)

    def test_signal_job_archives_replay_feature_context(self):
        source = (
            ROOT / "phase1" / "scripts" / "capture_signal_features.py"
        ).read_text(encoding="utf-8")
        self.assertIn("FeatureContextV1.build", source)
        self.assertIn('"replay_context"', source)
