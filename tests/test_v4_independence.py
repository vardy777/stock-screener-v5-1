import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class V4IndependenceTests(unittest.TestCase):
    def test_v3_runtime_tree_is_retired(self):
        self.assertFalse((ROOT / "v3").exists())

    def test_v4_runtime_has_no_v3_imports(self):
        violations = []
        for path in (ROOT / "v4").rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            if "from v3" in text or "import v3" in text:
                violations.append(str(path.relative_to(ROOT)))
        self.assertEqual(violations, [])

    def test_operational_phase1_scripts_have_no_v3_imports(self):
        names = (
            "capture_execution_snapshot.py",
            "capture_signal_features.py",
            "daily_pipeline.py",
            "fetch_all.py",
            "refresh_intraday_archive.py",
            "test_pushplus.py",
            "verify_capture_health.py",
        )
        violations = []
        for name in names:
            path = ROOT / "phase1" / "scripts" / name
            text = path.read_text(encoding="utf-8")
            if "from v3" in text or "import v3" in text:
                violations.append(name)
        self.assertEqual(violations, [])

    def test_dashboard_launcher_starts_v4_module_directly(self):
        text = (ROOT / "start_dashboard.py").read_text(encoding="utf-8")
        self.assertIn('"-m", "v4.p5_dashboard"', text)
        self.assertNotIn('"v3-dashboard"', text)


if __name__ == "__main__":
    unittest.main()
