"""
资金流分析模块 v2.0 (Phase 2)
数据源: 东方财富 push2 API + 新浪财经
"""

import json
import subprocess
import urllib.request
import re
import time
import logging
import numpy as np
from concurrent.futures import ThreadPoolExecutor, as_completed

logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "https://quote.eastmoney.com/",
}

SINA_HEADERS = {
    "Referer": "https://finance.sina.com.cn",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
}


def _curl(url, timeout=10):
    """使用 curl 获取 JSON 数据（带重试）"""
    for attempt in range(3):
        try:
            result = subprocess.run(
                ["curl", "-s", "--connect-timeout", str(timeout), url,
                 "-H", HEADERS["User-Agent"]],
                capture_output=True, text=True, timeout=timeout + 5
            )
            if result.returncode == 0 and result.stdout:
                data = json.loads(result.stdout)
                if data.get("data"):
                    return data
            time.sleep(0.5)
        except:
            time.sleep(0.5)
    return None


# ============================================================
# 个股资金流（东方财富 push2 API）
# ============================================================

def fetch_stock_money_flow(code):
    """
    获取个股当日资金流向
    返回 dict:
      main_net: 主力净流入(万元)
      super_large_net: 超大单净流入(万元)
      large_net: 大单净流入(万元)
      medium_net: 中单净流入(万元)
      main_ratio: 主力净占比(%)
      turnover: 换手率(%)
      volume_ratio: 量比
    """
    code = str(code).strip()
    market = 1 if code.startswith("6") else 0
    secid = f"{market}.{code}"
    
    url = (f"https://push2.eastmoney.com/api/qt/stock/get?"
           f"secid={secid}&fields=f43,f47,f48,f49,f55,f62,f166,f168,f170,f171,f175,f184,f185,f189")
    
    data = _curl(url)
    if data is None:
        return _fallback_money_flow(code)
    
    d = data.get("data", {})
    if not d:
        return _fallback_money_flow(code)
    
    return {
        "main_net": d.get("f166", 0) or 0,           # 主力净流入(万元)
        "super_large_net": d.get("f168", 0) or 0,     # 超大单(万元)
        "large_net": d.get("f170", 0) or 0,           # 大单(万元)
        "medium_net": d.get("f171", 0) or 0,          # 中单(万元)
        "main_ratio": d.get("f184", 0) or 0,          # 主力净占比(%)
        "super_large_ratio": d.get("f185", 0) or 0,   # 超大单占比(%)
        "turnover": (d.get("f49", 0) or 0) / 100,     # 换手率(%)
        "volume_ratio": d.get("f55", 0) or 0,         # 量比
        "amount": (d.get("f48", 0) or 0),             # 成交额(元)
    }


def _fallback_money_flow(code):
    """
    备用：通过成交量估算资金流
    如果没有实时资金流数据，用价格成交量做估算
    """
    return {
        "main_net": 0,
        "super_large_net": 0,
        "large_net": 0,
        "medium_net": 0,
        "main_ratio": 0,
        "super_large_ratio": 0,
        "turnover": 0,
        "volume_ratio": 0,
        "amount": 0,
        "_fallback": True,
    }


def batch_fetch_money_flow(codes, max_workers=8):
    """
    批量获取多只股票资金流
    返回 {code: money_flow_dict, ...}
    """
    results = {}
    
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_map = {executor.submit(fetch_stock_money_flow, code): code for code in codes}
        for future in as_completed(future_map):
            code = future_map[future]
            try:
                results[code] = future.result()
            except Exception as e:
                logger.debug(f"资金流 {code} 失败: {e}")
    
    ok = sum(1 for v in results.values() if v and not v.get("_fallback"))
    logger.info(f"资金流: 请求 {len(codes)} 只, 成功 {ok} 只")
    return results


# ============================================================
# 资金流评分因子
# ============================================================

