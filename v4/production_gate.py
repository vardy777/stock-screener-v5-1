"""Fail-closed authorization and single-writer gate for dormant adapters."""
from __future__ import annotations
import hashlib, json
from dataclasses import dataclass
from pathlib import Path


class ProductionGateError(RuntimeError): pass


def _hash(value):
    raw=json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


@dataclass(frozen=True)
class WriterLeaseV1:
    resource: str
    owner: str
    authorization_id: str
    manifest_sha256: str


def require_authorized_owner(path: Path, *, resource: str, owner: str) -> WriterLeaseV1:
    """Read an explicit create-once authorization; absence always blocks."""
    try:
        raw=Path(path).read_bytes(); value=json.loads(raw.decode("utf-8"))
    except (OSError,UnicodeError,json.JSONDecodeError) as exc:
        raise ProductionGateError("PRODUCTION_AUTHORIZATION_MISSING_OR_INVALID") from exc
    if value.get("schema_version")!="production-authorization-v1" or value.get("apply_allowed") is not True:
        raise ProductionGateError("PRODUCTION_AUTHORIZATION_NOT_GRANTED")
    owners=value.get("owners",{})
    if owners.get(resource)!=owner:
        raise ProductionGateError(f"WRITER_OWNER_MISMATCH:{resource}")
    active=[x for x in value.get("writers",[]) if x.get("resource")==resource and x.get("active") is True]
    if active!=[{"resource":resource,"owner":owner,"active":True}]:
        raise ProductionGateError(f"SINGLE_WRITER_GATE_FAILED:{resource}")
    return WriterLeaseV1(resource,owner,str(value.get("authorization_id","")),hashlib.sha256(raw).hexdigest())
