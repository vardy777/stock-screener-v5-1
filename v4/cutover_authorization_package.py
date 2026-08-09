"""Prepare, but never grant, the future atomic cutover authorization package."""
from __future__ import annotations
import hashlib,json
from pathlib import Path
from .p4_deployment import render_disabled_task_definitions

def build_package(project_root:Path, *, live_acceptance:dict, offline_acceptance:dict):
    gates={"offline_acceptance":offline_acceptance.get("passed") is True,
           "live_windows":live_acceptance.get("passed") is True,
           "explicit_user_authorization":False}
    body={"schema_version":"atomic-cutover-authorization-package-v1",
      "gates":gates,"task_definitions":render_disabled_task_definitions(project_root),
      "sequence":["backup_and_hash_current_state","stop_legacy_writers","verify_zero_legacy_writers",
        "initialize_p3_once","register_p4_tasks_disabled","verify_target_inventory","enable_p4_single_owner",
        "switch_8898_to_p5","run_read_only_smoke","verify_no_dual_writers"],
      "rollback":["disable_p4","stop_p3_writer","restore_task_inventory","restore_8898_entrypoint",
        "verify_legacy_single_writers","preserve_evidence"],
      "apply_allowed":False,"production_mutated":False}
    raw=json.dumps(body,ensure_ascii=False,sort_keys=True,separators=(",",":"))
    return {**body,"package_id":"cutpkg1-"+hashlib.sha256(raw.encode()).hexdigest()[:24],
            "ready_for_authorization":all(gates.values())}
