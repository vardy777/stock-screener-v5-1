"""Create-once P3 ledger initialization plan; never reads or changes production implicitly."""
from __future__ import annotations
import hashlib,json
from pathlib import Path
from .p3_account import OfflinePaperLedger
from .p3_storage import atomic_json_write,exclusive_file_lock
from .production_gate import require_authorized_owner

def initialization_plan(*,initial_cash=100000):
    body={"schema_version":"p3-initialization-plan-v1","initial_cash":float(initial_cash),
          "positions":[],"source":"authorized_clean_genesis","apply_allowed":False}
    raw=json.dumps(body,sort_keys=True,separators=(",",":"))
    return {**body,"plan_id":"p3init-"+hashlib.sha256(raw.encode()).hexdigest()[:24]}

def initialize_once(directory:Path, *, authorization_file:Path, initial_cash=100000):
    lease=require_authorized_owner(authorization_file,resource="paper_account",owner="P3")
    root=Path(directory); marker=root/"p3_initialization.json"; lock=root/".p3_initialization.lock"
    plan=initialization_plan(initial_cash=initial_cash)
    with exclusive_file_lock(lock):
        if marker.exists():
            current=json.loads(marker.read_text(encoding="utf-8"))
            if current.get("plan_id")!=plan["plan_id"]:
                raise RuntimeError("P3_ACCOUNT_ALREADY_INITIALIZED_WITH_DIFFERENT_PLAN")
            return current
        ledger=OfflinePaperLedger(root,initial_cash=initial_cash)
        if ledger.path.exists():
            raise RuntimeError("P3_LEDGER_EXISTS_WITHOUT_INITIALIZATION_MARKER")
        # Persist the ledger before the marker; a crash is detected and never guessed over.
        atomic_json_write(ledger.path,ledger._empty())
        result={**plan,"apply_allowed":True,"authorization_id":lease.authorization_id,
                "ledger_path":str(ledger.path.resolve()),"status":"INITIALIZED"}
        atomic_json_write(marker,result)
        return result
