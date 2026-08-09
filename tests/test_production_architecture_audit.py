import unittest
from pathlib import Path
from v4.production_architecture_audit import audit_production_architecture

ROOT=Path(__file__).resolve().parents[1]

class ProductionArchitectureAuditTests(unittest.TestCase):
    def test_every_production_leaf_respects_v4_boundaries(self):
        report=audit_production_architecture(ROOT)
        self.assertTrue(report["passed"],report["issues"])
        self.assertEqual(len(report["leaves"]),7)

if __name__=="__main__": unittest.main()
