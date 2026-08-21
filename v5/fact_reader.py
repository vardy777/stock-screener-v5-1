"""Deterministic readers for immutable V5 facts; hashes never imply recency."""
from __future__ import annotations
from datetime import datetime
import json
from pathlib import Path
from .core import ContractViolation

TIME_FIELDS={"acquisition":"requested_at","morning_pools":"created_at","confirmations":"decided_at","recovery_observations":"observed_at"}

def rows(root,kind,day):
    directory=Path(root)/kind/day
    return [(path,json.loads(path.read_text(encoding="utf-8"))) for path in directory.glob("*.json")] if directory.exists() else []

def latest(root,kind,day,*,predicate=None,time_field=None,as_of=None):
    values=[item for item in rows(root,kind,day) if predicate is None or predicate(item[1])]
    if not values:raise ContractViolation(f"V5 {kind} fact missing")
    field=time_field or TIME_FIELDS.get(kind)
    if not field:raise ContractViolation(f"V5 {kind} latest time field unspecified")
    def key(item):
        try:value=datetime.fromisoformat(str(item[1].get(field)))
        except (TypeError,ValueError) as exc:raise ContractViolation(f"V5 {kind} {field} invalid") from exc
        if value.tzinfo is None or value.utcoffset() is None:raise ContractViolation(f"V5 {kind} {field} timezone required")
        return value,item[0].name
    if as_of is not None:
        if as_of.tzinfo is None or as_of.utcoffset() is None:raise ContractViolation("V5 fact as_of timezone required")
        values=[item for item in values if key(item)[0]<=as_of]
        if not values:raise ContractViolation(f"causal V5 {kind} fact missing")
    return max(values,key=key)[1]
