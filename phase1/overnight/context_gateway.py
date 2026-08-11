"""Point-in-time previous-session context from a second market-data provider."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
import hashlib
import json
from pathlib import Path
import time
from typing import Callable, Iterable
import urllib.request

import numpy as np
import pandas as pd

from v4.execution import CHINA_TZ


PROVIDER = "tencent_fqkline_qfq_day"


def _url(code: str, rows: int = 45) -> str:
    symbol = ("sh" if str(code).startswith("6") else "sz") + str(code).zfill(6)
    return (
        "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param="
        f"{symbol},day,,,{int(rows)},qfq"
    )


def fetch_daily_rows(code: str, *, timeout: float = 12.0) -> list[list]:
    code = str(code).zfill(6); symbol = ("sh" if code.startswith("6") else "sz") + code
    request = urllib.request.Request(_url(code), headers={"User-Agent":"Mozilla/5.0"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        value = json.loads(response.read().decode("utf-8"))
    if int(value.get("code", -1)) != 0:
        raise ValueError("provider rejected request")
    rows = value.get("data", {}).get(symbol, {}).get("qfqday", [])
    if not isinstance(rows, list):
        raise ValueError("provider rows missing")
    return rows


def build_symbol_context(rows: list[list], code: str, expected_previous: str) -> tuple[dict, str, int]:
    parsed=[]; future=0
    expected=pd.Timestamp(expected_previous).normalize()
    for row in rows:
        if not isinstance(row, list) or len(row)<6: continue
        try:
            day=pd.Timestamp(str(row[0])).normalize()
            values=[float(row[index]) for index in range(1,6)]
        except (TypeError,ValueError):
            continue
        if day>expected: future+=1; continue
        if not all(np.isfinite(values)) or min(values[:4])<=0 or values[4]<0: continue
        parsed.append({"date":day,"open":values[0],"close":values[1],"high":values[2],
                       "low":values[3],"volume":values[4]*100.0})  # provider volume is lots
    frame=pd.DataFrame(parsed).drop_duplicates("date",keep="last").sort_values("date") if parsed else pd.DataFrame()
    if frame.empty or frame.iloc[-1]["date"]!=expected: return {},"stale_previous_session",future
    if len(frame)<22: return {},"insufficient_history",future
    close=frame["close"].astype(float); volume=frame["volume"].astype(float)
    overnight=frame["open"].astype(float)/close.shift(1)-1.0; returns=close.pct_change(fill_method=None)
    current=float(close.iloc[-1])
    result={
        "code":str(code).zfill(6),"context_date":expected.date().isoformat(),"context_prev_close":current,
        "volume_mean_20":float(volume.iloc[-20:].mean()),"ma5_base":float(close.iloc[-5:].mean()),
        "ma10_base":float(close.iloc[-10:].mean()),"ma20_base":float(close.iloc[-20:].mean()),
        "ret_1d":current/float(close.iloc[-2])-1.0,"ret_3d":current/float(close.iloc[-4])-1.0,
        "ret_5d":current/float(close.iloc[-6])-1.0,"ret_10d":current/float(close.iloc[-11])-1.0,
        "ret_20d":current/float(close.iloc[-21])-1.0,"volatility_20":float(returns.iloc[-20:].std(ddof=0)),
        "overnight_mean_20":float(overnight.dropna().iloc[-20:].mean()),
        "overnight_hit_1pct_20":float((overnight.dropna().iloc[-20:]>=0.01).mean()),
        "history_days":int(len(frame)),
    }
    if not all(np.isfinite(v) for k,v in result.items() if k not in {"code","context_date"}):
        return {},"non_finite",future
    return result,"ok",future


def build_context(codes: Iterable[str], expected_previous: str, *, reference_prices: dict[str,float],
                  reference_source: str, workers: int = 24,
                  fetcher: Callable[[str],list[list]] = fetch_daily_rows) -> tuple[pd.DataFrame,dict]:
    normalized=sorted({str(code).zfill(6) for code in codes}); started=datetime.now(CHINA_TZ)
    results=[]; reasons={}; future_rows=0
    def one(code):
        last=None
        for attempt in range(3):
            try: return code,*build_symbol_context(fetcher(code),code,expected_previous)
            except Exception as exc:
                last=exc
                if attempt<2: time.sleep(0.15*(attempt+1))
        return code,{},"fetch_failed:"+type(last).__name__,0
    with ThreadPoolExecutor(max_workers=max(1,int(workers))) as pool:
        futures=[pool.submit(one,code) for code in normalized]
        for index,future in enumerate(as_completed(futures),start=1):
            _,row,reason,dropped=future.result(); future_rows+=dropped
            reasons[reason]=reasons.get(reason,0)+1
            if row: results.append(row)
            if index%500==0: print(f"  context gateway: {index}/{len(normalized)}",flush=True)
    frame=pd.DataFrame(results).sort_values("code").reset_index(drop=True) if results else pd.DataFrame()
    matches=0; comparable=0
    for row in results:
        reference=float(reference_prices.get(row["code"],0) or 0)
        if reference>0:
            comparable+=1
            if abs(float(row["context_prev_close"])/reference-1.0)<=0.01: matches+=1
    coverage=len(frame)/len(normalized) if normalized else 0.0
    verification=matches/comparable if comparable else 0.0
    completed=datetime.now(CHINA_TZ)
    metadata={
        "context_version":"live-feature-context-v1","expected_previous_session":expected_previous,
        "files_considered":len(normalized),"valid_context_rows":len(frame),"coverage":coverage,"reasons":reasons,
        "volume_unit":"shares","volume_unit_verified":True,"provider":PROVIDER,
        "provider_volume_conversion":"lots_x_100_to_shares","captured_at":completed.isoformat(timespec="seconds"),
        "capture_duration_seconds":round((completed-started).total_seconds(),3),"future_rows_discarded":future_rows,
        "reference_source":reference_source,"reference_comparable":comparable,"reference_matches":matches,
        "reference_match_rate":verification,"maximum_reference_difference":0.01,
        "universe_sha256":hashlib.sha256("\n".join(normalized).encode()).hexdigest(),
        "strict_context_ready":bool(coverage>=0.95 and comparable/len(normalized)>=0.95 and verification>=0.95),
    }
    return frame,metadata