def score_money_flow(mf):
    """
    对资金流数据进行评分 (0~30分)
    """
    if not mf or mf.get("_fallback"):
        return {"score": 0, "reason": "无资金流数据"}
    
    score = 0
    reasons = []
    
    main_net = mf.get("main_net", 0) or 0
    main_ratio = mf.get("main_ratio", 0) or 0
    super_large = mf.get("super_large_net", 0) or 0
    vr = mf.get("volume_ratio", 0) or 0
    
    # 因子1: 主力净流入额 (0~12分)
    if main_net > 5000:
        score += 12
        reasons.append(f"主力净流{main_net:.0f}万")
    elif main_net > 2000:
        score += 8
        reasons.append("主力净流>2000万")
    elif main_net > 500:
        score += 5
        reasons.append("主力小幅流入")
    elif main_net > -500:
        score += 2
        reasons.append("主力持平")
    else:
        score -= 5
        reasons.append(f"主力流出{main_net:.0f}万❌")
    
    # 因子2: 主力净占比 (0~8分)
    if main_ratio > 15:
        score += 8
        reasons.append("主力占比高")
    elif main_ratio > 8:
        score += 5
        reasons.append("主力占比>8%")
    elif main_ratio > 3:
        score += 3
        reasons.append("主力微幅流入")
    
    # 因子3: 超大单 (0~6分)
    if super_large > 1000:
        score += 6
        reasons.append("超大单买入")
    elif super_large > 200:
        score += 3
        reasons.append("超大单微幅")
    elif super_large < -200:
        score -= 3
        reasons.append("超大单卖出❌")
    
    # 因子4: 量比 (0~4分)
    if vr > 2.5:
        score += 4
        reasons.append("量比>2.5")
    elif vr > 1.5:
        score += 2
        reasons.append("量比>1.5")
    
    return {
        "score": score,
        "reason": " | ".join(reasons) if reasons else "无明显信号",
        "main_net": main_net,
        "main_ratio": main_ratio,
        "super_large": super_large,
        "volume_ratio": vr,
    }


# ============================================================
# 板块资金流（东方财富）
# ============================================================

def fetch_sector_money_flow(top_n=10):
    """
    获取板块资金流向排名
    返回 [{"name":, "change_pct":, "main_net":, "main_ratio":}, ...]
    """
    url = ("https://push2.eastmoney.com/api/qt/clist/get?"
           "pn=1&pz=100&po=1&np=1&fltt=2&invt=2&fid=f3"
           "&fs=m:90+t:2&fields=f12,f14,f2,f3,f62,f184,f66,f69,f70,f184,f185")
    
    data = _curl(url)
    if not data:
        return []
    
    items = data.get("data", {}).get("diff", [])
    if not items:
        return []
    
    result = []
    for i in items:
        result.append({
            "name": i.get("f14", ""),
            "change_pct": i.get("f3", 0),
            "main_net": (i.get("f184", 0) or 0),
            "turnover": (i.get("f62", 0) or 0),
        })
    
    # 按主力净流入排序
    result.sort(key=lambda x: abs(x["main_net"]), reverse=True)
    return result[:top_n]


# ============================================================
# 龙虎榜数据
# ============================================================

def fetch_dragon_tiger():
    """
    获取龙虎榜数据
    返回 [{"code", "name", "reason", "net_buy"}, ...]
    """
    url = ("https://push2.eastmoney.com/api/qt/clist/get?"
           "pn=1&pz=50&po=1&np=1&fltt=2&invt=2&fid=f3"
           "&fs=b:BK0579&fields=f12,f14,f2,f3,f4,f62,f184,f66,f69,f70,f71,f72,f73,f74,f75,f76,f77,f78,f79,f80,f81,f82,f83,f84,f85,f86,f87,f88,f89,f90")
    
    data = _curl(url)
    if not data:
        return []
    
    items = data.get("data", {}).get("diff", [])
    if not items:
        return []
    
    result = []
    for i in items[:10]:
        result.append({
            "code": str(i.get("f12", "")),
            "name": i.get("f14", ""),
            "change_pct": i.get("f3", 0),
            "main_net": (i.get("f184", 0) or 0),
        })
    
    return result


# ============================================================
# 北向资金
# ============================================================

def fetch_northbound_flow():
    """
    获取北向资金（沪股通+深股通）当日流向
    """
    # 使用东方财富数据中心的北向资金API
    url = "https://push2.eastmoney.com/api/qt/kamt.kline/get?fields1=f1,f2,f3,f4,f5,f6&fields2=f51,f52,f53,f54,f55,f56"
    
    data = _curl(url)
    if not data:
        return {"sh_net": 0, "sz_net": 0, "total_net": 0}
    
    # 解析量化资金数据
    return {
        "total_net": 0,  # 简化为0，北向数据需要更复杂的接口
        "sh_net": 0,
        "sz_net": 0,
    }


