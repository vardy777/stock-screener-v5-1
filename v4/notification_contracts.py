"""Immutable, content-addressed notification transport receipts."""
from __future__ import annotations
from dataclasses import asdict,dataclass
from datetime import datetime
import hashlib,json

VERSION="notification-receipt-v1"

def _hash(value): return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode()).hexdigest()

@dataclass(frozen=True)
class NotificationReceiptV1:
    notification_id:str; message_key:str; parent_entity_id:str; payload_sha256:str
    outcome:str; response_code:int; transport_request_id:str; attempt:int; recorded_at:str
    schema_version:str=VERSION

    @classmethod
    def build(cls,*,message_key,parent_entity_id,payload_sha256,outcome,response_code,
              transport_request_id,attempt,recorded_at):
        timestamp=recorded_at if isinstance(recorded_at,datetime) else datetime.fromisoformat(str(recorded_at))
        if timestamp.tzinfo is None or timestamp.utcoffset() is None: raise ValueError("notification: timezone required")
        if not str(parent_entity_id).startswith(("mp-","cd-")): raise ValueError("notification: parent entity required")
        if len(str(payload_sha256))!=64: raise ValueError("notification: payload hash required")
        if outcome not in {"ACCEPTED","REJECTED","OUTCOME_UNKNOWN"}: raise ValueError("notification: invalid outcome")
        if int(attempt) < 1: raise ValueError("notification: positive attempt required")
        body={"schema_version":VERSION,"message_key":str(message_key),"parent_entity_id":str(parent_entity_id),
          "payload_sha256":str(payload_sha256),"outcome":outcome,"response_code":int(response_code or 0),
          "transport_request_id":str(transport_request_id or ""),"attempt":int(attempt),
          "recorded_at":timestamp.isoformat(timespec="seconds")}
        return cls("notification1-"+_hash(body)[:24],**{k:v for k,v in body.items() if k!="schema_version"})

    def to_dict(self): return asdict(self)
    def verify(self):
        body=self.to_dict(); body.pop("notification_id")
        if self.schema_version!=VERSION or self.notification_id!="notification1-"+_hash(body)[:24]: raise ValueError("notification: content hash mismatch")
        return self
    @classmethod
    def from_mapping(cls,value): return cls(**dict(value)).verify()
