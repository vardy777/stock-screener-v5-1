"""V5-owned foundational contracts.  No V4 runtime dependency is allowed."""
from __future__ import annotations
from datetime import timedelta,timezone

CHINA_TZ=timezone(timedelta(hours=8),name="Asia/Shanghai")

class ContractViolation(ValueError):
    pass

def strict_bool(value,field):
    if type(value) is not bool:raise ContractViolation(f"{field}: strict boolean required")
    return value

def strict_int(value,field,minimum=None):
    if type(value) is not int:raise ContractViolation(f"{field}: strict integer required")
    if minimum is not None and value<minimum:raise ContractViolation(f"{field}: out of range")
    return value

def strict_number(value,field):
    if type(value) not in {int,float}:raise ContractViolation(f"{field}: strict number required")
    result=float(value)
    if result!=result or result in {float("inf"),float("-inf")}:raise ContractViolation(f"{field}: out of range")
    return result

def strict_str(value,field,*,allow_empty=False):
    if type(value) is not str:raise ContractViolation(f"{field}: strict string required")
    if not allow_empty and not value:raise ContractViolation(f"{field}: non-empty string required")
    return value

def strict_enum(value,field,allowed):
    strict_str(value,field)
    if value not in allowed:raise ContractViolation(f"{field}: unsupported value")
    return value

def is_market_snapshot(value)->bool:
    """Structural boundary for versioned immutable market snapshots.

    V5 owns its native schema.  The legacy schema remains structurally readable
    only for explicit replay/migration adapters, never by importing V4 runtime.
    """
    return (getattr(value,"schema_version","") in {"v5-market-snapshot-v1","market-snapshot-v1"}
            and str(getattr(value,"snapshot_id","")).startswith("ms1-")
            and hasattr(value,"quality") and hasattr(value,"quotes"))
