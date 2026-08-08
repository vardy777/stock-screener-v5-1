"""Isolated event-sourced paper account for P3 offline development only."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable

from strategy_spec import DEFAULT_SPEC
from .p3_contracts import PaperContractViolation, PaperFillV1, PaperRoundTripV1


class OfflinePaperLedger:
    def __init__(self, directory: Path, *, initial_cash: float = 100_000.0):
        self.directory = Path(directory)
        self.initial_cash = float(initial_cash)
        if self.initial_cash <= 0:
            raise ValueError("initial_cash must be positive")
        self.path = self.directory / "paper_fills.jsonl"

    def fills(self) -> list[dict]:
        if not self.path.exists():
            return []
        try:
            rows = [
                json.loads(line)
                for line in self.path.read_text(encoding="utf-8").splitlines()
                if line
            ]
        except (OSError, json.JSONDecodeError) as exc:
            raise PaperContractViolation("ledger: unreadable or invalid JSON") from exc
        return [PaperFillV1.from_mapping(row).to_dict() for row in rows]

    def _state(self, extra: Iterable[dict] = ()) -> dict:
        cash = self.initial_cash
        positions: dict[str, dict] = {}
        for fill in [*self.fills(), *extra]:
            cash += float(fill["cash_flow"])
            code = fill["code"]
            if fill["side"] == "BUY":
                if code in positions:
                    raise PaperContractViolation("duplicate open position")
                positions[code] = fill
            else:
                position = positions.get(code)
                if not position or position["shares"] != fill["shares"]:
                    raise PaperContractViolation("sell without matching position")
                if fill["trade_date"] < position["eligible_sell_date"]:
                    raise PaperContractViolation("sell before T+1 eligibility")
                positions.pop(code)
        return {"cash": round(cash, 6), "positions": positions}

    def append(self, fill: PaperFillV1) -> bool:
        if not isinstance(fill, PaperFillV1):
            raise PaperContractViolation("fill: PaperFillV1 required")
        existing = self.fills()
        if any(item["fill_id"] == fill.fill_id for item in existing):
            return False
        if fill.side == "BUY":
            if any(item["decision_id"] == fill.decision_id and item["side"] == "BUY" for item in existing):
                raise PaperContractViolation("decision already filled")
            state = self._state()
            equity_at_cost = state["cash"] + sum(
                float(item["notional"]) for item in state["positions"].values()
            )
            if -fill.cash_flow > equity_at_cost * DEFAULT_SPEC.max_position_fraction + 0.01:
                raise PaperContractViolation("position exceeds one-third cap")
        projected = self._state([fill.to_dict()])
        if projected["cash"] < -0.001:
            raise PaperContractViolation("insufficient cash")
        self.directory.mkdir(parents=True, exist_ok=True)
        lines = existing + [fill.to_dict()]
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(
            "".join(json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n" for item in lines),
            encoding="utf-8",
        )
        temporary.replace(self.path)
        return True

    def snapshot(self) -> dict:
        state = self._state()
        return {
            "initial_cash": self.initial_cash,
            "cash": state["cash"],
            "positions": list(state["positions"].values()),
            "fill_count": len(self.fills()),
        }

    def round_trips(self) -> list[dict]:
        buys = {}
        result = []
        for raw in self.fills():
            fill = PaperFillV1.from_mapping(raw)
            if fill.side == "BUY":
                buys[fill.code] = fill
            else:
                result.append(PaperRoundTripV1.build(buys.pop(fill.code), fill).to_dict())
        return result

    def reconcile(self) -> dict:
        fills = self.fills()
        snapshot = self.snapshot()
        expected_cash = round(
            self.initial_cash + sum(float(item["cash_flow"]) for item in fills), 6
        )
        open_codes = {
            item["code"] for item in fills if item["side"] == "BUY"
        } - {
            item["code"] for item in fills if item["side"] == "SELL"
        }
        position_codes = {item["code"] for item in snapshot["positions"]}
        trips = self.round_trips()
        checks = {
            "cash_matches_fills": abs(snapshot["cash"] - expected_cash) <= 0.000001,
            "positions_match_fills": position_codes == open_codes,
            "fill_ids_unique": len({item["fill_id"] for item in fills}) == len(fills),
            "round_trips_match_sells": len(trips) == sum(item["side"] == "SELL" for item in fills),
        }
        if not snapshot["positions"]:
            checks["flat_pnl_matches_cash"] = abs(
                sum(float(item["net_pnl"]) for item in trips)
                - (snapshot["cash"] - self.initial_cash)
            ) <= 0.000001
        return {
            "schema_version": "paper-account-reconciliation-v1",
            "passed": all(checks.values()), "checks": checks,
            "fill_count": len(fills), "round_trip_count": len(trips),
            "cash": snapshot["cash"], "expected_cash": expected_cash,
        }
