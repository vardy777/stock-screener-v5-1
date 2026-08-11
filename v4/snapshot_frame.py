"""Internal dataframe projection of an already validated market snapshot.

Provider frames must never cross into this module.  pandas remains an
implementation detail for vectorised calculations after the contract boundary.
"""

from __future__ import annotations

import pandas as pd

from .market_contracts import ContractViolation, MarketSnapshotV1


def snapshot_frame(snapshot: MarketSnapshotV1) -> pd.DataFrame:
    if not isinstance(snapshot, MarketSnapshotV1):
        raise ContractViolation("snapshot: MarketSnapshotV1 required")
    rows = []
    # ``snapshot_id`` hashes the complete immutable quote set.  Computing it
    # inside the full-market loop turns a linear projection into O(n²) work
    # and can make a 4,000-symbol window finish several minutes late.
    snapshot_id = snapshot.snapshot_id
    for quote in snapshot.quotes:
        change_pct = (quote.last_price / quote.previous_close - 1.0) * 100.0
        rows.append({
            "code": quote.code,
            "name": quote.name,
            "price": quote.last_price,
            "last_price": quote.last_price,
            "prev_close": quote.previous_close,
            "open": quote.open_price,
            "high": quote.high_price,
            "low": quote.low_price,
            "change_pct": change_pct,
            "pct_chg": change_pct,
            "quote_time": quote.exchange_time,
            "exchange_time": quote.exchange_time,
            "provider_time": quote.provider_time,
            "received_at": quote.received_at,
            "bid1": quote.bid1,
            "bid1_volume": quote.bid1_volume,
            "ask1": quote.ask1,
            "ask1_volume": quote.ask1_volume,
            "volume": quote.volume,
            "amount": quote.amount,
            "halted": quote.halted,
            "limit_up": quote.limit_up,
            "limit_down": quote.limit_down,
            "provider": quote.provider,
            "snapshot_id": snapshot_id,
        })
    return pd.DataFrame(rows)
