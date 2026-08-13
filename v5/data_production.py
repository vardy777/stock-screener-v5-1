"""Provider-neutral strict V5 acquisition session; no lowered fallback policy."""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from typing import Iterable,Protocol
from v4.execution import CHINA_TZ
from v4.market_contracts import MarketSnapshotV1
from .contracts import AcquisitionSessionV1

# These describe collection truth for the entire universe.  Per-symbol
# execution states (halt, limit lock, missing book) are intentionally handled
# by the funnel, otherwise one unusable stock closes the whole market.
GLOBAL_STRICT_REASONS={"empty","duplicate_code","incomplete_coverage","batch_delay","provider_clock_skew","cross_trade_date"}

def acquisition_accepted(snapshot:MarketSnapshotV1)->bool:
    return not any(reason in GLOBAL_STRICT_REASONS for reason in snapshot.quality.reasons)

class SnapshotSource(Protocol):
    name:str
    def capture(self,codes:list[str],*,stage:str,now:datetime)->MarketSnapshotV1: ...
@dataclass(frozen=True)
class AcquisitionResult:
    session:AcquisitionSessionV1; snapshot:MarketSnapshotV1|None
class MultiSourceAcquirer:
    def __init__(self,sources:Iterable[SnapshotSource]):
        self.sources=tuple(sources)
        if not self.sources:raise ValueError("at least one source is required")
    def acquire(self,codes:Iterable[str],*,stage:str,now:datetime)->AcquisitionResult:
        if now.tzinfo is None or now.utcoffset() is None:raise ValueError("now: timezone-aware required")
        now=now.astimezone(CHINA_TZ);universe=sorted({str(x).zfill(6) for x in codes if str(x)})
        if not universe:raise ValueError("codes: non-empty required")
        attempts=[];selected=None
        for source in self.sources:
            try:
                snapshot=source.capture(universe,stage=stage,now=now)
                valid=(snapshot.trade_date==now.date().isoformat() and snapshot.quality.expected_codes==len(universe) and acquisition_accepted(snapshot))
                attempts.append({"source":source.name,"snapshot_id":snapshot.snapshot_id,"accepted":valid,"coverage":snapshot.quality.coverage,"age_seconds":snapshot.quality.maximum_quote_age_seconds,"batch_seconds":snapshot.quality.batch_duration_seconds,"reasons":list(snapshot.quality.reasons)})
                if valid:selected=snapshot;break
            except Exception as exc:attempts.append({"source":source.name,"accepted":False,"error":f"{type(exc).__name__}: {exc}"})
        session=AcquisitionSessionV1.build(trade_date=now.date().isoformat(),stage=stage,requested_at=now,expected_codes=len(universe),selected_snapshot_id=selected.snapshot_id if selected else "",accepted=selected is not None,source_attempts=attempts)
        return AcquisitionResult(session,selected)
