"""V5-owned foundational contracts.  No V4 runtime dependency is allowed."""
from __future__ import annotations
from datetime import timedelta,timezone

CHINA_TZ=timezone(timedelta(hours=8),name="Asia/Shanghai")

class ContractViolation(ValueError):
    pass

def is_market_snapshot(value)->bool:
    """Structural boundary for versioned immutable market snapshots.

    V5 owns its native schema.  The legacy schema remains structurally readable
    only for explicit replay/migration adapters, never by importing V4 runtime.
    """
    return (getattr(value,"schema_version","") in {"v5-market-snapshot-v1","market-snapshot-v1"}
            and str(getattr(value,"snapshot_id","")).startswith("ms1-")
            and hasattr(value,"quality") and hasattr(value,"quotes"))
