"""Offline-only P3 intent factory and isolated execution orchestration."""

from __future__ import annotations

from datetime import datetime
from typing import Iterable

from strategy_spec import DEFAULT_SPEC, TradeCostModel
from .calendar import TradingCalendar
from .market_contracts import MarketSnapshotV1
from .p3_account import OfflineExecutionJournal, OfflineOrderJournal, OfflinePaperLedger
from .p3_contracts import PaperContractViolation, PaperExecutionResultV1, PaperFillV1, PaperOrderIntentV1


class OfflineIntentFactory:
    def __init__(self, *, calendar=None, costs=None):
        self.calendar = calendar or TradingCalendar()
        self.costs = costs or TradeCostModel(DEFAULT_SPEC)

    def buy_from_decision(
        self, decision: dict, snapshot: MarketSnapshotV1, *, created_at: datetime,
        total_equity: float = 100_000.0,
    ) -> PaperOrderIntentV1:
        if not isinstance(snapshot, MarketSnapshotV1) or snapshot.session != "buy":
            raise PaperContractViolation("buy intent: buy MarketSnapshotV1 required")
        if decision.get("outcome") != "BUY" or not str(decision.get("decision_id", "")).startswith("cd-"):
            raise PaperContractViolation("buy intent: final BUY decision required")
        eligible = [item for item in decision.get("candidates", []) if item.get("v4_paper_eligible") is True]
        if len(eligible) != 1 or int(eligible[0].get("rank", 0)) != 1:
            raise PaperContractViolation("buy intent: exactly one eligible Top1 required")
        candidate = eligible[0]
        code = str(candidate.get("code", "")).zfill(6)
        quote = next((item for item in snapshot.quotes if item.code == code), None)
        if quote is None or quote.ask1 <= 0 or quote.ask1_volume <= 0:
            raise PaperContractViolation("buy intent: executable ask1 missing")
        trade_day = datetime.fromisoformat(snapshot.batch_completed_at).date()
        if getattr(self.calendar, "verified", False) is not True:
            raise PaperContractViolation("buy intent: verified trading calendar required")
        next_open = self.calendar.next_open(trade_day)
        if next_open is None:
            raise PaperContractViolation("buy intent: verified next session missing")
        budget = DEFAULT_SPEC.position_budget(total_equity)
        shares = self.costs.max_affordable_shares(quote.ask1, budget)
        if shares <= 0:
            raise PaperContractViolation("buy intent: no affordable board lot")
        return PaperOrderIntentV1.build(
            decision_id=decision["decision_id"], side="BUY", code=code,
            name=candidate.get("name", quote.name), trade_date=trade_day,
            created_at=created_at, reference_price=quote.ask1, shares=shares,
            cash_budget=budget, market_snapshot_id=snapshot.snapshot_id,
            eligible_sell_date=next_open,
        )

    def sell_from_position(
        self, position: dict, snapshot: MarketSnapshotV1, *, created_at: datetime,
    ) -> PaperOrderIntentV1:
        if not isinstance(snapshot, MarketSnapshotV1) or snapshot.session != "sell":
            raise PaperContractViolation("sell intent: sell MarketSnapshotV1 required")
        code = str(position.get("code", "")).zfill(6)
        quote = next((item for item in snapshot.quotes if item.code == code), None)
        if quote is None or quote.bid1 <= 0 or quote.bid1_volume <= 0:
            raise PaperContractViolation("sell intent: executable bid1 missing")
        trade_day = datetime.fromisoformat(snapshot.batch_completed_at).date().isoformat()
        eligible = str(position.get("eligible_sell_date", ""))
        if trade_day < eligible:
            raise PaperContractViolation("sell intent: position is not T+1 eligible")
        return PaperOrderIntentV1.build(
            decision_id=position["decision_id"], side="SELL", code=code,
            name=position.get("name", quote.name), trade_date=trade_day,
            created_at=created_at, reference_price=quote.bid1,
            shares=int(position["shares"]), cash_budget=float(position["notional"]),
            market_snapshot_id=snapshot.snapshot_id,
            eligible_sell_date=eligible,
        )


