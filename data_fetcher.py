"""
数据获取模块
使用新浪财经 HTTP API
"""

import pandas as pd
import numpy as np
import urllib.request
import re
import time
import json
import logging
from datetime import datetime, date

logger = logging.getLogger(__name__)

SINA_HEADERS = {
    "Referer": "https://finance.sina.com.cn",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
}


def is_trading_day(dt=None):
    if dt is None:
        dt = datetime.now()
    return dt.weekday() < 5


def get_today_str():
    return date.today().strftime("%Y-%m-%d")


def _fetch_url(url, timeout=15):
    try:
        req = urllib.request.Request(url, headers=SINA_HEADERS)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            try:
                text = raw.decode("gbk")
            except UnicodeDecodeError:
                text = raw.decode("gbk", errors="replace")
            return text
    except Exception as e:
        logger.warning(f"请求失败 [{url[:50]}...]: {e}")
        return None


# ============================================================
# 全市场行情查询
# ============================================================

CODE_PREFIXES = {
    "sh": range(600000, 605000),
    "sh_601": range(601000, 602000),
    "sh_603": range(603000, 604000),
    "sz_000": range(1, 1000),
    "sz_001": range(1, 1000),
    "sz_002": range(2001, 3000),
    "sz_300": range(300001, 301000),
    "sz_301": range(301001, 302000),
    "sh_688": range(688001, 689000),
}


def batch_fetch_quotes(codes, batch_size=800):
    """通过新浪 API 批量获取行情"""
    if not codes:
        return None
    
    all_dfs = []
    for i in range(0, len(codes), batch_size):
        batch = codes[i:i+batch_size]
        sina_codes = []
        for code in batch:
            code = str(code).strip()
            if code.startswith("6"):
                sina_codes.append(f"sh{code}")
            else:
                sina_codes.append(f"sz{code}")
        
        url = "https://hq.sinajs.cn/list=" + ",".join(sina_codes)
        text = _fetch_url(url)
        if text:
            df = _parse_sina_response(text)
            if df is not None and len(df) > 0:
                all_dfs.append(df)
        
        if i + batch_size < len(codes):
            time.sleep(0.3)
    
    if all_dfs:
        result = pd.concat(all_dfs, ignore_index=True)
        return result
    return None


def _parse_sina_response(text):
    """解析新浪 API 返回的行情数据"""
    rows = []
    for line in text.strip().split("\n"):
        line = line.strip()
        if not line or not line.startswith("var hq_str_"):
            continue
        
        match = re.search(r'"(.+)"', line)
        if not match:
            continue
        
        fields = match.group(1).split(",")
        if len(fields) < 10:
            continue
        
        try:
            name = fields[0].strip()
            if not name or name == "0":
                continue
            if name.startswith("ST") or "退" in name:
                continue
            
            prev_close = float(fields[2]) if fields[2] else 0
            price = float(fields[3]) if fields[3] else 0
            open_price = float(fields[1]) if fields[1] else 0
            high = float(fields[4]) if fields[4] else 0
            low = float(fields[5]) if fields[5] else 0
            volume_hand = float(fields[8]) if fields[8] else 0
            amount = float(fields[9]) if fields[9] else 0
            
            if price <= 0 or prev_close <= 0:
                continue
            
            code_match = re.search(r'var hq_str_(sh|sz)(\d+)="', line)
            code = code_match.group(2) if code_match else "000000"
            
            change_pct = round((price - prev_close) / prev_close * 100, 2)
            
            rows.append({
                "code": code, "name": name,
                "price": round(price, 2),
                "change_pct": change_pct,
                "change_amount": round(price - prev_close, 2),
                "high": round(high, 2), "low": round(low, 2),
                "open": round(open_price, 2),
                "prev_close": round(prev_close, 2),
                "volume": int(volume_hand * 100),
                "amount": round(amount, 2),
            })
        except (ValueError, IndexError, TypeError):
            continue
    
    if not rows:
        return None
    
    df = pd.DataFrame(rows)
    df["close_position"] = np.where(
        (df["high"] - df["low"]) > 0,
        ((df["price"] - df["low"]) / (df["high"] - df["low"])).round(2), 0.5
    )
    df["candle_body_pct"] = ((df["price"] - df["open"]) / df["open"] * 100).round(2)
    return df


# ============================================================
# 大盘指数
# ============================================================

