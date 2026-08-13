"""Read-only audit of V5 ownership and remaining production dependencies."""
from __future__ import annotations
import ast,json
from pathlib import Path
from .calendar import TradingCalendar
def audit(root):
    root=Path(root);violations=[]
    for path in (root/"v5").rglob("*.py"):
        text=path.read_text(encoding="utf-8")
        tree=ast.parse(text)
        for node in ast.walk(tree):
            names=[]
            if isinstance(node,ast.Import):names=[x.name for x in node.names]
            elif isinstance(node,ast.ImportFrom):names=[node.module or ""]
            if any(x=="v4" or x.startswith("v4.") or x=="phase1" or x.startswith("phase1.") for x in names):violations.append(f"{path.relative_to(root)}:{node.lineno}")
        if path.name!="independence_audit.py" and ("v4/.env" in text or "v4\\.env" in text):violations.append(f"{path.relative_to(root)}:legacy_config")
    state=json.loads((root/"docs/v5-project-state.json").read_text(encoding="utf-8"));migration=state["migration_completion"]
    try:calendar=TradingCalendar();calendar_ready=calendar.is_open(__import__("datetime").date.today()) is not None
    except Exception:calendar_ready=False
    checks={"no_legacy_runtime_imports":not violations,"v5_reference_calendar":calendar_ready,"v5_sensitive_config":migration["v5_owns_sensitive_configuration"],"v5_market_adapters":migration.get("v5_owns_market_data_adapters",False),"v5_fact_production":migration.get("v5_owns_fact_production_code",False),"production_data_exists":migration["v5_fact_files_available"],"production_scheduler_cutover":migration["v5_owns_scheduler"],"dashboard_8898_cutover":migration["v5_owns_dashboard_8898"]}
    return {"schema_version":"v5-independence-audit-v1","fully_independent":all(checks.values()),"checks":checks,"violations":violations}
if __name__=="__main__":
    import sys;result=audit(Path(__file__).resolve().parents[1]);print(json.dumps(result,ensure_ascii=False,indent=2));raise SystemExit(0 if result["fully_independent"] else 2)
