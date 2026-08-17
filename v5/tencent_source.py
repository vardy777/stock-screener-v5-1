"""V5-native Tencent Level-1 source and active-listing probe."""
from __future__ import annotations

from datetime import datetime
import re
import time
from urllib.request import Request, urlopen

from .core import CHINA_TZ
from .market_snapshot import MarketSnapshotV1, QuoteV1


def _fetch(url, timeout):
    request = Request(url, headers={"Referer": "https://finance.qq.com/", "User-Agent": "Mozilla/5.0"})
    with urlopen(request, timeout=timeout) as response:
        return response.read().decode("gb18030", errors="replace")


def _symbols(codes):
    return [("sh" if code.startswith("6") else "sz") + code for code in codes]


def _rows(text):
    for line in text.splitlines():
        match = re.match(r'v_(?:sh|sz)(\d{6})="(.*)";', line.strip())
        if match:
            yield match.group(1), match.group(2).split("~")


def active_codes(codes, *, fetch_text=None, timeout=12, batch_size=300):
    """Filter a provider directory using Tencent's explicit delisted marker."""
    fetch_text = fetch_text or _fetch
    result = set()
    for offset in range(0, len(codes), batch_size):
        batch = list(codes[offset:offset + batch_size])
        text = fetch_text("https://qt.gtimg.cn/q=" + ",".join(_symbols(batch)), timeout)
        for code, fields in _rows(text):
            try:
                if len(fields) >= 41 and fields[1].strip() and float(fields[4]) > 0 and fields[40] != "D":
                    result.add(code)
            except (TypeError, ValueError):
                continue
    return sorted(result)


class TencentRealtimeSource:
    name = "tencent_realtime_level1"

    def __init__(self, fetch_text=None, timeout=12, batch_size=300, clock=None,
                 overall_budget_seconds=25, monotonic=None, sleeper=None, retries=2):
        self.fetch_text = fetch_text or _fetch
        self.timeout = timeout
        self.batch_size = batch_size
        self.clock = clock or (lambda: datetime.now(CHINA_TZ))
        self.overall_budget_seconds = float(overall_budget_seconds)
        self.monotonic = monotonic or time.monotonic
        self.sleeper = sleeper or time.sleep
        self.retries = int(retries)

    def capture(self, codes, *, stage, now):
        started = self.clock()
        deadline = self.monotonic() + self.overall_budget_seconds
        quotes = []
        for offset in range(0, len(codes), self.batch_size):
            batch = list(codes[offset:offset + self.batch_size])
            text = None
            for attempt in range(self.retries + 1):
                remaining = deadline - self.monotonic()
                if remaining <= 0:
                    raise TimeoutError("tencent capture exceeded overall budget")
                try:
                    text = self.fetch_text(
                        "https://qt.gtimg.cn/q=" + ",".join(_symbols(batch)),
                        min(self.timeout, max(.1, remaining)),
                    )
                    break
                except (TimeoutError, ConnectionError, OSError, RuntimeError) as exc:
                    if attempt >= self.retries:
                        raise RuntimeError(f"tencent batch unavailable: {type(exc).__name__}") from exc
                    self.sleeper(min(.2 * (attempt + 1), max(0, deadline - self.monotonic())))
            received = self.clock()
            for code, fields in _rows(text or ""):
                try:
                    if len(fields) < 41 or fields[40] == "D":
                        continue
                    name = fields[1].strip()
                    price, previous, opened = map(float, (fields[3], fields[4], fields[5]))
                    high, low = map(float, (fields[33], fields[34]))
                    volume = int(float(fields[36]) * 100)
                    if not name or min(price, previous, opened, high, low) <= 0 or volume <= 0:
                        continue
                    exchange = datetime.strptime(fields[30], "%Y%m%d%H%M%S").replace(tzinfo=CHINA_TZ)
                    bid, ask = float(fields[9] or 0), float(fields[19] or 0)
                    ratio = .2 if code.startswith(("30", "688", "689")) else .1
                    quotes.append(QuoteV1.from_mapping({
                        "code": code, "name": name, "trade_date": exchange.date().isoformat(),
                        "exchange_time": exchange, "provider_time": exchange, "received_at": received,
                        "last_price": price, "previous_close": previous, "open_price": opened,
                        "high_price": high, "low_price": low, "bid1": bid,
                        "bid1_volume": int(float(fields[10] or 0) * 100), "ask1": ask,
                        "ask1_volume": int(float(fields[20] or 0) * 100), "volume": volume,
                        "amount": float(fields[37] or 0) * 10000, "halted": False,
                        "limit_up": price >= round(previous * (1 + ratio), 2) and ask <= 0,
                        "limit_down": price <= round(previous * (1 - ratio), 2) and bid <= 0,
                        "provider": self.name,
                    }))
                except Exception:
                    continue
        completed = self.clock()
        session = {"morning": "morning", "signal": "signal", "confirmation": "buy", "sell": "sell"}[stage]
        return MarketSnapshotV1.build(
            trade_date=now.astimezone(CHINA_TZ).date().isoformat(), session=session,
            batch_started_at=started, batch_completed_at=completed, quotes=quotes,
            expected_codes=len(codes),
        )
