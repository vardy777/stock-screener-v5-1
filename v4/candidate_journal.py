"""Immutable audit trail linking the 09:25 pool to the final 14:50 decision."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable

from .decision_contracts import ConfirmationDecisionV1, MorningPoolV1
from .execution import CHINA_TZ
from .offline_storage import atomic_json_write, exclusive_file_lock


ROOT = Path(__file__).resolve().parent.parent
JOURNAL_DIR = ROOT / "v4" / "data" / "candidate_journal"


class CandidateJournal:
    def __init__(self, directory: Path | None = None):
        self.directory = Path(directory) if directory else JOURNAL_DIR

    def path_for(self, trade_date: str) -> Path:
        return self.directory / f"{trade_date}.json"

    def load(self, trade_date: str) -> Dict[str, Any]:
        path = self.path_for(trade_date)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if data.get("trade_date") == trade_date else {}
        except (OSError, ValueError, TypeError):
            return {}

    def load_latest(self) -> Dict[str, Any]:
        paths = sorted(self.directory.glob("*.json")) if self.directory.exists() else []
        if not paths:
            return {}
        return self.load(paths[-1].stem)

    def morning(self, trade_date: str) -> dict:
        return dict(self.load(trade_date).get("morning", {}) or {})

    def confirmation(self, trade_date: str) -> dict:
        return dict(self.load(trade_date).get("confirmation", {}) or {})

    def _write(self, trade_date: str, payload: Dict[str, Any]) -> None:
        atomic_json_write(self.path_for(trade_date),payload)

    @staticmethod
    def _now() -> datetime:
        return datetime.now(CHINA_TZ)

    def save_morning(self, trade_date: str, candidates: Iterable[dict], market_state: dict, *, captured_at=None) -> dict:
        rows = [dict(item) for item in candidates if item.get("v4_candidate_origin") == "V4"]
        entity = MorningPoolV1.build(trade_date, captured_at or self._now(), rows, market_state)
        with exclusive_file_lock(self.directory/f".{trade_date}.lock"):
            payload = self.load(trade_date) or {"trade_date": trade_date}
            existing = payload.get("morning", {})
            if existing:
                if existing.get("pool_id") == entity.pool_id: return payload
                raise ValueError("morning pool is immutable for this trade date")
            if payload.get("confirmation"): raise ValueError("cannot create morning pool after confirmation decision")
            payload["morning"] = entity.to_dict(); self._write(trade_date, payload); return payload

    def morning_candidates(self, trade_date: str) -> list[dict]:
        return list(self.morning(trade_date).get("candidates", []))

    def has_morning(self, trade_date: str) -> bool:
        return "morning" in self.load(trade_date)

    def link_confirmation_candidates(self, trade_date: str, candidates: Iterable[dict]) -> list[dict]:
        payload = self.load(trade_date)
        if not payload.get("morning"):
            raise ValueError("missing current-session 09:25 mother pool")
        morning = {item.get("code"): item for item in payload["morning"].get("candidates", [])}
        rows = []
        for item in candidates:
            code = item.get("code")
            if code not in morning:
                raise ValueError(f"confirmation candidate {code} is outside morning pool")
            linked = dict(item)
            linked.update({
                "morning_pool_member": True,
                "morning_pool_id": payload["morning"].get("pool_id"),
                "morning_rank": morning[code].get("rank"),
                "morning_score": morning[code].get("score"),
                "morning_quote_time": morning[code].get("quote_time"),
                "linkage_status": "confirmed_from_morning_pool",
            })
            rows.append(linked)
        return rows

    def save_confirmation(self, trade_date: str, candidates: Iterable[dict], market_state: dict, *, decided_at=None, feature_context_id="") -> dict:
        with exclusive_file_lock(self.directory/f".{trade_date}.lock"):
            payload = self.load(trade_date)
            if not payload.get("morning"): raise ValueError("missing current-session 09:25 mother pool")
            morning_codes={x.get("code") for x in payload["morning"].get("candidates",[])}
            rows=[]
            for item in candidates:
                if item.get("code") not in morning_codes: raise ValueError(f"confirmation candidate {item.get('code')} is outside morning pool")
                morning_row=next(x for x in payload["morning"]["candidates"] if x.get("code")==item.get("code"))
                rows.append({**dict(item),"morning_pool_member":True,"morning_pool_id":payload["morning"].get("pool_id"),
                    "morning_rank":morning_row.get("rank"),"morning_score":morning_row.get("score"),
                    "morning_quote_time":morning_row.get("quote_time"),"linkage_status":"confirmed_from_morning_pool"})
            morning_data = payload["morning"]
            morning = MorningPoolV1(
                pool_id=morning_data["pool_id"], trade_date=morning_data["trade_date"],
                captured_at=morning_data["captured_at"],
                candidate_codes=tuple(morning_data.get("candidate_codes", morning_data.get("codes", []))),
                candidates=tuple(morning_data.get("candidates", [])),
                market_state=dict(morning_data.get("market_state", {})),
                lineage=dict(morning_data.get("lineage", {})),
                schema_version=morning_data.get("schema_version", "morning-pool-v1"),
            )
            entity = ConfirmationDecisionV1.build(morning, decided_at or self._now(), rows, market_state,
                                                  feature_context_id=feature_context_id)
            existing = payload.get("confirmation", {})
            if existing:
                if existing.get("decision_id") == entity.decision_id: return payload
                raise ValueError("confirmation decision is immutable for this trade date")
            payload["confirmation"] = entity.to_dict(); self._write(trade_date, payload); return payload

    def save_missing_morning_confirmation(self, trade_date: str, market_state: dict) -> dict:
        entity = ConfirmationDecisionV1.blocked_without_morning(
            trade_date, self._now(), market_state
        )
        with exclusive_file_lock(self.directory/f".{trade_date}.lock"):
            payload = self.load(trade_date) or {"trade_date": trade_date}
            if payload.get("morning"): raise ValueError("morning pool exists; use normal confirmation")
            existing = payload.get("confirmation", {})
            if existing:
                if existing.get("decision_id") == entity.decision_id: return payload
                raise ValueError("confirmation decision is immutable for this trade date")
            payload["confirmation"] = entity.to_dict(); self._write(trade_date, payload); return payload