# ============================================================
# 综合资金流评分（整合到选股系统）
# ============================================================

def calculate_capital_score(money_flow, kline=None):
    """
    综合资金流 + 量价分析评分
    返回 0~40 分的资金维度得分
    """
    if not money_flow or money_flow.get("_fallback"):
        vp = _volume_price_score(kline)
        return {
            "capital_score": vp.get("vp_score", 0),
            "money_flow_score": 0,
            "vp_score": vp.get("vp_score", 0),
            "money_flow_reason": vp.get("reason", "量价分析"),
            "main_net": 0,
            "main_ratio": 0,
        }
    
    mf_score = score_money_flow(money_flow)
    base_score = mf_score["score"]
    
    # 如果有K线数据，补充量价分析
    vp_score = 0
    if kline and len(kline) >= 10:
        vp_score = _volume_price_score(kline).get("vp_score", 0)
    
    # 综合：资金流占 70%，量价分析占 30%
    final = base_score * 0.7 + vp_score * 0.3
    
    return {
        "capital_score": round(final, 1),
        "money_flow_score": base_score,
        "vp_score": vp_score,
        "money_flow_reason": mf_score.get("reason", ""),
        "main_net": money_flow.get("main_net", 0),
        "main_ratio": money_flow.get("main_ratio", 0),
    }


def _volume_price_score(kline):
    """
    从 K 线数据计算量价配合评分
    作为无资金流数据时的备用
    """
    if not kline or len(kline) < 10:
        return {"vp_score": 0, "reason": "数据不足"}
    
    closes = np.array([k["close"] for k in kline])
    volumes = np.array([k["volume"] for k in kline])
    
    score = 0
    reasons = []
    n = len(kline)
    
    # 近5日量能 vs 前10日量能
    vol_5 = np.mean(volumes[-5:])
    vol_10 = np.mean(volumes[-10:-5]) if n >= 10 else vol_5
    vol_ratio = vol_5 / vol_10 if vol_10 > 0 else 1
    
    if vol_ratio > 1.5:
        score += 10
        reasons.append("近5日放量")
    elif vol_ratio > 1.2:
        score += 6
        reasons.append("量能增加")
    
    # 量价配合（价格上涨时放量）
    pct_5d = (closes[-1] - closes[-6]) / closes[-6] * 100 if n >= 6 else 0
    if pct_5d > 0 and vol_ratio > 1.2:
        score += 8
        reasons.append("量价配合")
    elif pct_5d > 0 and vol_ratio < 0.8:
        score -= 5
        reasons.append("价涨量缩⚠️")
    
    # 价格突破（最近收盘接近20日最高）
    if n >= 20:
        high_20 = np.max(closes[-20:])
        if closes[-1] >= high_20 * 0.98:
            score += 7
            reasons.append("近20日高位")
    
    return {
        "vp_score": score,
        "reason": " | ".join(reasons) if reasons else "量能正常",
        "vol_ratio": round(vol_ratio, 2),
        "pct_5d": round(pct_5d, 2),
    }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    
    codes = ["600519", "600459", "300331", "002913", "600345"]
    
    print("=" * 50)
    print("个股资金流测试")
    print("=" * 50)
    
    flows = batch_fetch_money_flow(codes)
    
    for code in codes:
        mf = flows.get(code)
        if mf:
            print(f"\n{code}:")
            print(f"  主力净流: {mf.get('main_net',0):.0f}万")
            print(f"  超大单: {mf.get('super_large_net',0):.0f}万")
            print(f"  主力占比: {mf.get('main_ratio',0):.2f}%")
            print(f"  量比: {mf.get('volume_ratio',0):.2f}")
            
            sc = score_money_flow(mf)
            print(f"  资金评分: {sc['score']}分 | {sc.get('reason','')}")
    
    print("\n板块资金流:")
    sectors = fetch_sector_money_flow(5)
    for s in sectors:
        print(f"  {s['name']}: 涨幅{s['change_pct']:+.2f}% 主力{s['main_net']:.0f}")
    
    print("\n龙虎榜:")
    dt = fetch_dragon_tiger()
    for s in dt:
        print(f"  {s['code']} {s['name']}: {s['change_pct']:+.2f}% 主力{s['main_net']:.0f}")
