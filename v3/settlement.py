"""Persistent compatibility settlement summary for ``v3-settle``.

This journal is deliberately separate from the V4 simulation account.  It
restores the legacy reporting command without creating orders or changing the
V4 research gate.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Dict, Optional

from v3.config import DATA_DIR


DEFAULT_STATE_PATH = Path(DATA_DIR) / "settlement_state.json"


class SettlementEngine:
    def __init__(self, path: Optional[str] = None):
        self.path = Path(path) if path else DEFAULT_STATE_PATH
        self.data = self._load()

    def _load(self) -> Dict:
        try:
            with self.path.open("r", encoding="utf-8") as handle:
                payload = json.load(handle)
            if isinstance(payload, dict) and isinstance(payload.get("trades"), list):
                return payload
        except (OSError, TypeError, ValueError):
            pass
        return {"version": 1, "trades": []}

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        with temporary.open("w", encoding="utf-8") as handle:
            json.dump(self.data, handle, ensure_ascii=False, indent=2)
        temporary.replace(self.path)

    def record(
        self,
        code: str,
        buy_price: float,
        sell_price: float,
        settled_on: Optional[str] = None,
    ) -> float:
        buy = float(buy_price)
        sell = float(sell_price)
        if buy <= 0 or sell <= 0:
            raise ValueError("buy_price and sell_price must be positive")
        day = settled_on or date.today().isoformat()
        normalized_code = str(code).strip().zfill(6)
        key = f"{day}|{normalized_code}|{buy:.6f}|{sell:.6f}"
        for trade in self.data["trades"]:
            if trade.get("key") == key:
                return float(trade.get("profit", 0.0))
        profit = (sell - buy) / buy * 100.0
        self.data["trades"].append(
            {
                "key": key,
                "date": day,
                "code": normalized_code,
                "buy_price": buy,
                "sell_price": sell,
                "profit": round(profit, 6),
            }
        )
        self._save()
        return profit

    def summary(self) -> Dict:
        details = list(self.data.get("trades", []))
        count = len(details)
        wins = sum(float(trade.get("profit", 0.0)) > 0 for trade in details)
        total_return = sum(float(trade.get("profit", 0.0)) for trade in details)
        return {
            "trades": count,
            "wins": wins,
            "win_rate": wins / count if count else 0.0,
            "total_return": total_return,
            "trades_detail": details,
        }

