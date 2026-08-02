#!/usr/bin/env python
"""
compute_factor_ic.py — 周六15:00运行, IC权重更新
从market.db读取最近60天数据
计算每日因子IC (Information Coefficient)
更新 factor_ic.json
输出IC报告
"""
import sys, os, json, sqlite3, logging
from datetime import datetime, date, timedelta
from collections import defaultdict

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
from v2.config import DATA_DIR, MARKET_DB, FACTOR_IC_FILE, FACTOR_21

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(name)s] %(levelname)s %(message)s')
logger = logging.getLogger('compute_factor_ic')


def fetch_daily_data(conn, days=60):
    """从 market.db 读取最近 days 天的快照数据"""
    end_date = date.today()
    start_date = end_date - timedelta(days=days)
    start_str = start_date.strftime("%Y-%m-%d")

    c = conn.cursor()
    c.execute("SELECT * FROM daily_snapshot WHERE date >= ? ORDER BY date, code", (start_str,))
    columns = [col[0] for col in c.description]
    rows = c.fetchall()

    # 按日期分组
    by_date = defaultdict(list)
    for row in rows:
        record = dict(zip(columns, row))
        d = record.get("date", "")
        by_date[d].append(record)

    logger.info(f"读取 {start_str} 至今共 {len(by_date)} 个交易日, {len(rows)} 条记录")
    return by_date


def calc_spearman_rank_correlation(x_vals, y_vals):
    """计算 Spearman 秩相关系数 (IC)"""
    n = len(x_vals)
    if n < 10:
        return 0.0
    # 排名
    x_sorted = sorted(enumerate(x_vals), key=lambda e: e[1])
    y_sorted = sorted(enumerate(y_vals), key=lambda e: e[1])

    x_rank = [0] * n
    y_rank = [0] * n
    for i, (idx, _) in enumerate(x_sorted):
        x_rank[idx] = i
    for i, (idx, _) in enumerate(y_sorted):
        y_rank[idx] = i

    # Pearson on ranks = Spearman
    n_f = float(n)
    mean_x = sum(x_rank) / n_f
    mean_y = sum(y_rank) / n_f

    cov = sum((x_rank[i] - mean_x) * (y_rank[i] - mean_y) for i in range(n))
    std_x = (sum((x_rank[i] - mean_x) ** 2 for i in range(n)) / n_f) ** 0.5
    std_y = (sum((y_rank[i] - mean_y) ** 2 for i in range(n)) / n_f) ** 0.5

    if std_x == 0 or std_y == 0:
        return 0.0
    return cov / (n_f * std_x * std_y)


def compute_factor_ic(by_date):
    """
    对每个因子计算每日 IC (因子值 vs 次日涨幅)
    返回 {factor_name: [daily_ic_values]}
    """
    factor_names = list(FACTOR_21.keys())
    dates_sorted = sorted(by_date.keys())

    # 因子每日 IC 值
    factor_daily_ic = {fname: [] for fname in factor_names}
    ic_dates = []

    for i in range(len(dates_sorted) - 1):
        today = dates_sorted[i]
        next_day = dates_sorted[i + 1]

        today_stocks = by_date[today]
        next_stocks_map = {s["code"]: s for s in by_date[next_day]}

        # 只取次日也有数据的
        paired = []
        for s in today_stocks:
            code = s.get("code", "")
            if code in next_stocks_map:
                paired.append((s, next_stocks_map[code]))

        if len(paired) < 20:
            continue

        # 各因子值和次日涨跌幅
        for fname in factor_names:
            factor_vals = []
            ret_vals = []
            for s_today, s_next in paired:
                # 因子值
                if fname == "momentum_1d":
                    fv = s_today.get("change_pct", 0) or 0
                elif fname == "close_position":
                    high = s_today.get("high", 0) or 0
                    low = s_today.get("low", 0) or 0
                    price = s_today.get("price", 0) or 0
                    fv = (price - low) / (high - low) if (high - low) > 0 else 0.5
                elif fname == "high_low_spread":
                    high = s_today.get("high", 0) or 0
                    low = s_today.get("low", 0) or 0
                    price = s_today.get("price", 0) or 0
                    fv = (high - low) / price if price > 0 else 0
                elif fname == "volume_ratio":
                    vol = s_today.get("volume", 0) or 1
                    # 估算量比: 当日量 / 前日量 (使用 prev_close 作为 proxy)
                    # 简单用 amount/prev 均值
                    fv = 1.0
                elif fname == "market_cap":
                    fv = s_today.get("circulating_market_cap", 5e9) or 5e9
                elif fname == "pe_ttm":
                    fv = s_today.get("pe_ttm", 30) or 30
                elif fname == "pb":
                    fv = s_today.get("pb", 3) or 3
                elif fname == "main_net":
                    # 从缓存读取, 如果没有就用0
                    fv = s_today.get("main_net", 0) or 0
                elif fname == "main_ratio":
                    fv = s_today.get("main_ratio", 0) or 0
                elif fname == "super_large_net":
                    fv = s_today.get("super_large_net", 0) or 0
                elif fname == "ma_bullish":
                    fv = 1 if s_today.get("ma_bullish", False) else 0
                elif fname == "macd_golden":
                    fv = 1 if s_today.get("macd_golden", False) else 0
                elif fname == "rsi_6" or fname == "rsi_14":
                    fv = 50  # 默认中性
                elif fname == "vwap_position":
                    high = s_today.get("high", 0) or 0
                    low = s_today.get("low", 0) or 0
                    price = s_today.get("price", 0) or 0
                    fv = (price - low) / (high - low) if (high - low) > 0 else 0.5
                elif fname == "candle_body_pct":
                    price = s_today.get("price", 0) or 0
                    open_p = s_today.get("open", 0) or 0
                    fv = (price - open_p) / open_p * 100 if open_p > 0 else 0
                elif fname == "tech_score":
                    fv = s_today.get("tech_score", 0) or 0
                elif fname == "cap_score":
                    fv = s_today.get("capital_score", 0) or 0
                else:
                    # momentum_5d/10d/20d 用 change_pct 近似
                    fv = s_today.get("change_pct", 0) or 0

                # 次日涨幅 (作为未来收益)
                prev_close = s_next.get("prev_close", 0) or 0
                price = s_next.get("price", 0) or 0
                ret = (price - prev_close) / prev_close * 100 if prev_close > 0 else 0

                factor_vals.append(fv)
                ret_vals.append(ret)

            if len(factor_vals) >= 20:
                ic = calc_spearman_rank_correlation(factor_vals, ret_vals)
                factor_daily_ic[fname].append(ic)

        ic_dates.append(next_day)

    return factor_daily_ic, ic_dates


