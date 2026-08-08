import ast
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ALLOWED_PROVIDER_BOUNDARIES = {"data.py", "market_gateway.py"}


class P1ArchitectureTests(unittest.TestCase):
    def test_only_gateway_or_provider_module_can_access_raw_quote_provider(self):
        violations = []
        for path in sorted((ROOT / "v4").glob("*.py")):
            if path.name in ALLOWED_PROVIDER_BOUNDARIES:
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, (ast.Import, ast.ImportFrom)):
                    names = [item.name for item in node.names]
                    if "DataFetcher" in names:
                        violations.append(f"{path.name}:{node.lineno}:DataFetcher import")
                if isinstance(node, ast.Call):
                    function = node.func
                    if isinstance(function, ast.Name) and function.id == "DataFetcher":
                        violations.append(f"{path.name}:{node.lineno}:DataFetcher call")
                    if isinstance(function, ast.Attribute) and function.attr == "batch_fetch_quotes":
                        violations.append(f"{path.name}:{node.lineno}:raw quote call")
        self.assertEqual(violations, [])

    def test_core_snapshot_consumers_reject_loose_objects(self):
        from v4.market import build_market_state
        from v4.market_contracts import ContractViolation
        from v4.snapshot_frame import snapshot_frame

        for consumer in (snapshot_frame, build_market_state):
            with self.subTest(consumer=consumer.__name__):
                with self.assertRaises(ContractViolation):
                    consumer({"quotes": []})

    def test_v4_has_no_implicit_local_timezone_or_naive_now(self):
        violations = []
        for path in sorted((ROOT / "v4").glob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                    continue
                if (
                    node.func.attr == "now"
                    and isinstance(node.func.value, ast.Name)
                    and node.func.value.id == "datetime"
                    and not node.args and not node.keywords
                ):
                    violations.append(f"{path.name}:{node.lineno}:naive datetime.now")
                if node.func.attr == "astimezone" and not node.args and not node.keywords:
                    violations.append(f"{path.name}:{node.lineno}:implicit local astimezone")
                if node.func.attr == "replace":
                    for keyword in node.keywords:
                        if keyword.arg == "tzinfo" and not (
                            isinstance(keyword.value, ast.Constant) and keyword.value.value is None
                        ):
                            violations.append(f"{path.name}:{node.lineno}:timezone injection")
        self.assertEqual(violations, [])
