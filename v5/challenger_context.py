"""V5-native causal daily context for isolated strategy challengers."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime
import hashlib, json, math, os, statistics, time
from pathlib import Path
from urllib.request import Request, urlopen

from .core import CHINA_TZ, ContractViolation

PROVIDER = "tencent_fqkline_qfq_day"


def fetch_daily_rows(code: str, *, timeout: float = 10.0, rows: int = 45) -> list[list]:
    code = str(code).zfill(6); symbol = ("sh" if code.startswith("6") else "sz") + code
    url = f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={symbol},day,,,{int(rows)},qfq"
    request = Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urlopen(request, timeout=timeout) as response:
        value = json.loads(response.read().decode("utf-8"))
    if int(value.get("code", -1)) != 0: raise ValueError("daily context provider rejected request")
    result = value.get("data", {}).get(symbol, {}).get("qfqday", [])
    if not isinstance(result, list): raise ValueError("daily context rows missing")
    return result


def build_symbol_context(rows: list[list], code: str, expected_previous: str) -> tuple[dict, str, int]:
    expected = date.fromisoformat(expected_previous); parsed = {}; future = 0
    for raw in rows:
        if not isinstance(raw, list) or len(raw) < 6: continue
        try:
            day = date.fromisoformat(str(raw[0])); values = [float(raw[index]) for index in range(1, 6)]
        except (TypeError, ValueError): continue
        if day > expected: future += 1; continue
        if not all(math.isfinite(value) for value in values) or min(values[:4]) <= 0 or values[4] < 0: continue
        parsed[day] = {"date": day.isoformat(), "open": values[0], "close": values[1], "high": values[2], "low": values[3], "volume": values[4] * 100.0}
    history = [parsed[key] for key in sorted(parsed)]
    if not history or history[-1]["date"] != expected_previous: return {}, "stale_previous_session", future
    if len(history) < 22: return {}, "insufficient_history", future
    history = history[-31:]; closes = [row["close"] for row in history]; volumes = [row["volume"] for row in history]; current = closes[-1]
    returns = [closes[index] / closes[index - 1] - 1 for index in range(1, len(closes))]
    row = {"code": str(code).zfill(6), "context_date": expected_previous, "context_prev_close": current, "ma5": statistics.mean(closes[-5:]), "ma10": statistics.mean(closes[-10:]), "ret_5d": current / closes[-6] - 1, "ret_10d": current / closes[-11] - 1, "volume_mean_5": statistics.mean(volumes[-5:]), "volume_mean_10": statistics.mean(volumes[-10:]), "volume_ratio_5_10": statistics.mean(volumes[-5:]) / max(statistics.mean(volumes[-10:]), 1.0), "volatility_10": statistics.pstdev(returns[-10:]), "history": history, "history_days": len(history), "provider": PROVIDER}
    numeric = [value for key, value in row.items() if key not in {"code", "context_date", "history", "provider"}]
    if not all(math.isfinite(float(value)) for value in numeric): return {}, "non_finite", future
    return row, "ok", future


def _context_id(value):
    return "v5ctx1-" + hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()[:32]


def build_context(codes, target_trade_date, expected_previous, *, reference_prices, workers=12, fetcher=fetch_daily_rows, cache_dir=None):
    normalized = sorted({str(code).zfill(6) for code in codes}); cache = Path(cache_dir) if cache_dir else None
    if cache: cache.mkdir(parents=True, exist_ok=True)
    started = datetime.now(CHINA_TZ); reasons = {}; results = []; future_rows = 0
    def one(code):
        cache_path = cache / f"{code}.json" if cache else None
        if cache_path and cache_path.exists():
            try:
                cached = json.loads(cache_path.read_text(encoding="utf-8"))
                if cached.get("code") == code and cached.get("context_date") == expected_previous: return cached, "ok_cached", 0
            except Exception: pass
        last = None
        for attempt in range(3):
            try:
                row, reason, future = build_symbol_context(fetcher(code), code, expected_previous)
                if row and cache_path:
                    tmp = cache_path.with_suffix(f".{os.getpid()}.tmp"); tmp.write_text(json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")), encoding="utf-8"); os.replace(tmp, cache_path)
                return row, reason, future
            except Exception as exc:
                last = exc
                if attempt < 2: time.sleep(0.2 * (attempt + 1))
        return {}, "fetch_failed:" + type(last).__name__, 0
    with ThreadPoolExecutor(max_workers=max(1, int(workers))) as pool:
        futures = {pool.submit(one, code): code for code in normalized}
        for index, future in enumerate(as_completed(futures), 1):
            row, reason, dropped = future.result(); reasons[reason] = reasons.get(reason, 0) + 1; future_rows += dropped
            if row: results.append(row)
            if index % 500 == 0: print(f"challenger context {index}/{len(normalized)}", flush=True)
    results.sort(key=lambda row: row["code"]); comparable = matches = 0
    for row in results:
        reference = float(reference_prices.get(row["code"], 0) or 0)
        if reference > 0:
            comparable += 1
            if abs(row["context_prev_close"] / reference - 1) <= 0.01: matches += 1
    coverage = len(results) / max(len(normalized), 1); comparable_ratio = comparable / max(len(normalized), 1); match_rate = matches / max(comparable, 1)
    value = {"schema_version": "v5-challenger-context-v1", "strategy_id": "volume_price_v1", "target_trade_date": target_trade_date, "expected_previous_session": expected_previous, "provider": PROVIDER, "captured_at": datetime.now(CHINA_TZ).isoformat(timespec="seconds"), "universe_count": len(normalized), "valid_context_rows": len(results), "coverage": coverage, "reference_comparable": comparable, "reference_comparable_ratio": comparable_ratio, "reference_matches": matches, "reference_match_rate": match_rate, "future_rows_discarded": future_rows, "reasons": reasons, "challenger_context_ready": coverage >= 0.95 and comparable_ratio >= 0.95 and match_rate >= 0.95, "research_only": True, "strict_sample": False, "rows": results}
    value["capture_duration_seconds"] = round((datetime.now(CHINA_TZ) - started).total_seconds(), 3); value["context_id"] = _context_id(value)
    return value


def save_context(root, context):
    root = Path(root); context_id = context.get("context_id"); rebuilt = _context_id({key: value for key, value in context.items() if key != "context_id"})
    if context_id != rebuilt: raise ContractViolation("challenger context hash mismatch")
    path = root / "challengers/volume_price_v1/contexts" / context["target_trade_date"] / f"{context_id}.json"; path.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(context, ensure_ascii=False, sort_keys=True, separators=(",", ":")); tmp = path.with_suffix(f".{os.getpid()}.tmp"); tmp.write_text(raw, encoding="utf-8")
    try: os.link(tmp, path)
    except FileExistsError:
        if path.read_text(encoding="utf-8") != raw: raise ContractViolation("challenger context immutable collision")
    finally: tmp.unlink(missing_ok=True)
    return path


def load_context(root, trade_date):
    paths = list((Path(root) / "challengers/volume_price_v1/contexts" / trade_date).glob("*.json"))
    if len(paths) != 1: raise ContractViolation("challenger context missing or ambiguous")
    value = json.loads(paths[0].read_text(encoding="utf-8")); declared = value.get("context_id"); rebuilt = _context_id({key: row for key, row in value.items() if key != "context_id"})
    if declared != rebuilt or paths[0].stem != declared or value.get("challenger_context_ready") is not True: raise ContractViolation("challenger context invalid or not ready")
    return value
