"""Persistent audit trail linking the 09:25 pool to the 14:50 decision."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable


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

    def _write(self, trade_date: str, payload: Dict[str, Any]) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        path = self.path_for(trade_date)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(path)

    def save_morning(self, trade_date: str, candidates: Iterable[dict], market_state: dict) -> dict:
        rows = [dict(item) for item in candidates if item.get("v4_candidate_origin") == "V4"]
        payload = self.load(trade_date) or {"trade_date": trade_date}
        payload["morning"] = {
            "captured_at": datetime.now().isoformat(timespec="seconds"),
            "codes": [item.get("code") for item in rows],
            "candidates": rows,
            "market_state": market_state,
        }
        payload.pop("confirmation", None)
        self._write(trade_date, payload)
        return payload

    def morning_candidates(self, trade_date: str) -> list[dict]:
        return list(self.load(trade_date).get("morning", {}).get("candidates", []))

    def has_morning(self, trade_date: str) -> bool:
        """Return true even when the valid morning observation conclusion is empty."""
        return "morning" in self.load(trade_date)

    def save_confirmation(self, trade_date: str, candidates: Iterable[dict], market_state: dict) -> dict:
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
                "morning_rank": morning[code].get("rank"),
                "morning_score": morning[code].get("score"),
                "morning_quote_time": morning[code].get("quote_time"),
                "linkage_status": "confirmed_from_morning_pool",
            })
            rows.append(linked)
        payload["confirmation"] = {
            "captured_at": datetime.now().isoformat(timespec="seconds"),
            "codes": [item.get("code") for item in rows],
            "candidates": rows,
            "market_state": market_state,
            "mother_pool_size": len(morning),
        }
        self._write(trade_date, payload)
        return payload
