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
        for path in sorted((ROOT / "v4").glob("p3_*.py")):
            name = path.name
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

    def test_existing_production_paths_do_not_import_p3_modules(self):
        paths = (
            ROOT / "v4" / "sim_engine.py",
            ROOT / "v4" / "simulation.py",
            ROOT / "v4" / "paper_scheduler.py",
            ROOT / "v4" / "dashboard.py",
            ROOT / "v4" / "scripts" / "paper_trade.py",
        )
        violations = []
        for path in paths:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                modules = []
                if isinstance(node, ast.ImportFrom):
                    modules.append(node.module or "")
                elif isinstance(node, ast.Import):
                    modules.extend(alias.name for alias in node.names)
                for module in modules:
                    if module.startswith("v4.p3_") or module.startswith(".p3_"):
                        violations.append(f"{path.name}:{node.lineno}:{module}")
        self.assertEqual(violations, [])

    def test_legacy_validator_is_read_only_by_construction(self):
        source = (ROOT / "v4" / "p3_migration.py").read_text(encoding="utf-8")
        for forbidden in ("write_text(", "write_bytes(", "replace(", "unlink(", "open(\"w"):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
