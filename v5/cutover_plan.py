"""Report-only atomic cutover readiness. Does not mutate tasks or ports."""
from pathlib import Path
import json
from .cutover_preflight import build
from .paper import PaperLedger
def plan(root):
 root=Path(root);preflight=build();facts=any((root/"v5/data/morning_pools").rglob("*.json")) and any((root/"v5/data/confirmations").rglob("*.json"));reconcile=PaperLedger(root/"v5/data/paper").reconcile()["passed"]
 checks={"cutover_preflight":preflight["passed"],"v5_facts_exist":bool(facts),"paper_reconciled":reconcile,"rollback_backup_exists":any((root/"backups").glob("v5-cutover-*"))};return {"schema_version":"v5-atomic-cutover-plan-v1","apply_allowed":all(checks.values()),"checks":checks,"actions":["disable V4 paper/scheduler/dashboard tasks","write authorized ownership contract","register V5 nine tasks","switch 8898 to V5","verify single writer and HTTP 200"],"rollback":["stop V5 tasks","restore task inventory backup","restore 8898 V4 dashboard","ownership back to V4"]}
if __name__=="__main__":print(json.dumps(plan(Path(__file__).resolve().parents[1]),ensure_ascii=False,indent=2))
