import ast
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class P3ArchitectureTests(unittest.TestCase):
    def test_offline_modules_have_no_production_or_scheduler_dependency(self):
        forbidden_modules = {
            "v4.sim_engine", "v4.simulation", "v4.paper_scheduler",
            "v4.dashboard", "v4.config", "v4.push",
        }
        violations = []
        for name in ("p3_contracts.py", "p3_account.py"):
            path = ROOT / "v4" / name
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.module in forbidden_modules:
                    violations.append(f"{name}:{node.lineno}:{node.module}")
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        if alias.name in forbidden_modules:
                            violations.append(f"{name}:{node.lineno}:{alias.name}")
        self.assertEqual(violations, [])

    def test_offline_ledger_has_no_default_production_path(self):
        source = (ROOT / "v4" / "p3_account.py").read_text(encoding="utf-8")
        self.assertNotIn("DATA_DIR", source)
        self.assertNotIn("v4/data", source.replace("\\", "/"))
        self.assertNotIn("DEFAULT_ACCOUNT_PATH", source)


if __name__ == "__main__":
    unittest.main()
