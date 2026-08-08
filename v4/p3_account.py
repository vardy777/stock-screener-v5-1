"""Isolated event-sourced paper account for P3 offline development only."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Iterable

from strategy_spec import DEFAULT_SPEC
from .p3_contracts import (
    PaperContractViolation, PaperFillV1, PaperOrderIntentV1, PaperRoundTripV1,
)


LEDGER_VERSION = "offline-paper-ledger-v1"
GENESIS = "genesis"


def _event_id(sequence: int, previous_event_id: str, fill_id: str) -> str:
    raw = json.dumps(
        {"sequence": sequence, "previous_event_id": previous_event_id, "fill_id": fill_id},
        sort_keys=True, separators=(",", ":"),
    )
    return "pe-" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


class OfflineOrderJournal:
    def __init__(self, directory: Path):
        self.directory = Path(directory)
        self.path = self.directory / "paper_orders.json"

    def intents(self) -> list[dict]:
        if not self.path.exists():
            return []
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise PaperContractViolation("order journal: invalid JSON") from exc
        if payload.get("schema_version") != "offline-paper-orders-v1":
            raise PaperContractViolation("order journal: schema mismatch")
        rows = payload.get("intents", [])
        if payload.get("intent_count") != len(rows):
            raise PaperContractViolation("order journal: count mismatch")
        return [PaperOrderIntentV1.from_mapping(row).to_dict() for row in rows]

    def append(self, intent: PaperOrderIntentV1) -> bool:
        if not isinstance(intent, PaperOrderIntentV1):
            raise PaperContractViolation("intent: PaperOrderIntentV1 required")
        intent.verify()
        rows = self.intents()
        if any(row["intent_id"] == intent.intent_id for row in rows):
            return False
        rows.append(intent.to_dict())
        payload = {
            "schema_version": "offline-paper-orders-v1",
            "intent_count": len(rows), "intents": rows,
        }
        self.directory.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2),
            encoding="utf-8",
        )
        temporary.replace(self.path)
        return True


class OfflinePaperLedger:
    def __init__(self, directory: Path, *, initial_cash: float = 100_000.0):
        self.directory = Path(directory)
        self.initial_cash = float(initial_cash)
        if self.initial_cash <= 0:
            raise ValueError("initial_cash must be positive")
        self.path = self.directory / "paper_ledger.json"

    def _empty(self) -> dict:
        return {
            "schema_version": LEDGER_VERSION, "initial_cash": self.initial_cash,
            "event_count": 0, "head_event_id": GENESIS, "events": [],
        }

    def _load(self) -> dict:
        if not self.path.exists():
            return self._empty()
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise PaperContractViolation("ledger: unreadable or invalid JSON") from exc
        if payload.get("schema_version") != LEDGER_VERSION:
            raise PaperContractViolation("ledger: schema mismatch")
        if abs(float(payload.get("initial_cash", 0.0)) - self.initial_cash) > 0.000001:
            raise PaperContractViolation("ledger: initial cash mismatch")
        events = payload.get("events")
        if not isinstance(events, list) or payload.get("event_count") != len(events):
            raise PaperContractViolation("ledger: event count mismatch")
        previous = GENESIS
        for sequence, event in enumerate(events, start=1):
            fill = PaperFillV1.from_mapping(event.get("fill", {}))
            expected = _event_id(sequence, previous, fill.fill_id)
            if (
                event.get("sequence") != sequence
                or event.get("previous_event_id") != previous
                or event.get("event_id") != expected
            ):
                raise PaperContractViolation("ledger: event chain mismatch")
            previous = expected
        if payload.get("head_event_id") != previous:
            raise PaperContractViolation("ledger: head mismatch")
        return payload

    def fills(self) -> list[dict]:
        return [
            PaperFillV1.from_mapping(event["fill"]).to_dict()
            for event in self._load()["events"]
        ]

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
                if fill["decision_id"] != position["decision_id"]:
                    raise PaperContractViolation("sell decision does not match position")
                if fill["trade_date"] < position["eligible_sell_date"]:
                    raise PaperContractViolation("sell before T+1 eligibility")
                if fill["filled_at"] <= position["filled_at"]:
                    raise PaperContractViolation("sell timestamp is not after buy")
                positions.pop(code)
        return {"cash": round(cash, 6), "positions": positions}

    def append(self, fill: PaperFillV1) -> bool:
        if not isinstance(fill, PaperFillV1):
            raise PaperContractViolation("fill: PaperFillV1 required")
        fill.verify()
        payload = self._load()
        existing = [event["fill"] for event in payload["events"]]
        if any(item["fill_id"] == fill.fill_id for item in existing):
            return False
        if fill.side == "BUY":
            if any(item["decision_id"] == fill.decision_id and item["side"] == "BUY" for item in existing):
                raise PaperContractViolation("decision already filled")
            state = self._state()
            if len(state["positions"]) >= DEFAULT_SPEC.max_positions:
                raise PaperContractViolation("maximum position count reached")
            equity_at_cost = state["cash"] + sum(
                float(item["notional"]) for item in state["positions"].values()
            )
            if -fill.cash_flow > equity_at_cost * DEFAULT_SPEC.max_position_fraction + 0.01:
                raise PaperContractViolation("position exceeds one-third cap")
        projected = self._state([fill.to_dict()])
        if projected["cash"] < -0.001:
            raise PaperContractViolation("insufficient cash")
        sequence = len(payload["events"]) + 1
        previous = payload["head_event_id"]
        event_id = _event_id(sequence, previous, fill.fill_id)
        payload["events"].append({
            "sequence": sequence, "previous_event_id": previous,
            "event_id": event_id, "fill": fill.to_dict(),
        })
        payload["event_count"] = sequence
        payload["head_event_id"] = event_id
        self.directory.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2),
            encoding="utf-8",
        )
        temporary.replace(self.path)
        return True

    def snapshot(self) -> dict:
        state = self._state()
        return {
            "initial_cash": self.initial_cash, "cash": state["cash"],
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

    def reconcile(self, order_journal: OfflineOrderJournal | None = None) -> dict:
        fills = self.fills()
        snapshot = self.snapshot()
        expected_cash = round(
            self.initial_cash + sum(float(item["cash_flow"]) for item in fills), 6
        )
        replayed_positions = self._state()["positions"]
        position_codes = {item["code"] for item in snapshot["positions"]}
        trips = self.round_trips()
        checks = {
            "cash_matches_fills": abs(snapshot["cash"] - expected_cash) <= 0.000001,
            "positions_match_fills": position_codes == set(replayed_positions),
            "fill_ids_unique": len({item["fill_id"] for item in fills}) == len(fills),
            "round_trips_match_sells": len(trips) == sum(item["side"] == "SELL" for item in fills),
            "event_chain_valid": True,
        }
        if order_journal is not None:
            intents = order_journal.intents()
            intent_ids = {item["intent_id"] for item in intents}
            checks["fills_link_to_orders"] = all(
                item["intent_id"] in intent_ids for item in fills
            )
            checks["order_ids_unique"] = len(intent_ids) == len(intents)
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
