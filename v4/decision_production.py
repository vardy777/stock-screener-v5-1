"""Pure P2 production decision producer with no account responsibilities."""
from __future__ import annotations
from datetime import datetime,time
from pathlib import Path
from time import sleep

from market_universe import list_universe_codes

from .candidate_journal import CandidateJournal
from .decision_service import DecisionChainService
from .execution import TradingClock
from .market import analyze_market, empty_market_state
from .market_gateway import MarketDataGateway
from .runtime import V4Runtime


class P2DecisionProducer:
    def __init__(self, *, gateway=None, journal=None, runtime=None, universe_codes=None):
        self.gateway = gateway or MarketDataGateway()
        self.journal = journal or CandidateJournal()
        self.runtime = runtime or V4Runtime()
        self.universe_codes = universe_codes

    def produce(self, stage: str) -> dict:
        if stage not in {"morning", "confirmation"}:
            raise ValueError("decision stage must be morning or confirmation")
        current = TradingClock.now(); day = current.date().isoformat()
        morning_rows = []; allowed_codes = None
        if stage == "confirmation":
            morning_rows = self.journal.morning_candidates(day)
            if not self.journal.has_morning(day):
                return DecisionChainService(self.journal, None).publish_missing_morning(day, empty_market_state())
            allowed_codes = {str(row.get("code")) for row in morning_rows if row.get("code")}
            if not allowed_codes:
                # An empty morning pool is a valid, immutable input. Reuse
                # its frozen market-state lineage rather than inventing a
                # 14:50 snapshot which was never needed for an empty pool.
                morning_entity = self.journal.morning(day)
                market_state = dict(morning_entity.get("market_state", {}))
                if not market_state:
                    raise RuntimeError("MORNING_MARKET_STATE_MISSING")
                return self.journal.save_confirmation(day, [], market_state)
            codes = sorted(allowed_codes)
        else:
            root = Path(__file__).resolve().parents[1]
            codes = list(self.universe_codes or list_universe_codes(root / "phase1" / "data" / "daily"))
            if not codes:
                raise RuntimeError("FULL_MARKET_UNIVERSE_EMPTY")
        # Confirmation is an observation over the whole frozen mother pool.
        # A halted/limit-locked/non-executable member must be rejected per
        # symbol by policy, not invalidate the complete decision snapshot.
        # P3 creates the strict order-book execution snapshot only for the
        # final eligible Top1 immediately before a paper fill.
        snapshot = self.gateway.fetch_snapshot(codes, session="buy" if stage == "confirmation" else "morning",
            require_order_book=False, now=current)
        if not snapshot.quotes:
            raise RuntimeError("MARKET_SNAPSHOT_EMPTY")
        # Quote validity belongs to the immutable capture, not to however long
        # downstream analytics take.  This also makes replay deterministic.
        reference_time = datetime.fromisoformat(snapshot.batch_completed_at)
        market_state = dict(analyze_market(
            snapshot, reference_time=reference_time
        ).get("market_state", {}))
        # 09:25 is a provider transition boundary: one batch can legitimately
        # contain many 09:24:xx quotes. Retry inside the same business window
        # before freezing an empty pool, while keeping the 95% gate unchanged.
        # Nothing is persisted until the final capture is selected.
        attempts=1
        while (stage == "morning" and market_state.get("data_valid") is not True
               and attempts < 3 and TradingClock.now().timetz().replace(tzinfo=None) < time(9,29)):
            sleep(2)
            retry_now=TradingClock.now()
            snapshot=self.gateway.fetch_snapshot(codes,session="morning",require_order_book=False,now=retry_now)
            if not snapshot.quotes: break
            reference_time=datetime.fromisoformat(snapshot.batch_completed_at)
            market_state=dict(analyze_market(snapshot,reference_time=reference_time).get("market_state",{}))
            attempts+=1
        market_state["capture_attempts"]=attempts
        candidates = self.runtime.evaluate_universe(snapshot, market_state=market_state,
            allowed_codes=allowed_codes, morning_candidates=morning_rows if stage == "confirmation" else None,
            decision_stage=stage, reference_time=reference_time)
        service = DecisionChainService(self.journal, self.runtime)
        return (service.publish_morning(day, candidates, market_state) if stage == "morning"
                else service.publish_confirmation(day, candidates, market_state))
