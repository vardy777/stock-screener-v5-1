from datetime import datetime

import pandas as pd

from v4.execution import CHINA_TZ
from v4.market_contracts import EvidenceCohort, MarketSnapshotV1, QuoteV1


def snapshot_from_frame(frame: pd.DataFrame, *, session="morning", expected_codes=None):
    rows = []
    for raw in frame.to_dict(orient="records"):
        exchange = datetime.fromisoformat(str(raw["quote_time"])).astimezone(CHINA_TZ)
        price = float(raw.get("price", 0.0))
        previous = float(raw.get("prev_close", price or 1.0))
        rows.append(QuoteV1.from_mapping({
            "code": str(raw["code"]).zfill(6), "name": raw.get("name", "测试股票"),
            "trade_date": exchange.date().isoformat(), "exchange_time": exchange,
            "provider_time": exchange, "received_at": exchange,
            "last_price": price, "previous_close": previous,
            "open_price": float(raw.get("open", previous)),
            "high_price": float(raw.get("high", price)),
            "low_price": float(raw.get("low", price)),
            "bid1": float(raw.get("bid1", price)), "bid1_volume": 100,
            "ask1": float(raw.get("ask1", price)), "ask1_volume": 100,
            "volume": int(raw.get("volume", 100)), "amount": float(raw.get("amount", 1.0)),
            "halted": False, "limit_up": False, "limit_down": False, "provider": "test",
        }))
    completed = max(datetime.fromisoformat(item.exchange_time) for item in rows)
    return MarketSnapshotV1.build(
        trade_date=completed.date().isoformat(), session=session,
        batch_started_at=completed, batch_completed_at=completed,
        quotes=rows, expected_codes=expected_codes or len({item.code for item in rows}),
        cohort=EvidenceCohort.STRICT, require_order_book=False,
    )
