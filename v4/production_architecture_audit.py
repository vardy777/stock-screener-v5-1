"""Static audit of every enabled P4 production leaf and ownership boundary."""
from __future__ import annotations
import ast
from pathlib import Path
from .production_task_runner import COMMANDS

FORBIDDEN_NAMES={"DataFetcher","SimulationEngine"}
FORBIDDEN_PRODUCTION_IMPORTS={"v4.dashboard","v4.simulation","v4.sim_engine"}

def _python_leaf(command):
    return next((Path(value) for value in command if str(value).lower().endswith(".py")),None)

def audit_production_architecture(root:Path)->dict:
    root=Path(root).resolve(); issues=[]; leaves={}
    for task,command in COMMANDS.items():
        leaf=_python_leaf(command)
        if leaf is None or not leaf.is_file(): issues.append(f"MISSING_PYTHON_LEAF:{task}"); continue
        leaves[task]=str(leaf.resolve())
        try: relative=leaf.resolve().relative_to(root/"v4"/"scripts")
        except ValueError: issues.append(f"LEAF_OUTSIDE_V4:{task}:{leaf}"); continue
        tree=ast.parse(leaf.read_text(encoding="utf-8"),filename=str(leaf))
        for node in ast.walk(tree):
            if isinstance(node,ast.ImportFrom) and str(node.module or "").startswith("v3"):
                issues.append(f"V3_IMPORT:{task}:{node.lineno}")
            if isinstance(node,ast.Name) and node.id in FORBIDDEN_NAMES:
                issues.append(f"FORBIDDEN_COMPATIBILITY_FACADE:{task}:{node.id}:{node.lineno}")
            if isinstance(node,ast.ImportFrom) and str(node.module or "") in FORBIDDEN_PRODUCTION_IMPORTS:
                issues.append(f"LEGACY_RUNTIME_IMPORT:{task}:{node.module}:{node.lineno}")
            if isinstance(node,ast.Import):
                for alias in node.names:
                    if alias.name in FORBIDDEN_PRODUCTION_IMPORTS:
                        issues.append(f"LEGACY_RUNTIME_IMPORT:{task}:{alias.name}:{node.lineno}")
    signal=root/"phase1/scripts/capture_signal_features.py"
    signal_text=signal.read_text(encoding="utf-8")
    if "DataFetcher" in signal_text or "fetch_quotes_with_retries" in signal_text:
        issues.append("SIGNAL_BYPASSES_MARKET_GATEWAY")
    if "MarketDataGateway" not in signal_text or "snapshot_frame" not in signal_text:
        issues.append("SIGNAL_VERSIONED_SNAPSHOT_MISSING")
    decision=(root/"v4/scripts/decision_job.py").read_text(encoding="utf-8")
    if "SimulationEngine" in decision or "P2DecisionProducer" not in decision:
        issues.append("DECISION_PRODUCER_NOT_PURE_P2")
    return {"schema_version":"production-architecture-audit-v1","passed":not issues,
            "issues":issues,"leaves":leaves,"read_only":True}
