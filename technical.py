"""
技术指标模块
计算 MA、MACD、均线排列等技术因子
"""

import numpy as np
import urllib.request
import json
import re
import time
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

logger = logging.getLogger(__name__)

SINA_HEADERS = {
    "Referer": "https://finance.sina.com.cn",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
}


# ============================================================
# 获取个股历史 K 线（新浪 API）
# ============================================================

def fetch_kline(code, days=60):
    """
    获取个股日线 K 线数据
    返回 [{day, open, high, low, close, volume}, ...] 按日期升序
    """
    prefix = "sh" if str(code).startswith("6") else "sz"
    url = (f"https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/"
           f"CN_MarketData.getKLineData?symbol={prefix}{code}&scale=240&ma=5&datalen={days}")
    
    try:
        req = urllib.request.Request(url, headers=SINA_HEADERS)
        with urllib.request.urlopen(req, timeout=10) as resp:
            raw = resp.read().decode("gbk", errors="replace")
        
        data = json.loads(raw)
        if not data or not isinstance(data, list):
            return None
        
        # 解析并排序（新浪返回按日期降序）
        result = []
        for item in data:
            result.append({
                "day": item["day"],
                "open": float(item["open"]),
                "high": float(item["high"]),
                "low": float(item["low"]),
                "close": float(item["close"]),
                "volume": int(item.get("volume", 0)),
            })
        
        # 按日期升序排列
        result.sort(key=lambda x: x["day"])
        
        return result
    except Exception as e:
        logger.debug(f"获取 {code} K线失败: {e}")
        return None


def batch_fetch_kline(codes, days=60, max_workers=5):
    """
    批量获取多只股票 K 线
    返回 {code: kline_data, ...}
    """
    results = {}
    
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_map = {executor.submit(fetch_kline, code, days): code for code in codes}
        
        for future in as_completed(future_map):
            code = future_map[future]
            try:
                data = future.result()
                if data:
                    results[code] = data
            except Exception as e:
                logger.debug(f"批量获取 {code} 失败: {e}")
    
    logger.info(f"批量 K 线: 请求 {len(codes)} 只, 成功 {len(results)} 只")
    return results


# ============================================================
# 技术指标计算
# ============================================================

def calc_ma(kline, periods=[5, 10, 20]):
    """
    计算移动均线
    返回 {ma5: [...], ma10: [...], ma20: [...]} 每个都是每日值的列表
    """
    closes = np.array([k["close"] for k in kline])
    result = {}
    
    for p in periods:
        ma = np.full(len(closes), np.nan)
        for i in range(p - 1, len(closes)):
            ma[i] = round(np.mean(closes[i-p+1:i+1]), 2)
        result[f"ma{p}"] = ma.tolist()
    
    return result


def calc_macd(kline, fast=12, slow=26, signal=9):
    """
    计算 MACD 指标
    返回 {dif, dea, macd_hist} 三个列表
    """
    closes = np.array([k["close"] for k in kline])
    n = len(closes)
    
    # EMA 计算
    def ema(data, period):
        result = np.full(n, np.nan)
        multiplier = 2 / (period + 1)
        result[0] = data[0]
        for i in range(1, n):
            result[i] = (data[i] - result[i-1]) * multiplier + result[i-1]
        return result
    
    ema_fast = ema(closes, fast)
    ema_slow = ema(closes, slow)
    
    dif = (ema_fast - ema_slow).tolist()
    
    # DEA (signal line) — EMA of DIF
    dea = np.full(n, np.nan)
    multiplier = 2 / (signal + 1)
    dea[signal - 1] = dif[signal - 1]
    for i in range(signal, n):
        dea[i] = (dif[i] - dea[i-1]) * multiplier + dea[i-1]
    
    dea = dea.tolist()
    
    # MACD 柱状图
    macd_hist = [round(dif[i] - dea[i], 4) if not np.isnan(dea[i]) else 0 for i in range(n)]
    dif = [round(v, 4) for v in dif]
    dea = [round(v, 4) if not np.isnan(v) else 0 for v in dea]
    
    return {"dif": dif, "dea": dea, "macd_hist": macd_hist}


# ============================================================
# 技术面评分（多因子综合）
# ============================================================