def get_market_summary():
    url = "https://hq.sinajs.cn/list=sh000001,sz399001,sz399006"
    text = _fetch_url(url)
    
    if not text:
        return {"status": "unknown", "detail": "无法获取指数数据"}
    
    summary = {}
    for line in text.strip().split("\n"):
        match = re.search(r'"(.+)"', line)
        if not match:
            continue
        fields = match.group(1).split(",")
        if len(fields) < 4:
            continue
        try:
            name = fields[0]
            prev_close = float(fields[2])
            price = float(fields[3])
            pct = round((price - prev_close) / prev_close * 100, 2)
            if "上证" in name:
                summary["sh_index"] = pct
            elif "深证" in name:
                summary["sz_index"] = pct
            elif "创业板" in name:
                summary["cyb_index"] = pct
        except (ValueError, IndexError):
            continue
    
    sh = summary.get("sh_index", 0) or 0
    if sh > 0.5:
        summary["market_mood"] = "强势"
    elif sh > -0.5:
        summary["market_mood"] = "震荡"
    elif sh > -1.5:
        summary["market_mood"] = "弱势"
    else:
        summary["market_mood"] = "危险"
    
    return summary


# ============================================================
# 快速全市场行情
# ============================================================

def fetch_top_stocks(limit=100):
    """
    快速获取涨幅靠前的股票
    先查上证部分，再查深证部分
    """
    query_ranges = [
        [f"6{i:05d}" for i in range(0, 1000)],
        [f"6{i:05d}" for i in range(1000, 2000)],
        [f"6{i:05d}" for i in range(2000, 3000)],
        [f"0{i:04d}" for i in range(1, 1000)],
        [f"00{i:04d}" for i in range(2001, 3000)],
        [f"30{i:04d}" for i in range(1, 500)],
    ]
    
    all_dfs = []
    for codes in query_ranges:
        df = batch_fetch_quotes(codes, batch_size=800)
        if df is not None:
            all_dfs.append(df)
        time.sleep(0.2)
    
    if all_dfs:
        result = pd.concat(all_dfs, ignore_index=True)
        result = result.sort_values("change_pct", ascending=False)
        logger.info(f"快速查询: 获取 {len(result)} 只, 涨幅>2%%: {(result['change_pct']>2).sum()} 只")
        return result.head(limit)
    return None


# ============================================================
# 涨停板数据
# ============================================================

def fetch_limit_up_stocks():
    """
    获取今日涨停股票列表 (涨幅 >= 9.8%)
    返回 [{"code": ..., "name": ..., "change_pct": ...}, ...]
    """
    df = fetch_top_stocks(limit=50)
    if df is None:
        return []
    
    limit_ups = df[df["change_pct"] >= 9.5]
    result = []
    for _, row in limit_ups.iterrows():
        result.append({
            "code": str(row["code"]),
            "name": str(row["name"]),
            "change_pct": float(row["change_pct"]),
        })
    
    return result


# ============================================================
# 市场情绪
# ============================================================

def get_market_sentiment():
    """
    获取市场情绪数据
    返回 dict: {zt_count, dt_count, zt_rate, sentiment}
    """
    df = fetch_top_stocks(limit=100)
    if df is None:
        return {}
    
    zt = len(df[df["change_pct"] >= 9.5])
    strong = len(df[df["change_pct"] >= 5.0])
    
    return {
        "zt_count": zt,          # 涨停数量
        "strong_count": strong,   # 大涨数量(>5%)
        "total_scanned": 100,
    }


# ============================================================
# 兼容旧接口
# ============================================================

def fetch_all_stocks_spot(max_retries=3):
    return fetch_top_stocks(limit=200)


def fetch_sectors_performance():
    return None


def get_top_sectors(sectors_df, top_n=10):
    return []


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    
    print("=" * 50)
    print("测试数据获取模块")
    print("=" * 50)
    
    market = get_market_summary()
    print(f"\n大盘: {market}")
    
    print("\n今日涨停:")
    zt = fetch_limit_up_stocks()
    for s in zt[:5]:
        print(f"  {s['code']} {s['name']}: {s['change_pct']:+.2f}%")
    
    print("\n涨幅靠前:")
    df = fetch_top_stocks(limit=10)
    if df is not None:
        for _, row in df.iterrows():
            print(f"  {row['code']} {row['name']}: {row['price']:.2f} ({row['change_pct']:+.2f}%)")
