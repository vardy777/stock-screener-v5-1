"""V3 core watchlist monitoring and notification rendering.

This module restores the source contract used by
``v3/scripts/watchlist_scan.py``.  It only reports live observations and never
creates candidates or orders for the overnight strategy.
"""

from __future__ import annotations

import html
import json
import logging
import urllib.request
from datetime import datetime
from typing import Dict, List, Optional


logger = logging.getLogger(__name__)


# Keep the original eight-stock watchlist and its reporting thresholds.
WATCHLIST = [
    {"code": "sz000021", "name": "深科技", "sector": "半导体封测", "risk": "high", "strategy": "短线博弈", "target": 75.0, "stop": 49.6},
    {"code": "sz300223", "name": "北京君正", "sector": "存储芯片", "risk": "high", "strategy": "观望不参与", "target": 280.0, "stop": 204.0},
    {"code": "sh600030", "name": "中信证券", "sector": "券商龙头", "risk": "low", "strategy": "中期配置", "target": 31.0, "stop": 26.59},
    {"code": "sh600089", "name": "特变电工", "sector": "电力设备", "risk": "medium", "strategy": "趋势持有", "target": 26.0, "stop": 20.5},
    {"code": "sz000725", "name": "京东方A", "sector": "面板显示", "risk": "medium", "strategy": "波段操作", "target": 9.0, "stop": 7.2},
    {"code": "sh600346", "name": "恒力石化", "sector": "化工龙头", "risk": "medium", "strategy": "价值持有", "target": 22.0, "stop": 17.0},
    {"code": "sz300274", "name": "阳光电源", "sector": "光伏逆变器", "risk": "medium", "strategy": "趋势持有", "target": 175.0, "stop": 140.0},
    {"code": "sh603078", "name": "江化微", "sector": "电子化学品", "risk": "high", "strategy": "超短博弈", "target": 55.0, "stop": 40.0},
]


def _number(parts: List[str], index: int, cast=float, default=0):
    try:
        return cast(parts[index]) if parts[index] else default
    except (IndexError, TypeError, ValueError):
        return default


def fetch_quote(gtimg_code: str) -> Optional[Dict[str, float]]:
    """Fetch one real-time quote from Tencent's public quote endpoint."""

    url = f"https://qt.gtimg.cn/q={gtimg_code}"
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            parts = response.read().decode("gbk", errors="ignore").split("~")
        if len(parts) < 47:
            return None
        price = _number(parts, 3)
        if price <= 0:
            return None
        return {
            "name": parts[1],
            "code": parts[2],
            "price": price,
            "prev_close": _number(parts, 4),
            "open": _number(parts, 5),
            "volume": _number(parts, 6, int),
            "outer": _number(parts, 7, int),
            "inner": _number(parts, 8, int),
            "bid1_price": _number(parts, 9),
            "bid1_vol": _number(parts, 10, int),
            "ask1_price": _number(parts, 19),
            "ask1_vol": _number(parts, 20, int),
            "change_pct": _number(parts, 32),
            "high": _number(parts, 33),
            "low": _number(parts, 34),
            "amount": _number(parts, 37),
            "turnover": _number(parts, 38),
            "pe": _number(parts, 39),
            "limit_up": _number(parts, 41),
            "limit_down": _number(parts, 42),
            "amplitude": _number(parts, 43),
            "float_mcap": _number(parts, 44),
            "total_mcap": _number(parts, 45),
            "pb": _number(parts, 46),
        }
    except Exception as exc:
        logger.warning("fetch %s failed: %s", gtimg_code, exc)
        return None


