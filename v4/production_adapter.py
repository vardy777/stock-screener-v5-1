"""Dormant thin entrypoint shared by future P3/P4 scheduled tasks."""
from __future__ import annotations
from datetime import datetime
from pathlib import Path
from .execution import CHINA_TZ
from .production_gate import ProductionGateError, require_authorized_owner
from .task_output_contract import TaskOutputV1


def run_disabled(task_name: str, *, trade_date: str, authorization_file: Path | None=None,
                 execute=None, now=None):
    """Execute only after explicit ownership authorization and injected implementation.

    No legacy engine is imported here.  The production implementation remains
    deliberately unbound until live-window acceptance and cutover authorization.
    """
    timestamp=now or datetime.now(CHINA_TZ)
    owner="P3" if task_name in {"paper_buy","paper_sell"} else "P4"
    resource="paper_account" if owner=="P3" else "task_receipts"
    if authorization_file is None:
        return TaskOutputV1.build(task_name=task_name,trade_date=trade_date,status="BLOCKED",
            reason_code="PRODUCTION_ADAPTER_DISABLED",recorded_at=timestamp)
    try:
        lease=require_authorized_owner(authorization_file,resource=resource,owner=owner)
    except ProductionGateError as exc:
        return TaskOutputV1.build(task_name=task_name,trade_date=trade_date,status="BLOCKED",
            reason_code=str(exc),recorded_at=timestamp)
    if execute is None:
        return TaskOutputV1.build(task_name=task_name,trade_date=trade_date,status="BLOCKED",
            reason_code="PRODUCTION_IMPLEMENTATION_UNBOUND",recorded_at=timestamp,
            input_ids=(lease.authorization_id,))
    return execute(lease)