def update_ic_weights(factor_daily_ic):
    """根据 IC 均值更新因子权重"""
    ic_means = {}
    for fname, ic_vals in factor_daily_ic.items():
        if ic_vals:
            mean_ic = sum(ic_vals) / len(ic_vals)
            ic_means[fname] = mean_ic
        else:
            ic_means[fname] = 0

    # 使用 IC 均值作为权重基础 (取绝对值)
    total_abs = sum(abs(v) for v in ic_means.values())
    if total_abs == 0:
        # fallback 到默认权重
        return {name: info["weight"] for name, info in FACTOR_21.items()}

    ic_weights = {}
    for fname, mean_ic in ic_means.items():
        ic_weights[fname] = round(abs(mean_ic) / total_abs, 4)

    return ic_weights


def main():
    today = date.today().strftime("%Y-%m-%d")
    logger.info(f"=== 因子IC计算 {today} ===")

    if not os.path.exists(MARKET_DB):
        logger.error(f"market.db 不存在: {MARKET_DB}")
        return

    conn = sqlite3.connect(MARKET_DB)

    # 1. 读取60天数据
    by_date = fetch_daily_data(conn, days=60)
    conn.close()

    if len(by_date) < 5:
        logger.error(f"数据不足: 仅 {len(by_date)} 个交易日")
        return

    # 2. 计算每日因子 IC
    factor_daily_ic, ic_dates = compute_factor_ic(by_date)
    logger.info(f"IC 计算完成: {len(ic_dates)} 个交易日")

    # 3. 更新 IC 权重
    ic_weights = update_ic_weights(factor_daily_ic)

    # 4. 输出 IC 报告
    logger.info(f"\n{'='*60}")
    logger.info(f"  因子 IC 报告")
    logger.info(f"{'='*60}")
    logger.info(f"{'因子':<20} {'平均IC':>10} {'IC次数':>8} {'权重':>8}")
    logger.info(f"{'-'*20} {'-'*10} {'-'*8} {'-'*8}")

    # 按 IC 绝对值排序
    sorted_factors = sorted(
        [(f, sum(v)/len(v) if v else 0, len(v)) for f, v in factor_daily_ic.items()],
        key=lambda x: abs(x[1]), reverse=True
    )

    for fname, mean_ic, count in sorted_factors:
        weight = ic_weights.get(fname, 0)
        desc = FACTOR_21.get(fname, {}).get("desc", fname)
        logger.info(f"{fname:<20} {mean_ic:>+10.4f} {count:>8d} {weight:>8.4f}  ({desc})")

    logger.info(f"{'='*60}")

    # 5. 保存到文件
    factor_ic_data = {
        "ic_weights": ic_weights,
        "ic_values": {f: v for f, v in factor_daily_ic.items()},
        "ic_dates": ic_dates,
        "updated_at": datetime.now().isoformat(),
        "factor_count": len(ic_weights),
        "trading_days": len(ic_dates),
    }

    with open(FACTOR_IC_FILE, "w", encoding="utf-8") as f:
        json.dump(factor_ic_data, f, ensure_ascii=False, indent=2)

    logger.info(f"IC 权重已保存: {FACTOR_IC_FILE}")
    logger.info(f"共 {len(ic_weights)} 个因子权重已更新")
    logger.info("=== IC 计算完成 ===")


if __name__ == "__main__":
    main()
