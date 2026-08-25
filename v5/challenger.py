"""Isolated volume/price challenger over the exact V5 production snapshots."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import hashlib, json, math, os
from pathlib import Path

from .challenger_context import build_symbol_context, load_context, save_context, _context_id
from .core import CHINA_TZ, ContractViolation
from .fact_reader import latest
from .market_state import MarketStateV1
from .paper_production import PaperProduction, load_snapshot
from .performance import report_strict_paper
from .calendar import TradingCalendar

STRATEGY_ID = "volume_price_v1"


@dataclass(frozen=True)
class VolumePricePolicyV1:
    minimum_amount: float = 5_000_000.0
    maximum_candidates: int = 20
    morning_change_minimum: float = -0.01
    morning_change_maximum: float = 0.05
    confirmation_change_maximum: float = 0.07
    maximum_intraday_range: float = 0.15
    maximum_tail_fade: float = 0.025
    minimum_tail_location: float = 0.55
    ret5_minimum: float = -0.05
    ret5_maximum: float = 0.12
    ret10_minimum: float = -0.08
    ret10_maximum: float = 0.20
    price_to_ma5_minimum: float = 0.95
    price_to_ma5_maximum: float = 1.08
    ma5_to_ma10_minimum: float = 0.97
    ma5_to_ma10_maximum: float = 1.10
    volume_ratio_minimum: float = 0.70
    volume_ratio_maximum: float = 1.80
    version: str = "volume-price-policy-v1"


def _id(prefix, value): return prefix + hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()[:32]


def _save(root, kind, day, prefix, value):
    value = dict(value); entity_id = _id(prefix, value); key = {"v5chmp1-": "pool_id", "v5chcd1-": "confirmation_id", "v5chrun1-": "run_id"}[prefix]; value[key] = entity_id
    path = Path(root) / "challengers" / STRATEGY_ID / kind / day / f"{entity_id}.json"; path.parent.mkdir(parents=True, exist_ok=True); raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")); tmp = path.with_suffix(f".{os.getpid()}.tmp"); tmp.write_text(raw, encoding="utf-8")
    try: os.link(tmp, path)
    except FileExistsError:
        if path.read_text(encoding="utf-8") != raw: raise ContractViolation("challenger immutable collision")
    finally: tmp.unlink(missing_ok=True)
    return value


def _load_one(root, kind, day, prefix, key):
    paths = list((Path(root) / "challengers" / STRATEGY_ID / kind / day).glob("*.json"))
    if not paths: raise ContractViolation(f"challenger {kind} missing")
    values = []
    for path in paths:
        value = json.loads(path.read_text(encoding="utf-8")); declared = value.pop(key, None); rebuilt = _id(prefix, value); value[key] = declared
        if declared != rebuilt or path.stem != declared: raise ContractViolation(f"challenger {kind} hash mismatch")
        values.append(value)
    timestamp_key = "created_at" if kind == "morning_pools" else "decided_at"
    return max(values, key=lambda row: (datetime.fromisoformat(row[timestamp_key]), row[key]))


def _market_state(root, day, snapshot_id):
    matches = []
    for path in (Path(root) / "market_states" / day).glob("*.json"):
        value = json.loads(path.read_text(encoding="utf-8"))
        if value.get("snapshot_id") == snapshot_id: matches.append(MarketStateV1.from_mapping(value))
    if len(matches) != 1: raise ContractViolation("challenger market state missing or ambiguous")
    return matches[0]


def _peak(value, target, width): return max(0.0, 1.0 - abs(value - target) / width)


def _liquidity_percentiles(rows):
    ordered = sorted(rows, key=lambda row: (row["quote"].amount, row["quote"].code))
    denominator = max(len(ordered) - 1, 1)
    return {row["quote"].code: index / denominator for index, row in enumerate(ordered)}


def _funnel(snapshot, context, market, *, stage, baseline=None, policy=None):
    policy = policy or VolumePricePolicyV1(); contexts = {row["code"]: row for row in context["rows"]}; baseline_by_code = {row["code"]: row for row in (baseline or [])}; allowed = set(baseline_by_code) if stage == "confirmation" else None
    rejected = {}; rows = []; completed = datetime.fromisoformat(snapshot.batch_completed_at)
    for quote in snapshot.quotes:
        reason = None; age = (completed - datetime.fromisoformat(quote.exchange_time)).total_seconds(); name = quote.name.upper()
        if "ST" in name or "退" in quote.name: reason = "special_treatment"
        elif quote.halted: reason = "halted"
        elif age < 0 or age > 120: reason = "stale_symbol_quote"
        elif quote.limit_up or quote.limit_down: reason = "limit_locked"
        elif stage == "confirmation" and (quote.ask1 <= 0 or quote.ask1_volume <= 0): reason = "missing_buy_book"
        elif quote.code not in contexts: reason = "historical_context_missing"
        elif allowed is not None and quote.code not in allowed: reason = "outside_morning_pool"
        if reason: rejected[reason] = rejected.get(reason, 0) + 1; continue
        ctx = contexts[quote.code]; change = quote.last_price / quote.previous_close - 1; day_range = (quote.high_price - quote.low_price) / quote.previous_close; location = (quote.last_price - quote.low_price) / max(quote.high_price - quote.low_price, 0.000001); price_ma5 = quote.previous_close / ctx["ma5"]; ma_ratio = ctx["ma5"] / ctx["ma10"]
        checks = [quote.amount >= policy.minimum_amount, day_range <= policy.maximum_intraday_range, policy.ret5_minimum <= ctx["ret_5d"] <= policy.ret5_maximum, policy.ret10_minimum <= ctx["ret_10d"] <= policy.ret10_maximum, policy.price_to_ma5_minimum <= price_ma5 <= policy.price_to_ma5_maximum, policy.ma5_to_ma10_minimum <= ma_ratio <= policy.ma5_to_ma10_maximum, policy.volume_ratio_minimum <= ctx["volume_ratio_5_10"] <= policy.volume_ratio_maximum]
        if stage == "morning": checks.append(policy.morning_change_minimum <= change <= policy.morning_change_maximum)
        else:
            prior = baseline_by_code[quote.code]; checks.extend([change <= policy.confirmation_change_maximum, change >= prior["change"] - policy.maximum_tail_fade, location >= policy.minimum_tail_location])
        if not all(checks): rejected["volume_price_policy_rejected"] = rejected.get("volume_price_policy_rejected", 0) + 1; continue
        rows.append({"quote": quote, "context": ctx, "change": change, "range": day_range, "location": location, "price_to_ma5": price_ma5, "ma5_to_ma10": ma_ratio})
    if not market.trade_allowed: rejected["market_risk_off"] = len(rows); rows = []
    liquidity = _liquidity_percentiles(rows) if rows else {}
    candidates = []
    for row in rows:
        quote = row["quote"]; ctx = row["context"]
        if stage == "confirmation":
            prior = baseline_by_code[quote.code]; score = prior["score"]; rank = prior["rank"]; contributions = prior["factor_contributions"]
        else:
            trend = (_peak(ctx["ret_5d"], 0.04, 0.10) + _peak(ctx["ret_10d"], 0.08, 0.16)) / 2; extension = _peak(row["price_to_ma5"], 1.01, 0.07); volume = _peak(ctx["volume_ratio_5_10"], 1.15, 0.65); current = _peak(row["change"], 0.02, 0.04); contributions = {"trend_quality": round(trend * 0.30, 6), "ma5_extension_quality": round(extension * 0.25, 6), "volume_structure": round(volume * 0.20, 6), "moderate_morning_move": round(current * 0.15, 6), "current_liquidity": round(liquidity[quote.code] * 0.10, 6)}; score = sum(contributions.values()); rank = 0
        candidates.append({"code": quote.code, "name": quote.name, "rank": rank, "change": row["change"], "change_pct": round(row["change"] * 100, 4), "amount": quote.amount, "last_price": quote.last_price, "bid1": quote.bid1, "ask1": quote.ask1, "quote_time": quote.exchange_time, "provider": quote.provider, "score": round(score, 6), "factor_values": {"ret_5d": ctx["ret_5d"], "ret_10d": ctx["ret_10d"], "price_to_ma5": row["price_to_ma5"], "ma5_to_ma10": row["ma5_to_ma10"], "volume_ratio_5_10": ctx["volume_ratio_5_10"], "intraday_change": row["change"], "close_location": row["location"]}, "factor_contributions": contributions, "input_snapshot_id": snapshot.snapshot_id, "context_id": context["context_id"], "strategy_id": STRATEGY_ID, "reasons": ["5/10日趋势不过热", "量能结构通过", "当日涨幅适中"] + (["尾盘稳定性通过", "沿用早盘冻结排名"] if stage == "confirmation" else []), "risks": ["量价挑战者仍可能发生隔夜跳空"]})
    if stage == "morning":
        candidates.sort(key=lambda row: (row["score"], row["code"]), reverse=True); candidates = [row | {"rank": index} for index, row in enumerate(candidates[:policy.maximum_candidates], 1)]
    else: candidates.sort(key=lambda row: (row["rank"], row["code"]))
    return {"policy_version": policy.version, "policy_parameters": policy.__dict__, "input_count": len(snapshot.quotes), "rejected": rejected, "candidates": candidates[:policy.maximum_candidates]}


def project_morning(root, now):
    root = Path(root); day = now.date().isoformat(); context = load_context(root, day); acquisition = latest(root, "acquisition", day, predicate=lambda row: row.get("stage") == "morning")
    if not acquisition.get("accepted"): raise ContractViolation("challenger morning acquisition rejected")
    snapshot = load_snapshot(root / "snapshots" / day / f"{acquisition['selected_snapshot_id']}.json"); market = _market_state(root, day, snapshot.snapshot_id); funnel = _funnel(snapshot, context, market, stage="morning")
    value = {"schema_version": "v5-challenger-morning-pool-v1", "strategy_id": STRATEGY_ID, "trade_date": day, "created_at": snapshot.batch_completed_at, "snapshot_id": snapshot.snapshot_id, "market_state_id": market.market_state_id, "context_id": context["context_id"], "policy_version": funnel["policy_version"], "policy_parameters": funnel["policy_parameters"], "input_count": funnel["input_count"], "rejected": funnel["rejected"], "candidates": funnel["candidates"]}
    return _save(root, "morning_pools", day, "v5chmp1-", value)


def project_confirmation(root, now):
    root = Path(root); day = now.date().isoformat(); pool = _load_one(root, "morning_pools", day, "v5chmp1-", "pool_id"); context = load_context(root, day); pointer = json.loads((root / "frozen" / day / "signal.json").read_text(encoding="utf-8")); snapshot = load_snapshot(root / "snapshots" / day / f"{pointer['snapshot_id']}.json"); market = _market_state(root, day, snapshot.snapshot_id); funnel = _funnel(snapshot, context, market, stage="confirmation", baseline=pool["candidates"])
    value = {"schema_version": "v5-challenger-confirmation-v1", "strategy_id": STRATEGY_ID, "trade_date": day, "decided_at": now.astimezone(CHINA_TZ).isoformat(), "morning_pool_id": pool["pool_id"], "snapshot_id": snapshot.snapshot_id, "market_state_id": market.market_state_id, "context_id": context["context_id"], "policy_version": funnel["policy_version"], "candidates": funnel["candidates"], "rejected": funnel["rejected"], "outcome": "BUY_CANDIDATE" if funnel["candidates"] else "EMPTY"}
    return _save(root, "confirmations", day, "v5chcd1-", value)


def challenger_root(root): return Path(root) / "challengers" / STRATEGY_ID


def paper_buy(root, now, execution_snapshot=None):
    root = Path(root); day = now.date().isoformat(); confirmation = _load_one(root, "confirmations", day, "v5chcd1-", "confirmation_id")
    if confirmation["outcome"] == "EMPTY": return {"outcome": "NO_CANDIDATE", "confirmation_id": confirmation["confirmation_id"]}
    snapshot = execution_snapshot or load_snapshot(root / "snapshots" / day / f"{confirmation['snapshot_id']}.json"); event = PaperProduction(challenger_root(root)).buy(confirmation, snapshot, at=now, eligible_sell_date=TradingCalendar().next_open(now.date()).isoformat()); return event.__dict__


def position_codes(root): return {row["code"] for row in PaperProduction(challenger_root(root)).ledger.state()["positions"]}


def paper_sell(root, snapshot, now):
    events = PaperProduction(challenger_root(root)).sell_all(snapshot, at=now)
    return {"outcome": "FILLED" if events and all(event.outcome == "FILLED" for event in events) else "NO_POSITIONS" if not events else "UNFILLED", "events": [event.__dict__ for event in events]}


def record_run(root, task, day, at, outcome, details):
    value = {"schema_version": "v5-challenger-run-v1", "strategy_id": STRATEGY_ID, "task": task, "trade_date": day, "recorded_at": at.astimezone(CHINA_TZ).isoformat(), "outcome": outcome, "details": details}; return _save(root, "runs", day, "v5chrun1-", value)


def run_isolated(root, task, now, action):
    try: details = action(); outcome = "SUCCESS"
    except Exception as exc: details = {"error_type": type(exc).__name__, "error": str(exc)}; outcome = "FAILED"
    try:
        return record_run(root, task, now.date().isoformat(), now, outcome, details)
    except Exception as exc:
        # A research sidecar must never turn an otherwise valid baseline task
        # into a production failure.  The parent V5 run still preserves this
        # diagnostic even if challenger storage itself is unavailable.
        return {"schema_version": "v5-challenger-run-v1", "strategy_id": STRATEGY_ID, "task": task, "trade_date": now.date().isoformat(), "recorded_at": now.astimezone(CHINA_TZ).isoformat(), "outcome": "FAILED", "details": {"error_type": type(exc).__name__, "error": str(exc), "record_persisted": False}}


def advance_context(root, now, snapshot):
    root = Path(root); current = load_context(root, now.date().isoformat()); next_day = TradingCalendar().next_open(now.date()).isoformat(); rows = []
    quotes = {quote.code: quote for quote in snapshot.quotes}
    for context_row in current["rows"]:
        quote = quotes.get(context_row["code"])
        if not quote: continue
        history = [[row["date"], row["open"], row["close"], row["high"], row["low"], row["volume"] / 100.0] for row in context_row["history"]]
        history.append([now.date().isoformat(), quote.open_price, quote.last_price, quote.high_price, quote.low_price, quote.volume / 100.0]); row, reason, _ = build_symbol_context(history, quote.code, now.date().isoformat())
        if reason == "ok": rows.append(row)
    value = {"schema_version": "v5-challenger-context-v1", "strategy_id": STRATEGY_ID, "target_trade_date": next_day, "expected_previous_session": now.date().isoformat(), "provider": "v5_strict_1449_snapshot_increment", "captured_at": snapshot.batch_completed_at, "universe_count": current["universe_count"], "valid_context_rows": len(rows), "coverage": len(rows) / max(current["universe_count"], 1), "reference_comparable": len(rows), "reference_comparable_ratio": len(rows) / max(current["universe_count"], 1), "reference_matches": len(rows), "reference_match_rate": 1.0, "future_rows_discarded": 0, "reasons": {"ok": len(rows)}, "challenger_context_ready": len(rows) / max(current["universe_count"], 1) >= 0.95, "research_only": True, "strict_sample": False, "rows": sorted(rows, key=lambda row: row["code"]), "capture_duration_seconds": 0.0}; value["context_id"] = _context_id(value); save_context(root, value); return {key: value[key] for key in ("context_id", "target_trade_date", "coverage", "challenger_context_ready")}


def projection(root, day, *, as_of=None):
    root = Path(root); pool = confirmation = None
    try: pool = _load_one(root, "morning_pools", day, "v5chmp1-", "pool_id")
    except ContractViolation: pass
    try: confirmation = _load_one(root, "confirmations", day, "v5chcd1-", "confirmation_id")
    except ContractViolation: pass
    ledger = PaperProduction(challenger_root(root)).ledger; trips = ledger.round_trips(as_of=as_of); performance = report_strict_paper(trips)
    active = confirmation or pool; candidates = list(active.get("candidates", [])) if active else []
    context_ready = False
    try: context_ready = load_context(root, day).get("challenger_context_ready") is True
    except ContractViolation: pass
    from .paired_comparison import build_pairs
    from .opportunity import load_pairs
    from .statistical_protocol import evaluate
    pairs = build_pairs(PaperProduction(root).ledger, ledger, pairing_facts=load_pairs(root))
    return {"strategy_id": STRATEGY_ID, "label": "量价挑战者", "mode": "shadow_no_push", "context_ready": context_ready, "stage": "confirmation" if confirmation else "morning" if pool else "waiting", "candidate_count": len(candidates), "candidates": candidates, "outcome": active.get("outcome", "OBSERVE") if active else "WAITING", "account": ledger.state(as_of=as_of), "performance": performance.to_dict(), "paired_evaluation": evaluate(pairs), "paired_days": pairs, "pool_id": pool.get("pool_id", "") if pool else "", "confirmation_id": confirmation.get("confirmation_id", "") if confirmation else ""}
