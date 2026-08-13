"""Read-only V5 cutover preflight. Never modifies tasks or ports."""
from __future__ import annotations
import ast,json
from pathlib import Path
from .calendar import TradingCalendar
ROOT=Path(__file__).resolve().parents[1]
def build():
    imports=[]
    for path in sorted((ROOT/"v5").glob("*.py")):
        tree=ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names=[]
            if isinstance(node,ast.Import):names=[x.name for x in node.names]
            elif isinstance(node,ast.ImportFrom):names=[node.module or ""]
            imports.extend(f"{path.name}:{node.lineno}:{name}" for name in names if name=="v4" or name.startswith("v4."))
    state=json.loads((ROOT/"docs/v5-project-state.json").read_text(encoding="utf-8"))
    try:TradingCalendar();calendar_ready=True
    except Exception:calendar_ready=False
    checks={"no_v4_runtime_imports":not imports,"v5_reference_calendar":calendar_ready,"research_locked":state.get("production_status")=="research_locked","broker_disabled":state.get("broker_orders_enabled") is False,"offline_tests_recorded":int(state.get("tests_passed",0))>0,"real_source_ready":state.get("real_source_ready") is True,"live_shadow_accepted":state.get("live_shadow_accepted") is True}
    return {"schema_version":"v5-cutover-preflight-v1","passed":all(checks.values()),"checks":checks,"v4_imports":imports,"apply_allowed":False,"read_only":True}
if __name__=="__main__":
    report=build();print(json.dumps(report,ensure_ascii=False,indent=2));raise SystemExit(0 if report["passed"] else 3)
