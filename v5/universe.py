"""Versioned V5 point-in-time universe facts."""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
import hashlib,json
from pathlib import Path
from typing import Iterable
from .core import CHINA_TZ,ContractViolation

def eligible(code):
    return code.startswith(("000","001","002","003","30","600","601","603","605"))
@dataclass(frozen=True)
class UniverseV1:
    trade_date:str;created_at:str;codes:tuple[str,...];sources:tuple[str,...];schema_version:str="v5-universe-v1"
    @classmethod
    def build(cls,*,trade_date,created_at,codes:Iterable[str],sources:Iterable[str]):
        if created_at.tzinfo is None:raise ContractViolation("universe created_at timezone required")
        values=tuple(sorted({str(x).zfill(6) for x in codes if eligible(str(x).zfill(6))}));origins=tuple(sorted({str(x) for x in sources if str(x)}))
        if not values or not origins:raise ContractViolation("universe codes/sources required")
        return cls(str(trade_date),created_at.astimezone(CHINA_TZ).isoformat(timespec="seconds"),values,origins)
    @property
    def universe_id(self):
        payload={"schema_version":self.schema_version,"trade_date":self.trade_date,"created_at":self.created_at,"codes":list(self.codes),"sources":list(self.sources)}
        return "univ1-"+hashlib.sha256(json.dumps(payload,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode()).hexdigest()
    def to_dict(self):return {"schema_version":self.schema_version,"universe_id":self.universe_id,"trade_date":self.trade_date,"created_at":self.created_at,"codes":list(self.codes),"sources":list(self.sources),"count":len(self.codes)}
    def save(self,root):
        path=Path(root)/"universes"/self.trade_date/f"{self.universe_id}.json";path.parent.mkdir(parents=True,exist_ok=True);raw=json.dumps(self.to_dict(),ensure_ascii=False,sort_keys=True,separators=(",",":"))
        if path.exists() and path.read_text(encoding="utf-8")!=raw:raise ContractViolation("universe immutable collision")
        if not path.exists():path.write_text(raw,encoding="utf-8")
        return path
    @classmethod
    def from_mapping(cls,value):return cls(value["trade_date"],value["created_at"],tuple(value["codes"]),tuple(value["sources"]))

def import_archive_seed(daily_dir,*,trade_date,created_at):
    """Explicit one-time migration boundary; runtime consumes saved V5 facts."""
    codes=[path.stem for path in Path(daily_dir).glob("*.csv")]
    return UniverseV1.build(trade_date=trade_date,created_at=created_at,codes=codes,sources=["legacy_daily_archive_seed_migration"])
