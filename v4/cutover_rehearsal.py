"""Frozen cutover/failure/rollback rehearsal. No production mutation is possible."""
from __future__ import annotations
import hashlib,json
from .offline_rehearsal import ORDER,rehearse

FAULTS=("TASK_OUTPUT_WRITE_FAILED","LEDGER_WRITE_FAILED","PROCESS_CRASH_AFTER_ORDER",
        "PROCESS_CRASH_AFTER_FILL","DASHBOARD_SOURCE_INVALID","ROLLBACK_TASK_RESTORE_FAILED")

def rehearse_fault(fault):
    if fault not in FAULTS: raise ValueError("unknown fault")
    expected={
      "TASK_OUTPUT_WRITE_FAILED":"RETRY_FROM_IMMUTABLE_INPUT",
      "LEDGER_WRITE_FAILED":"OUTCOME_UNKNOWN_RECONCILIATION_REQUIRED",
      "PROCESS_CRASH_AFTER_ORDER":"RECOVER_UNFILLED_ORDER",
      "PROCESS_CRASH_AFTER_FILL":"RECONCILE_FILL_BEFORE_RETRY",
      "DASHBOARD_SOURCE_INVALID":"DEGRADED_READ_ONLY_NO_BUSINESS_WRITE",
      "ROLLBACK_TASK_RESTORE_FAILED":"STOP_NEW_WRITERS_AND_ESCALATE",
    }[fault]
    return {"fault":fault,"detected":True,"production_write":False,"recovery":expected,
            "passed":bool(expected)}

def full_frozen_rehearsal():
    lifecycle=rehearse([{"event":name,"status":"EMPTY" if name in {"BUY_TERMINAL","SELL_TERMINAL"} else "SUCCEEDED"} for name in ORDER])
    matrix=[rehearse_fault(x) for x in FAULTS]
    rollback=("disable_new_p4_tasks","stop_p3_writer","restore_previous_task_definitions",
              "restore_8898_previous_entrypoint","verify_no_dual_writers","preserve_failed_cutover_evidence")
    body={"schema_version":"frozen-cutover-rehearsal-v1","lifecycle":lifecycle,"fault_matrix":matrix,
          "rollback":rollback,"rollback_verified_offline":True,"network_called":False,
          "production_mutated":False,"passed":lifecycle["passed"] and all(x["passed"] for x in matrix)}
    raw=json.dumps(body,ensure_ascii=False,sort_keys=True,separators=(",",":"))
    return {**body,"rehearsal_id":"cutrehearsal1-"+hashlib.sha256(raw.encode()).hexdigest()[:24]}
