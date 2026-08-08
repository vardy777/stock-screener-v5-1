"""The sole provider-to-core market data boundary for V4."""

from __future__ import annotations

from datetime import datetime
from typing import Iterable, Protocol

from .execution import CHINA_TZ, TradingClock
from .market_contracts import ContractViolation, EvidenceCohort, MarketSnapshotV1, QuoteV1


class QuoteProvider(Protocol):
    def batch_fetch_quotes(self, codes: list[str]): ...


class MarketDataGateway:
    """Convert provider frames into an immutable, versioned snapshot.

    pandas/provider objects terminate here. Core modules must receive the
    returned MarketSnapshotV1 and must never call a quote provider directly.
    """

    def __init__(self, provider: QuoteProvider | None = None):
        if provider is None:
            from .data import DataFetcher
            provider = DataFetcher()
        self._provider = provider

    def fetch_snapshot(
        self, codes: Iterable[str], *, session: str,
        cohort: EvidenceCohort = EvidenceCohort.STRICT,
        now: datetime | None = None, minimum_coverage: float = 0.95,
        require_order_book: bool | None = None,
    ) -> MarketSnapshotV1:
        current = now or TradingClock.now()
        if current.tzinfo is None or current.utcoffset() is None:
            raise ContractViolation("now: timezone is required")
        current = current.astimezone(CHINA_TZ)
        universe = sorted({str(code).strip().zfill(6) for code in codes if str(code).strip()})
        frame = self._provider.batch_fetch_quotes(universe)
        attrs = getattr(frame, "attrs", {}) if frame is not None else {}
        started_value = attrs.get("batch_started_at", current)
        completed_value = attrs.get("batch_completed_at", current)
        quotes: list[QuoteV1] = []
        if frame is not None and not getattr(frame, "empty", True):
            for row in frame.to_dict(orient="records"):
                code = str(row.get("code", "")).strip().zfill(6)
                if code not in universe or bool(row.get("is_mock", False)):
                    continue
                try:
                    quotes.append(QuoteV1.from_provider_row(row))
                except ContractViolation:
                    continue
        return MarketSnapshotV1.build(
            trade_date=current.date().isoformat(), session=session,
            batch_started_at=started_value, batch_completed_at=completed_value,
            quotes=quotes, expected_codes=len(universe), cohort=cohort,
            minimum_coverage=minimum_coverage,
            require_order_book=(session in {"buy", "sell"}) if require_order_book is None else require_order_book,
        )
