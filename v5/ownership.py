"""Fail-closed V5 production ownership contract."""
from __future__ import annotations
import json
from pathlib import Path
from .core import ContractViolation
OWNERS=("v4","v5")
def load(path):
    p=Path(path)
    if not p.exists():return {"schema_version":"v5-ownership-v1","paper_writer":"v4","scheduler":"v4","dashboard":"v4","notifications":"v5","authorized":False}
    value=json.loads(p.read_text(encoding="utf-8"))
    if value.get("schema_version")!="v5-ownership-v1" or any(value.get(k) not in OWNERS for k in ("paper_writer","scheduler","dashboard","notifications")):raise ContractViolation("ownership contract invalid")
    return value
def require(path,capability):
    value=load(path)
    if value.get(capability)!="v5" or value.get("authorized") is not True:raise ContractViolation(f"V5 does not own {capability}")
    return value
