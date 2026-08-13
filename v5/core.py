"""V5-owned foundational contracts.  No V4 runtime dependency is allowed."""
from __future__ import annotations
from datetime import timedelta,timezone

CHINA_TZ=timezone(timedelta(hours=8),name="Asia/Shanghai")

class ContractViolation(ValueError):
    pass

def is_market_snapshot(value)->bool:
    """Structural boundary for versioned immutable market snapshots.

    During migration this accepts a V4 snapshot object without importing V4;
    native V5 snapshots will satisfy the same public shape.
    """
    return (getattr(value,"schema_version","")=="market-snapshot-v1"
            and str(getattr(value,"snapshot_id","")).startswith("ms1-")
            and hasattr(value,"quality") and hasattr(value,"quotes"))