def fetch_daily_kline(gtimg_code: str, days: int = 30) -> Optional[Dict[str, List[float]]]:
    """Fetch adjusted daily closes and volumes for display-only indicators."""

    url = (
        "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param="
        f"{gtimg_code},day,,,{int(days)},qfq"
    )
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            payload = json.loads(response.read().decode("utf-8"))
        item = payload.get("data", {}).get(gtimg_code, {})
        rows = item.get("qfqday") or item.get("day") or []
        closes = []
        volumes = []
        for row in rows:
            if len(row) < 6:
                continue
            try:
                closes.append(float(row[2]))
                volumes.append(float(row[5]))
            except (TypeError, ValueError):
                continue
        if not closes:
            return None
        return {"closes": closes, "volumes": volumes}
    except Exception as exc:
        logger.warning("kline %s failed: %s", gtimg_code, exc)
        return None


def calc_technical(quote: Dict, kline: Optional[Dict]) -> Dict[str, float]:
    """Calculate the small indicator set used by the legacy watchlist card."""

    price = float(quote.get("price", 0) or 0)
    if not kline or len(kline.get("closes", [])) < 5:
        return {
            "ma5": price,
            "ma10": price,
            "ma20": price,
            "vs_ma5": 0.0,
            "vs_ma20": 0.0,
            "vol_ratio": 1.0,
            "ma_alignment": 0,
            "momentum_5d": 2,
            "vol_5": 0.0,
            "vol_20": 0.0,
        }

    closes = [float(value) for value in kline["closes"]]
    volumes = [float(value) for value in kline.get("volumes", [])]
    if len(volumes) < len(closes):
        volumes = ([0.0] * (len(closes) - len(volumes))) + volumes
    count = len(closes)
    ma5 = sum(closes[-5:]) / 5
    ma10 = sum(closes[-10:]) / 10 if count >= 10 else ma5
    ma20 = sum(closes[-20:]) / 20 if count >= 20 else ma10
    vol5 = sum(volumes[-5:]) / 5
    vol20 = sum(volumes[-20:]) / 20 if count >= 20 else vol5
    if price > ma5 > ma10 > ma20:
        alignment = 30
    elif price > ma5:
        alignment = 15
    elif price > ma20:
        alignment = 5
    else:
        alignment = 0
    return {
        "ma5": ma5,
        "ma10": ma10,
        "ma20": ma20,
        "vs_ma5": (price / ma5 - 1) * 100 if ma5 else 0.0,
        "vs_ma20": (price / ma20 - 1) * 100 if ma20 else 0.0,
        "vol_5": vol5,
        "vol_20": vol20,
        "vol_ratio": volumes[-1] / vol5 if vol5 and volumes else 1.0,
        "ma_alignment": alignment,
        "momentum_5d": sum(
            1 for index in range(-5, -1) if closes[index] > closes[index - 1]
        ),
    }


def assess_risk(quote: Dict, tech: Dict, stock: Dict) -> str:
    """Return the original compact risk explanation string."""

    del stock  # retained in the public signature for compatibility
    signals = []
    pe = float(quote.get("pe", 0) or 0)
    if pe > 100:
        signals.append("PE>100x")
    elif pe > 50:
        signals.append("PE偏高")
    distance = float(tech.get("vs_ma20", 0) or 0)
    if distance > 30:
        signals.append("严重偏离MA20")
    elif distance > 15:
        signals.append("偏离MA20")
    turnover = float(quote.get("turnover", 0) or 0)
    if turnover > 15:
        signals.append(f"超高换手{turnover:.0f}%")
    amplitude = float(quote.get("amplitude", 0) or 0)
    if amplitude > 8:
        signals.append(f"振幅{amplitude:.1f}%")
    outer = float(quote.get("outer", 0) or 0)
    inner = float(quote.get("inner", 0) or 0)
    if outer > 0 and inner > 0 and outer / (outer + inner) < 0.45:
        signals.append("主动卖盘占优")
    return " | ".join(signals) if signals else "✅ 无异常"


