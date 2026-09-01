"""Content-addressed evidence for the V5.1 security master."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
import base64
import hashlib
import json
from pathlib import Path

from shared_core.core import ContractViolation,strict_int,strict_str,strict_enum
from .facts import content_id, save_immutable
from .security_master import aware

NORMALIZATION_VERSION = "v5.1-master-normalization-v1"


@dataclass(frozen=True)
class DirectoryResponseFactV51:
    provider_family: str
    exchange: str
    endpoint: str
    retrieved_at: str
    raw_sha256: str
    raw_content_b64: str
    record_count: int
    normalization_version: str = NORMALIZATION_VERSION
    schema_version: str = "v5.1-directory-response-v1"

    @classmethod
    def build(cls, **row):
        family = strict_str(row.get("provider_family"),"provider_family").strip().lower()
        exchange = strict_enum(row.get("exchange"),"exchange",{"SSE","SZSE","ALL"})
        endpoint = strict_str(row.get("endpoint"),"endpoint").strip()
        retrieved_at = aware(row.get("retrieved_at"), "retrieved_at").isoformat()
        digest = strict_str(row.get("raw_sha256"),"raw_sha256").lower()
        raw_content = strict_str(row.get("raw_content_b64"),"raw_content_b64")
        count = strict_int(row.get("record_count"),"record_count",0)
        if not family or exchange not in {"SSE", "SZSE", "ALL"} or not endpoint:
            raise ContractViolation("directory response identity invalid")
        if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
            raise ContractViolation("directory response raw sha256 invalid")
        try: raw_bytes = base64.b64decode(raw_content, validate=True)
        except Exception as exc: raise ContractViolation("directory response raw content invalid") from exc
        if not raw_bytes or hashlib.sha256(raw_bytes).hexdigest() != digest:
            raise ContractViolation("directory response raw content/hash mismatch")
        if count < 0:
            raise ContractViolation("directory response record count invalid")
        return cls(family, exchange, endpoint, retrieved_at, digest, raw_content, count)

    @property
    def response_id(self):
        return content_id("v51dirresponse1", asdict(self))

    def to_dict(self):
        return {**asdict(self), "response_id": self.response_id}


@dataclass(frozen=True)
class MasterMatchFactV51:
    symbol: str
    exchange: str
    official_response_id: str
    third_party_response_id: str | None
    official_name: str
    official_listing_date: str
    third_party_name: str | None
    third_party_listing_date: str | None
    outcome: str
    matched_at: str
    normalization_version: str = NORMALIZATION_VERSION
    schema_version: str = "v5.1-master-match-v1"

    @classmethod
    def build(cls, **row):
        symbol = strict_str(row.get("symbol"),"symbol")
        exchange = strict_enum(row.get("exchange"),"exchange",{"SSE","SZSE"})
        outcome = strict_enum(row.get("outcome"),"outcome",{"MATCH","THIRD_PARTY_UNAVAILABLE","THIRD_PARTY_MISSING","CONFLICT"})
        official_id = strict_str(row.get("official_response_id"),"official_response_id")
        raw_third_id=row.get("third_party_response_id");third_id=None if raw_third_id is None else strict_str(raw_third_id,"third_party_response_id")
        official_name = strict_str(row.get("official_name"),"official_name").strip()
        official_date = strict_str(row.get("official_listing_date"),"official_listing_date")
        if len(symbol) != 6 or not symbol.isdigit() or exchange not in {"SSE", "SZSE"}:
            raise ContractViolation("master match symbol invalid")
        if not official_id.startswith("v51dirresponse1-") or not official_name:
            raise ContractViolation("master match official lineage invalid")
        if outcome in {"MATCH", "THIRD_PARTY_MISSING", "CONFLICT"} and not third_id:
            raise ContractViolation("master match third-party lineage required")
        third_name=row.get("third_party_name");third_date=row.get("third_party_listing_date")
        if third_name is not None:third_name=strict_str(third_name,"third_party_name")
        if third_date is not None:third_date=strict_str(third_date,"third_party_listing_date")
        return cls(symbol, exchange, official_id, third_id, official_name, official_date,
                   third_name,third_date,
                   outcome, aware(row.get("matched_at"), "matched_at").isoformat())

    @property
    def match_id(self):
        return content_id("v51mastermatch1", asdict(self))

    def to_dict(self):
        return {**asdict(self), "match_id": self.match_id}


class MasterEvidenceRepository:
    def __init__(self, root):
        self.root = Path(root)

    def save_response(self, fact):
        if not isinstance(fact, DirectoryResponseFactV51):
            raise ContractViolation("directory response fact required")
        return save_immutable(self.root / "security_master/evidence/responses" / f"{fact.response_id}.json", fact.to_dict())

    def save_match(self, fact):
        if not isinstance(fact, MasterMatchFactV51):
            raise ContractViolation("master match fact required")
        responses = self.responses()
        if fact.official_response_id not in responses or (fact.third_party_response_id and fact.third_party_response_id not in responses):
            raise ContractViolation("master match references missing response")
        return save_immutable(self.root / "security_master/evidence/matches" / fact.symbol / f"{fact.match_id}.json", fact.to_dict())

    def responses(self):
        result = {}
        folder = self.root / "security_master/evidence/responses"
        for path in folder.glob("*.json") if folder.exists() else ():
            row = json.loads(path.read_text(encoding="utf-8")); declared = row.pop("response_id", "")
            if set(row)!=set(DirectoryResponseFactV51.__dataclass_fields__):raise ContractViolation("directory response persisted keys invalid")
            fact = DirectoryResponseFactV51.build(**row)
            if declared != fact.response_id or path.stem != fact.response_id:
                raise ContractViolation("directory response content-address mismatch")
            result[fact.response_id] = fact
        return result

    def matches(self):
        result = {}
        folder = self.root / "security_master/evidence/matches"
        for path in folder.glob("*/*.json") if folder.exists() else ():
            row = json.loads(path.read_text(encoding="utf-8")); declared = row.pop("match_id", "")
            if set(row)!=set(MasterMatchFactV51.__dataclass_fields__):raise ContractViolation("master match persisted keys invalid")
            fact = MasterMatchFactV51.build(**row)
            if declared != fact.match_id or path.stem != fact.match_id:
                raise ContractViolation("master match content-address mismatch")
            if fact.match_id in result:
                raise ContractViolation("duplicate master match identity")
            result[fact.match_id] = fact
        return result

    def resolve(self, response_ids, match_ids, master_versions):
        responses = self.responses(); matches = self.matches()
        if set(response_ids) - set(responses) or set(match_ids) - set(matches):
            raise ContractViolation("master verification references missing evidence")
        selected = [matches[x] for x in match_ids]
        symbols = [x.symbol for x in selected]
        if len(symbols) != len(set(symbols)):
            raise ContractViolation("master verification duplicate symbol match")
        if set(symbols) != {x.symbol for x in master_versions}:
            raise ContractViolation("master verification match/version coverage mismatch")
        if any(x.outcome == "CONFLICT" for x in selected):
            raise ContractViolation("master verification contains identity conflict")
        for match in selected:
            official = responses[match.official_response_id]
            if official.provider_family != match.exchange.lower():
                raise ContractViolation("master match official family/exchange mismatch")
            if match.third_party_response_id and responses[match.third_party_response_id].provider_family == official.provider_family:
                raise ContractViolation("same-family alias is not independent verification")
        return True
