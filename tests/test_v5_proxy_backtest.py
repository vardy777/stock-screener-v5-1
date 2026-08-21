from datetime import date, timedelta
from v5.proxy_backtest import run_proxy


def history(days=23, symbols=30):
    output = {}; start = date(2026, 1, 5)
    for offset in range(days):
        day = (start + timedelta(days=offset)).isoformat(); output[day] = {}
        for index in range(symbols):
            code = f"{index + 1:06d}"; prior = 10 + index / 10; strength = (index + 1) / 1000
            bars = {}; opened = prior * (1 + strength + offset * 0.01)
            for clock, multiplier in (("10:30", 1.0), ("11:30", 1.002), ("14:00", 1.004), ("15:00", 1.006)):
                close = opened * multiplier; bars[clock] = {"open": opened, "high": close * 1.002, "low": opened * 0.998, "close": close, "volume": 1_000_000 + index * 10_000, "amount": 0.0}
            output[day][code] = bars
    return output


def test_proxy_is_separate_non_strict_twenty_session_cohort_with_valid_chain():
    report = run_proxy(history(), lookback=20, minimum_cross_section=20)
    assert report["strict_evidence"] is False and report["cohort"] == "historical_hourly_proxy"
    assert report["lookback_sessions"] == 20 and len(report["daily"]) == 20
    assert report["chain_checks"] == {"all_confirmations_are_mother_pool_subsets": True, "maximum_one_execution_per_day": True, "exactly_twenty_sessions": True}
    assert all(set(row["confirmation_codes"]) <= set(row["mother_pool_codes"]) for row in report["daily"])
    assert report["strategy"]["win_rate_wilson_95"][0] <= report["strategy"]["win_rate"] <= report["strategy"]["win_rate_wilson_95"][1]
    assert report["paired_trade_day_market_median_baseline"]["count"] == report["strategy"]["count"]


def test_morning_pool_never_uses_later_same_day_bars():
    source = history(); first = run_proxy(source, lookback=20, minimum_cross_section=20)
    target = first["daily"][0]["trade_date"]
    for bars in source[target].values():
        for clock in ("11:30", "14:00", "15:00"):
            bars[clock]["close"] *= 1.5; bars[clock]["high"] *= 1.5
    second = run_proxy(source, lookback=20, minimum_cross_section=20)
    assert first["daily"][0]["mother_pool_codes"] == second["daily"][0]["mother_pool_codes"]


def test_proxy_refuses_insufficient_history():
    try:
        run_proxy(history(days=10), lookback=20, minimum_cross_section=20)
    except ValueError as exc:
        assert "complete proxy sessions" in str(exc)
    else:
        raise AssertionError("insufficient history accepted")


def test_partial_symbol_bars_are_excluded_not_backfilled():
    source = history(); target = sorted(source)[-5]; source[target]["000001"].pop("14:00")
    report = run_proxy(source, lookback=20, minimum_cross_section=20)
    row = next(item for item in report["daily"] if item["trade_date"] == target)
    assert row["cross_section"] == 30 and row["tail_cross_section"] == 29
