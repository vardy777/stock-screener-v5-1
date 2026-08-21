"""Leakage-bounded hourly proxy for the frozen V5 rule policy.

This cohort is research-only.  It deliberately cannot create V5 production
facts, strict samples, notification receipts, paper orders or ledger events.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal, ROUND_DOWN
import csv
import hashlib
import json
import math
from pathlib import Path
from statistics import mean, median


TIMES = ("10:30", "11:30", "14:00", "15:00")


@dataclass(frozen=True)
class ProxyPolicyV1:
    minimum_amount: float = 5_000_000.0
    maximum_intraday_change: float = 0.095
    maximum_range: float = 0.15
    maximum_candidates: int = 20
    initial_cash: Decimal = Decimal("100000")
    commission_rate: Decimal = Decimal("0.0003")
    minimum_commission: Decimal = Decimal("5")
    stamp_tax: Decimal = Decimal("0.0005")
    slippage: Decimal = Decimal("0.0005")
    version: str = "v5-hourly-proxy-policy-v1"


def _tail_lines(path: Path, byte_limit: int = 32_768) -> list[str]:
    with path.open("rb") as handle:
        handle.seek(0, 2); size = handle.tell(); start = max(0, size - byte_limit); handle.seek(start)
        text = handle.read().decode("utf-8-sig", errors="ignore")
    lines = text.splitlines()
    return lines if start == 0 else lines[1:]


def load_hourly_directory(directory: Path) -> dict[str, dict[str, dict[str, dict]]]:
    """Read only the recent tail of each per-symbol CSV; never writes source data."""
    result: dict[str, dict[str, dict[str, dict]]] = defaultdict(lambda: defaultdict(dict))
    for path in sorted(Path(directory).glob("*.csv")):
        code = path.stem.zfill(6)
        for line in _tail_lines(path):
            try:
                fields = next(csv.reader([line])); stamp = fields[0]; day, clock = stamp[:10], stamp[11:16]
                if clock not in TIMES or len(fields) < 7: continue
                values = [float(value) for value in fields[1:7]]
                if not all(math.isfinite(value) for value in values): continue
                result[day][code][clock] = dict(zip(("open", "high", "low", "close", "volume", "amount"), values))
            except (ValueError, IndexError, csv.Error):
                continue
    return {day: dict(codes) for day, codes in result.items()}


def _complete_codes(rows: dict[str, dict[str, dict]]) -> set[str]:
    return {code for code, bars in rows.items() if all(clock in bars for clock in TIMES)}


def _snapshot(rows, previous_rows, *, morning: bool):
    output = []
    for code in sorted(set(rows) & set(previous_rows)):
        bars = rows[code]; prior = previous_rows[code].get("15:00")
        required = ("10:30",) if morning else TIMES
        if not prior or prior["close"] <= 0 or not all(clock in bars for clock in required): continue
        selected = [bars["10:30"]] if morning else [bars[clock] for clock in TIMES]
        last = selected[-1]["close"]; high = max(row["high"] for row in selected); low = min(row["low"] for row in selected)
        volume = sum(max(row["volume"], 0.0) for row in selected)
        # Source amount is zero in this archive.  Price times reported share
        # volume is an explicit turnover proxy, not a reconstructed fact.
        amount = sum(max(row["volume"], 0.0) * max(row["close"], 0.0) for row in selected)
        if min(last, high, low) <= 0: continue
        output.append({"code": code, "last": last, "previous_close": prior["close"], "high": high, "low": low, "volume": volume, "amount": amount})
    return output


def _market_state(rows):
    changes = [row["last"] / row["previous_close"] - 1 for row in rows]
    advance = sum(value > 0 for value in changes) / max(len(changes), 1)
    severe = sum(value <= -0.05 for value in changes) / max(len(changes), 1)
    reasons = []
    if advance < 0.25: reasons.append("MARKET_BREADTH_TOO_WEAK")
    if severe > 0.20: reasons.append("SEVERE_DECLINE_TOO_BROAD")
    return {"total": len(changes), "advance_ratio": advance, "severe_decline_ratio": severe, "trade_allowed": not reasons, "reasons": reasons}


def _eligible(rows, policy: ProxyPolicyV1, *, allowed_codes=None):
    allowed = None if allowed_codes is None else set(allowed_codes); features = []
    for row in rows:
        if allowed is not None and row["code"] not in allowed: continue
        change = row["last"] / row["previous_close"] - 1
        day_range = (row["high"] - row["low"]) / row["previous_close"]
        if row["volume"] <= 0 or row["amount"] < policy.minimum_amount: continue
        if abs(change) >= policy.maximum_intraday_change: continue  # proxy for locked limit books
        if change > policy.maximum_intraday_change or day_range > policy.maximum_range: continue
        location = (row["last"] - row["low"]) / max(row["high"] - row["low"], 0.000001)
        features.append(row | {"change": change, "range": day_range, "close_location": location})
    return features


def _percentiles(rows, key):
    ordered = sorted(rows, key=lambda row: (row[key], row["code"])); denominator = max(len(ordered) - 1, 1)
    return {row["code"]: index / denominator for index, row in enumerate(ordered)}


def _mother_pool(rows, policy):
    momentum = _percentiles(rows, "change"); liquidity = _percentiles(rows, "amount"); location = _percentiles(rows, "close_location")
    ranked = []
    for row in rows:
        score = momentum[row["code"]] * 0.45 + liquidity[row["code"]] * 0.30 + location[row["code"]] * 0.25
        ranked.append(row | {"score": score})
    ranked.sort(key=lambda row: (row["score"], row["code"]), reverse=True)
    return [row | {"rank": index} for index, row in enumerate(ranked[:policy.maximum_candidates], 1)]


def _costed_return(buy_reference, sell_reference, policy, *, cash):
    buy = Decimal(str(buy_reference)) * (Decimal(1) + policy.slippage); sell = Decimal(str(sell_reference)) * (Decimal(1) - policy.slippage)
    budget = min(policy.initial_cash / Decimal(3), cash)
    shares = int(((budget - policy.minimum_commission) / buy / Decimal(100)).to_integral_value(rounding=ROUND_DOWN)) * 100
    if shares <= 0: return None
    buy_notional = (buy * shares).quantize(Decimal("0.01")); sell_notional = (sell * shares).quantize(Decimal("0.01"))
    buy_fee = max(policy.minimum_commission, (buy_notional * policy.commission_rate).quantize(Decimal("0.01")))
    sell_fee = max(policy.minimum_commission, (sell_notional * policy.commission_rate).quantize(Decimal("0.01")))
    tax = (sell_notional * policy.stamp_tax).quantize(Decimal("0.01")); invested = buy_notional + buy_fee; proceeds = sell_notional - sell_fee - tax
    return {"shares": shares, "buy_fill": float(buy), "sell_fill": float(sell), "invested": float(invested), "proceeds": float(proceeds), "pnl": float(proceeds - invested), "net_return": float(proceeds / invested - 1)}


def _metrics(values):
    if not values: return {"count": 0, "win_rate": None, "average_return": None, "median_return": None, "cumulative_return": 0.0}
    count = len(values); wins = sum(value > 0 for value in values); rate = wins / count; z = 1.959963984540054
    center = (rate + z*z/(2*count))/(1+z*z/count); margin = z*math.sqrt(rate*(1-rate)/count+z*z/(4*count*count))/(1+z*z/count)
    return {"count": count, "win_rate": rate, "win_rate_wilson_95": [max(0.0, center-margin), min(1.0, center+margin)], "average_return": mean(values), "median_return": median(values), "cumulative_return": math.prod(1 + value for value in values) - 1}


def run_proxy(history, *, lookback=20, policy=None, minimum_cross_section=3000):
    policy = policy or ProxyPolicyV1(); complete = {day: _complete_codes(rows) for day, rows in history.items()}
    dates = sorted(day for day, codes in complete.items() if len(codes) >= minimum_cross_section)
    pairs = [(dates[index], dates[index + 1]) for index in range(1, len(dates) - 1)]
    pairs = pairs[-lookback:]
    if len(pairs) < lookback: raise ValueError(f"only {len(pairs)} complete proxy sessions available")
    cash = policy.initial_cash; peak = cash; maximum_drawdown = Decimal(0); daily = []
    strategy_returns = []; market_returns = []; random_returns = []
    for index, (day, next_day) in enumerate(pairs):
        previous_day = dates[dates.index(day) - 1]; morning_rows = _snapshot(history[day], history[previous_day], morning=True); tail_rows = _snapshot(history[day], history[previous_day], morning=False)
        morning_market = _market_state(morning_rows); tail_market = _market_state(tail_rows)
        morning_eligible = _eligible(morning_rows, policy) if morning_market["trade_allowed"] else []
        pool = _mother_pool(morning_eligible, policy); allowed = {row["code"] for row in pool}
        tail_eligible = _eligible(tail_rows, policy, allowed_codes=allowed) if tail_market["trade_allowed"] else []
        survivors = sorted(tail_eligible, key=lambda row: next(item["rank"] for item in pool if item["code"] == row["code"]))
        next_open = {code: bars["10:30"]["open"] for code, bars in history[next_day].items() if "10:30" in bars and bars["10:30"]["open"] > 0}
        executable = [row for row in survivors if row["code"] in next_open]
        selected = executable[0] if executable else None; execution = None
        if selected:
            execution = _costed_return(selected["last"], next_open[selected["code"]], policy, cash=cash)
            if execution:
                cash += Decimal(str(execution["pnl"])); strategy_returns.append(execution["net_return"]); peak = max(peak, cash); maximum_drawdown = max(maximum_drawdown, (peak - cash) / peak)
        all_tail = _eligible(tail_rows, policy) if tail_market["trade_allowed"] else []
        comparisons = []
        for row in all_tail:
            if row["code"] in next_open:
                value = _costed_return(row["last"], next_open[row["code"]], policy, cash=policy.initial_cash)
                if value: comparisons.append((row["code"], value["net_return"]))
        market_median = median(value for _, value in comparisons) if comparisons else 0.0
        random_return = 0.0
        if comparisons:
            random_index = int(hashlib.sha256(day.encode()).hexdigest(), 16) % len(comparisons); random_return = sorted(comparisons)[random_index][1]
        market_returns.append(market_median); random_returns.append(random_return)
        prior = next((row for row in pool if selected and row["code"] == selected["code"]), None)
        no_trade_reason = None
        if not execution:
            if not morning_market["trade_allowed"]: no_trade_reason = "MORNING_MARKET_RISK_OFF"
            elif not pool: no_trade_reason = "NO_MORNING_CANDIDATE"
            elif not tail_market["trade_allowed"]: no_trade_reason = "TAIL_MARKET_RISK_OFF"
            elif not survivors: no_trade_reason = "NO_TAIL_SURVIVOR"
            elif not executable: no_trade_reason = "NO_NEXT_OPEN_PROXY"
            else: no_trade_reason = "NON_EXECUTABLE_PROXY"
        selected_lineage = None if not selected else {"code": selected["code"], "morning_rank": prior["rank"], "morning_score": prior["score"], "morning_change": prior["change"], "morning_close_location": prior["close_location"], "morning_amount_proxy": prior["amount"], "tail_change": selected["change"], "tail_close_location": selected["close_location"], "tail_amount_proxy": selected["amount"]}
        daily.append({"trade_date": day, "next_trade_date": next_day, "morning_proxy_time": "10:30", "tail_proxy_time": "15:00", "next_open_proxy_time": "10:30_bar_open", "cross_section": len(morning_rows), "tail_cross_section": len(tail_rows), "morning_market": morning_market, "tail_market": tail_market, "morning_eligible_count": len(morning_eligible), "mother_pool_codes": [row["code"] for row in pool], "confirmation_codes": [row["code"] for row in executable], "confirmation_is_mother_pool_subset": {row["code"] for row in executable} <= allowed, "selected_code": selected["code"] if selected else None, "selected_lineage": selected_lineage, "no_trade_reason": no_trade_reason, "execution": execution, "market_median_net_return": market_median, "deterministic_random_net_return": random_return})
    traded = [row for row in daily if row["execution"]]
    report = {"schema_version": "v5-historical-hourly-proxy-backtest-v1", "cohort": "historical_hourly_proxy", "strict_evidence": False, "research_locked": True, "broker_orders": False, "lookback_sessions": lookback, "period": {"start": pairs[0][0], "end": pairs[-1][0], "last_exit": pairs[-1][1]}, "policy_version": policy.version, "v5_policy_mapping": {"mother_pool_size": policy.maximum_candidates, "momentum_weight": 0.45, "liquidity_weight": 0.30, "close_location_weight": 0.25, "minimum_amount_proxy": policy.minimum_amount, "maximum_intraday_change": policy.maximum_intraday_change, "maximum_range": policy.maximum_range, "top1_only": True, "one_third_cap": True}, "strategy": _metrics(strategy_returns), "all_session_market_median_baseline": _metrics(market_returns), "all_session_deterministic_random_baseline": _metrics(random_returns), "paired_trade_day_market_median_baseline": _metrics([row["market_median_net_return"] for row in traded]), "paired_trade_day_deterministic_random_baseline": _metrics([row["deterministic_random_net_return"] for row in traded]), "paired_excess_vs_market_median": _metrics([row["execution"]["net_return"] - row["market_median_net_return"] for row in traded]), "ending_cash": float(cash), "net_pnl": float(cash - policy.initial_cash), "maximum_drawdown": float(maximum_drawdown), "days_with_trade": len(traded), "days_without_trade": len(daily)-len(traded), "no_trade_reasons": {reason:sum(row["no_trade_reason"]==reason for row in daily) for reason in sorted({row["no_trade_reason"] for row in daily if row["no_trade_reason"]})}, "chain_checks": {"all_confirmations_are_mother_pool_subsets": all(row["confirmation_is_mother_pool_subset"] for row in daily), "maximum_one_execution_per_day": all(row["execution"] is None or row["selected_code"] for row in daily), "exactly_twenty_sessions": len(daily) == lookback}, "limitations": ["09:25 is proxied by the 10:30 first-hour close", "14:49 ask is proxied by the 15:00 hourly close", "next 09:30 bid is proxied by the next 10:30 bar open", "historical bid/ask depth and dual-source consensus are unavailable", "ST/delisting names and point-in-time membership are unavailable", "source amount is zero; turnover is proxied by close times share volume", "survivorship and archive-universe bias may remain", "this cohort cannot satisfy strict-sample or model-publication gates"], "daily": daily}
    unsigned = json.dumps(report, ensure_ascii=False, sort_keys=True, separators=(",", ":")); report["report_id"] = "v5proxy1-" + hashlib.sha256(unsigned.encode()).hexdigest()[:24]
    return report