def generate_advice(quote: Dict, tech: Dict, stock: Dict) -> Dict:
    """Generate the legacy watchlist wording; this is not a V4 trade signal."""

    price = float(quote.get("price", 0) or 0)
    if price <= 0:
        return {
            "action": "❌ 数据获取失败",
            "level": "error",
            "to_target_pct": 0.0,
            "to_stop_pct": 0.0,
            "risk_flags": "数据异常",
        }
    target = float(stock["target"])
    stop = float(stock["stop"])
    change = float(quote.get("change_pct", 0) or 0)
    to_target = (target / price - 1) * 100
    to_stop = (price / stop - 1) * 100

    if change >= 9.9:
        bid_volume = int(quote.get("bid1_vol", 0) or 0)
        if bid_volume > 50_000:
            action, level = f"🟢 涨停封板强(封单{bid_volume}手)，持有", "hold"
        else:
            action, level = f"🟡 涨停封单弱(封单{bid_volume}手)，建议减仓50%", "reduce"
    elif change >= 5:
        action, level = f"🟡 强势拉升+{change:.1f}%，关注封板力度", "hold"
    elif change >= 0:
        if tech.get("ma_alignment", 0) >= 15 and tech.get("vol_ratio", 1) > 1.2:
            action, level = "🟢 放量多头排列，持有/可加仓", "buy"
        elif to_stop < 10:
            action, level = f"🟡 接近止损位({stop})，密切关注", "reduce"
        else:
            action, level = "🟢 趋势正常，继续持有", "hold"
    elif change > -3:
        action, level = "🟡 小幅回调，观察", "hold"
    elif price <= stop:
        action, level = f"🔴 跌破止损价{stop}！建议立即清仓", "sell"
    else:
        action, level = f"🔴 大跌{change:.1f}%，接近止损线", "reduce"

    if stock["code"] == "sz300223" and stock["strategy"] == "观望不参与":
        action, level = "⚪ 观望（PE 188x+高波动），不参与", "watch"
    return {
        "action": action,
        "level": level,
        "to_target_pct": round(to_target, 1),
        "to_stop_pct": round(to_stop, 1),
        "risk_flags": assess_risk(quote, tech, stock),
    }


def _error_result(stock: Dict, fetch_time: str) -> Dict:
    return {
        **stock,
        "price": 0.0,
        "change_pct": 0.0,
        "pe": 0.0,
        "pb": 0.0,
        "turnover": 0.0,
        "amount": 0.0,
        "volume": 0.0,
        "outer": 0,
        "inner": 0,
        "amplitude": 0.0,
        "ma5": 0.0,
        "ma20": 0.0,
        "vs_ma5": 0.0,
        "vs_ma20": 0.0,
        "vol_ratio": 1.0,
        "ma_alignment": 0,
        "momentum_5d": 0,
        "action": "❌ 数据获取失败",
        "level": "error",
        "to_target_pct": 0.0,
        "to_stop_pct": 0.0,
        "risk_flags": "数据异常",
        "fetch_time": fetch_time,
    }


def scan_all() -> List[Dict]:
    """Scan all eight watchlist stocks without inventing fallback prices."""

    results = []
    fetch_time = datetime.now().strftime("%H:%M:%S")
    for stock in WATCHLIST:
        try:
            quote = fetch_quote(stock["code"])
            if not quote:
                results.append(_error_result(stock, fetch_time))
                continue
            technical = calc_technical(
                quote, fetch_daily_kline(stock["code"], 30)
            )
            advice = generate_advice(quote, technical, stock)
            result = {
                "code": stock["code"],
                "name": stock["name"],
                "sector": stock["sector"],
                "risk": stock["risk"],
                "strategy": stock["strategy"],
                "price": round(float(quote["price"]), 2),
                "change_pct": round(float(quote.get("change_pct", 0)), 2),
                "pe": round(float(quote.get("pe", 0)), 1),
                "pb": round(float(quote.get("pb", 0)), 2),
                "turnover": round(float(quote.get("turnover", 0)), 2),
                "amount": round(float(quote.get("amount", 0)) / 10_000, 2),
                "volume": round(float(quote.get("volume", 0)) / 10_000, 1),
                "outer": int(quote.get("outer", 0) or 0),
                "inner": int(quote.get("inner", 0) or 0),
                "amplitude": round(float(quote.get("amplitude", 0)), 2),
                "ma5": round(float(technical["ma5"]), 2),
                "ma20": round(float(technical["ma20"]), 2),
                "vs_ma5": round(float(technical["vs_ma5"]), 1),
                "vs_ma20": round(float(technical["vs_ma20"]), 1),
                "vol_ratio": round(float(technical["vol_ratio"]), 2),
                "ma_alignment": int(technical["ma_alignment"]),
                "momentum_5d": int(technical["momentum_5d"]),
                **advice,
                "fetch_time": fetch_time,
            }
            results.append(result)
            logger.info(
                "  %-6s %8.2f %+6.2f%% | %s",
                stock["name"],
                quote["price"],
                quote.get("change_pct", 0),
                advice["action"],
            )
        except Exception as exc:
            logger.exception("watchlist scan failed for %s: %s", stock["code"], exc)
            results.append(_error_result(stock, fetch_time))
    return results