class OfflineExecutionEngine:
    def __init__(
        self, ledger: OfflinePaperLedger, *, costs=None, order_journal=None, execution_journal=None
    ):
        self.ledger = ledger
        self.costs = costs or TradeCostModel(DEFAULT_SPEC)
        self.order_journal = order_journal or OfflineOrderJournal(ledger.directory)
        self.execution_journal = execution_journal or OfflineExecutionJournal(ledger.directory)

    @staticmethod
    def _reason_code(exc: Exception) -> str:
        if isinstance(exc, PaperContractViolation):
            return "CONTRACT_REJECTED"
        if isinstance(exc, OSError):
            return "STORAGE_FAILURE"
        return "EXECUTION_FAILURE"

    def execute(self, intents: Iterable[PaperOrderIntentV1], *, filled_at: datetime) -> dict:
        results = []
        for intent in intents:
            try:
                self.order_journal.append(intent)
                reference = intent.reference_price
                fill_price = (
                    self.costs.buy_fill_price(reference)
                    if intent.side == "BUY"
                    else self.costs.sell_fill_price(reference)
                )
                costs = (
                    self.costs.buy_cash_required(fill_price, intent.shares)
                    if intent.side == "BUY"
                    else self.costs.sell_cash_received(fill_price, intent.shares)
                )
                fill = PaperFillV1.build(
                    intent, filled_at=filled_at, fill_price=fill_price, costs=costs
                )
                appended = self.ledger.append(fill)
                result_event = PaperExecutionResultV1.build(
                    intent_id=intent.intent_id, recorded_at=filled_at, outcome="FILLED",
                    reason_code="IDEMPOTENT" if not appended else "FILLED", fill_id=fill.fill_id)
                self.execution_journal.append(result_event)
                results.append({
                    "intent_id": intent.intent_id, "fill_id": fill.fill_id,
                    "success": True, "idempotent": not appended,
                })
            except Exception as exc:
                intent_id = getattr(intent, "intent_id", None)
                if intent_id:
                    try:
                        self.execution_journal.append(PaperExecutionResultV1.build(
                            intent_id=intent_id, recorded_at=filled_at, outcome="REJECTED",
                            reason_code=self._reason_code(exc)))
                    except Exception:
                        pass
                results.append({
                    "intent_id": intent_id, "success": False,
                    "reason_code": self._reason_code(exc), "error": str(exc),
                })
        return {
            "success": all(item["success"] for item in results),
            "filled": sum(1 for item in results if item["success"] and not item.get("idempotent")),
            "failed": sum(1 for item in results if not item["success"]),
            "results": results,
        }

    def recovery_report(self) -> dict:
        intents = self.order_journal.intents()
        fills = self.ledger.fills()
        results = self.execution_journal.results()
        filled_ids = {row["intent_id"] for row in fills}
        rejected_ids = {row["intent_id"] for row in results if row["outcome"] == "REJECTED" and row["reason_code"] != "STORAGE_FAILURE"}
        retryable_ids = {row["intent_id"] for row in results if row["outcome"] == "REJECTED" and row["reason_code"] == "STORAGE_FAILURE"}
        known_ids = {row["intent_id"] for row in intents}
        pending = [row for row in intents if row["intent_id"] not in filled_ids and row["intent_id"] not in rejected_ids]
        return {
            "schema_version": "offline-execution-recovery-v1",
            "status": "RECOVERY_REQUIRED" if pending or retryable_ids - filled_ids else "CLEAN",
            "pending_intents": pending,
            "retryable_intent_ids": sorted(retryable_ids - filled_ids),
            "filled_intent_ids": sorted(filled_ids), "rejected_intent_ids": sorted(rejected_ids),
            "orphan_fill_ids": sorted(row["fill_id"] for row in fills if row["intent_id"] not in known_ids),
        }

    def retry_pending(self, *, filled_at: datetime) -> dict:
        """Idempotently retry every persisted intent not terminally resolved."""
        pending = [PaperOrderIntentV1.from_mapping(row) for row in self.recovery_report()["pending_intents"]]
        return self.execute(pending, filled_at=filled_at)