def score_technical(kline):
    """
    对一只股票的技术面进行综合评分
    返回 dict 包含各项技术因子得分
    """
    if not kline or len(kline) < 20:
        return {"score": 0, "scores": {}, "reason": "K线数据不足(需20天+)", "ma_data": None, "macd_data": None}
    
    closes = np.array([k["close"] for k in kline])
    latest = kline[-1]
    latest_close = latest["close"]
    n = len(kline)
    
    scores = {}
    reasons = []
    total = 0
    
    # --- 因子 1: MA 多头排列 (0~30分) ---
    mas = calc_ma(kline)
    if n >= 20:
        ma5 = mas["ma5"][-1]
        ma10 = mas["ma10"][-1]
        ma20 = mas["ma20"][-1]
        
        if not any(np.isnan(x) for x in [ma5, ma10, ma20]):
            # 多头排列: close > MA5 > MA10 > MA20
            if latest_close > ma5 > ma10 > ma20:
                scores["ma_bullish"] = 30
                reasons.append("MA多头排列")
                total += 30
            elif latest_close > ma5 > ma10:  # 短期多头
                scores["ma_short_bullish"] = 20
                reasons.append("短期多头")
                total += 20
            elif latest_close > ma5:
                scores["ma_weak"] = 10
                reasons.append("站上MA5")
                total += 10
            else:
                scores["ma_bearish"] = -10
                reasons.append("均线下方❌")
                total -= 10
    
    # --- 因子 2: MACD 金叉/死叉 (0~25分) ---
    macd = calc_macd(kline)
    if n >= 26:
        dif_latest = macd["dif"][-1]
        dea_latest = macd["dea"][-1]
        hist_latest = macd["macd_hist"][-1]
        
        # 金叉: DIF > DEA
        if dif_latest > dea_latest and hist_latest > 0:
            scores["macd_golden"] = 25
            reasons.append("MACD金叉")
            total += 25
        elif dif_latest > dea_latest:
            scores["macd_bullish"] = 15
            reasons.append("MACD多头")
            total += 15
        elif dif_latest < dea_latest and hist_latest < 0:
            scores["macd_dead"] = -15
            reasons.append("MACD死叉❌")
            total -= 15
    
    # --- 因子 3: 趋势强度 (0~20分) ---
    # 最近 5 天涨幅
    if n >= 6:
        pct_5d = (closes[-1] - closes[-6]) / closes[-6] * 100
        if pct_5d > 5:
            scores["trend_strong"] = 20
            reasons.append("5日涨幅>5%")
            total += 20
        elif pct_5d > 2:
            scores["trend_good"] = 12
            reasons.append("5日涨幅>2%")
            total += 12
        elif pct_5d > 0:
            scores["trend_weak"] = 5
            reasons.append("5日微涨")
            total += 5
        else:
            scores["trend_down"] = -5
            reasons.append("5日下跌")
            total -= 5
    
    # --- 因子 4: 成交量确认 (0~15分) ---
    if n >= 10:
        vol = np.array([k["volume"] for k in kline])
        vol_ma5 = np.mean(vol[-5:])
        vol_ma10 = np.mean(vol[-10:])
        vol_ratio = vol_ma5 / vol_ma10 if vol_ma10 > 0 else 1
        
        if vol_ratio > 1.5:
            scores["vol_surge"] = 15
            reasons.append("放量")
            total += 15
        elif vol_ratio > 1.2:
            scores["vol_good"] = 10
            reasons.append("量能温和")
            total += 10
        elif vol_ratio > 0.8:
            scores["vol_normal"] = 5
            reasons.append("量能正常")
            total += 5
        else:
            scores["vol_shrink"] = -10
            reasons.append("缩量❌")
            total -= 10
    
    # --- 因子 5: 价格位置 (0~10分) ---
    if n >= 20:
        high_20 = np.max(closes[-20:])
        low_20 = np.min(closes[-20:])
        if high_20 > low_20:
            pos = (latest_close - low_20) / (high_20 - low_20)
            if pos > 0.8:
                scores["pos_high"] = 10
                reasons.append("高位")
                total += 10
            elif pos > 0.5:
                scores["pos_mid_high"] = 7
                reasons.append("中高位")
                total += 7
            elif pos > 0.2:
                scores["pos_mid"] = 3
                reasons.append("中位")
                total += 3
    
    return {
        "score": total,
        "scores": scores,
        "reasons": " | ".join(reasons) if reasons else "无明显信号",
        "ma_data": mas if n >= 20 else None,
        "macd_data": macd if n >= 26 else None,
    }


def check_bullish_alignment(kline):
    """快速判断是否多头排列（用来做布尔过滤）"""
    if not kline or len(kline) < 20:
        return False, "数据不足"
    
    closes = np.array([k["close"] for k in kline])
    latest = closes[-1]
    
    mas = calc_ma(kline)
    ma5 = mas["ma5"][-1]
    ma10 = mas["ma10"][-1]
    ma20 = mas["ma20"][-1]
    
    if any(np.isnan(x) for x in [ma5, ma10, ma20]):
        return False, "均线数据不足"
    
    checks = []
    if latest > ma5:
        checks.append(">MA5")
    if ma5 > ma10:
        checks.append("MA5>MA10")
    
    if latest > ma5 > ma10:
        return True, "短多 " + " ".join(checks)
    elif latest > ma5:
        return True, "站上MA5 " + " ".join(checks)
    else:
        return False, f"均线下: {latest:.1f}<MA5{ma5:.1f}"


def check_macd_golden(kline):
    """快速判断 MACD 是否金叉或多头"""
    if not kline or len(kline) < 26:
        return False, "数据不足"
    
    macd = calc_macd(kline)
    dif = macd["dif"][-1]
    dea = macd["dea"][-1]
    hist = macd["macd_hist"][-1]
    
    if dif > dea and hist > 0:
        return True, f"金叉 DIF({dif:.2f})>DEA({dea:.2f})"
    elif dif > dea:
        return True, f"DIF>DEA ({dif:.2f}>{dea:.2f})"
    else:
        return False, f"死叉 DIF({dif:.2f})<DEA({dea:.2f})"


# ============================================================
# 测试
# ============================================================

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    
    codes = ["600519", "000001", "300750"]
    klines = batch_fetch_kline(codes)
    
    for code in codes:
        kline = klines.get(code)
        if kline:
            latest = kline[-1]
            ma5 = calc_ma(kline)["ma5"][-1] if len(kline) >= 5 else 0
            score = score_technical(kline)
            
            print(f"\n📊 {code} {latest['day']} 收盘:{latest['close']:.2f} MA5:{ma5:.2f}")
            print(f"   技术评分: {score['score']}分 | {score['reasons']}")
            
            ok, msg = check_bullish_alignment(kline)
            print(f"   均线: {'✅' if ok else '❌'} {msg}")
            
            if len(kline) >= 26:
                ok2, msg2 = check_macd_golden(kline)
                print(f"   MACD: {'✅' if ok2 else '❌'} {msg2}")