def build_push_html(results: List[Dict]) -> str:
    """Build the PushPlus HTML card used by the existing scheduler script."""

    now = datetime.now()
    weekday = "一二三四五六日"[now.weekday()]
    rises = sum(float(item.get("change_pct", 0)) > 0 for item in results)
    falls = sum(float(item.get("change_pct", 0)) < 0 for item in results)
    limits = sum(float(item.get("change_pct", 0)) >= 9.9 for item in results)
    reductions = sum(item.get("level") in {"reduce", "sell"} for item in results)
    parts = [
        f"<h3>📊 核心关注 · {now:%m/%d} {now:%H:%M} 周{weekday}</h3>",
        f"<p>⬆{rises}只 ⬇{falls}只 | 🚀涨停{limits}只"
        + (f" | ⚠️减仓{reductions}只" if reductions else "")
        + "</p><hr>",
    ]
    labels = {"high": "🔴 高风险博弈", "medium": "🟡 中风险趋势", "low": "🟢 低风险配置"}
    for risk in ("high", "medium", "low"):
        group = [item for item in results if item.get("risk") == risk]
        if not group:
            continue
        parts.append(f"<h4>{labels[risk]}</h4>")
        for item in sorted(group, key=lambda row: row.get("change_pct", 0), reverse=True):
            change = float(item.get("change_pct", 0) or 0)
            color = "#ff4757" if change > 0 else "#2ed573" if change < 0 else "#888"
            border = "#e94560" if item.get("level") in {"sell", "reduce", "error"} else "#48dbfb" if item.get("level") == "watch" else "#2ed573"
            parts.append(
                f'<div style="margin:6px 0;padding:8px;background:#1a1a2e;border-left:3px solid {border};border-radius:4px;">'
                f'<b>{html.escape(str(item.get("name", "")))}</b> {float(item.get("price", 0)):.2f} '
                f'<span style="color:{color}">{change:+.2f}%</span> '
                f'<span style="color:#5a7a9a;font-size:11px">距止损{float(item.get("to_stop_pct", 0)):.1f}% '
                f'换手{float(item.get("turnover", 0)):.1f}%</span><br>'
                f'<span style="font-size:12px">{html.escape(str(item.get("action", "")))}</span></div>'
            )
    parts.append(f'<p style="color:#3a4a6a;font-size:10px;margin-top:8px">⏰ {now:%H:%M} | 下次扫描30分钟后 | 仅供参考</p>')
    return "".join(parts)


def build_simple_text(results: List[Dict]) -> str:
    """Build a console fallback when PushPlus is unavailable."""

    return "\n".join(
        f'{item.get("name", ""):6s} {float(item.get("price", 0)):8.2f} '
        f'{float(item.get("change_pct", 0)):+7.2f}% | {item.get("action", "")}'
        for item in results
    )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    scanned = scan_all()
    print(build_simple_text(scanned))

