"""Deterministic P3/P4/P5 cutover plan and fail-closed readiness report."""

from __future__ import annotations

import hashlib,json
from pathlib import Path

from .p3_migration import LegacyAccountValidator
from .p4_deployment import full_offline_task_manifest


def _hash(value):
    return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode()).hexdigest()


def task_diff(project_root: Path, installed_tasks: list[dict]) -> dict:
    expected=full_offline_task_manifest(project_root)["tasks"]
    installed={str(x.get("task_name",x.get("name",""))):x for x in installed_tasks}
    rows=[]
    for item in expected:
        current=installed.get(item["windows_task_name"])
        command_match=False
        if current is not None:
            actual=str(current.get("command","")); command_match=all(token.lower() in actual.lower() for token in str(item["command"]).split())
        rows.append({"task_name":item["task_name"],"status":"MISSING" if current is None else
                     ("MATCH" if command_match and current.get("at")==item["at"] else "DIFFERENT"),
                     "expected":item,"installed":current or {}})
    extras=sorted(set(installed)-{x["windows_task_name"] for x in expected})
    return {"schema_version":"cutover-task-diff-v1","rows":rows,"extra_tasks":extras,
            "passed":all(x["status"]=="MATCH" for x in rows) and not extras,"read_only":True}


def validate_writer_inventory(writers: list[dict], *, target=False) -> dict:
    expected={"candidate_decision":"P2","paper_account":"P3" if target else "legacy_production",
              "task_receipts":"P4" if target else "legacy_phase1_scripts"}
    grouped={key:[] for key in expected}
    for row in writers:
        resource=str(row.get("resource",""))
        if resource in grouped and row.get("active") is True: grouped[resource].append(str(row.get("owner","")))
    checks=[]
    for resource,owner in expected.items():
        actual=grouped[resource]; checks.append({"resource":resource,"expected_owner":owner,"active_owners":actual,
            "passed":actual==[owner]})
    return {"schema_version":"writer-inventory-audit-v1","target_mode":bool(target),"checks":checks,
            "passed":all(x["passed"] for x in checks),"read_only":True}


def build_cutover_readiness(*, project_root: Path, live_acceptance: dict, legacy_account_path: Path,
                            installed_tasks: list[dict], backup_verification: dict, writers: list[dict] | None = None) -> dict:
    account=LegacyAccountValidator().validate(legacy_account_path)
    tasks=task_diff(project_root,installed_tasks)
    current_writers=validate_writer_inventory(writers or [],target=False)
    gates=[
        {"gate":"live_windows","passed":live_acceptance.get("passed") is True},
        {"gate":"legacy_account","passed":account.get("cutover_eligible") is True},
        {"gate":"backup_verified","passed":backup_verification.get("passed") is True},
        {"gate":"task_target_diff_clean","passed":tasks["passed"]},
        {"gate":"current_single_writers","passed":current_writers["passed"]},
        {"gate":"production_authorization","passed":False},
    ]
    sequence=["capture_pre_cutover_manifest","stop_old_writers","verify_old_writers_stopped",
              "initialize_p3_account_once","install_p4_tasks_disabled","enable_p4_owner",
              "smoke_test_read_only","switch_8898_to_p5","verify_single_writers"]
    rollback=["disable_new_p4_tasks","stop_p3_writer","restore_previous_task_definitions",
              "restore_8898_previous_entrypoint","verify_no_dual_writers","preserve_failed_cutover_evidence"]
    body={"schema_version":"p3-p5-cutover-readiness-v1","gates":gates,"account":account,"task_diff":tasks,"writer_inventory":current_writers,
          "sequence":sequence,"rollback":rollback,"ownership_target":{"decision":"P2","account_execution":"P3",
          "scheduler_notifications":"P4","dashboard":"P5"},"apply_allowed":False,"production_mutated":False}
    return {**body,"ready":all(x["passed"] for x in gates),"plan_id":"cut1-"+_hash(body)[:24]}
