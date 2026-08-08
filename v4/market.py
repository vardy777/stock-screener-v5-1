"""V4-owned full-market state, sentiment and sector observability.

The legacy scheduler and dashboard paths may import these functions, but all
current-session market analytics are produced here.  Sector classification is
deliberately display-only until a point-in-time industry mapping reaches the
readiness threshold.
"""

from __future__ import annotations

import json
import math
from datetime import datetime
from pathlib import Path
from typing import Any, Dict

import pandas as pd

from decision_policy import market_is_risk_off, market_regime_score
from market_universe import is_eligible_a_share
from .execution import TradingClock
from .market_contracts import MarketSnapshotV1, MarketStateV1
from .snapshot_frame import snapshot_frame


ROOT = Path(__file__).resolve().parent.parent
MARKET_CACHE_PATH = ROOT / "v4" / "data" / "market_context.json"
MARKET_ANALYTICS_VERSION = "v4-market-v1"

SECTOR_KEYWORDS = [
    ("银行", ["银行", "工商", "建设", "农业", "中行", "招行", "兴业", "浦发", "民生", "中信银行"]),
    ("证券", ["证券", "券商", "中信建投", "华泰", "海通", "国泰", "广发"]),
    ("保险", ["保险", "人寿", "人保", "太保", "新华"]),
    ("白酒", ["茅台", "五粮液", "泸州", "汾酒", "洋河", "古井", "酒鬼"]),
    ("医药", ["医药", "药业", "医疗", "生物", "药明", "恒瑞", "片仔癀"]),
    ("房地产", ["地产", "万科", "保利", "华侨城", "金地"]),
    ("汽车", ["汽车", "比亚迪", "长城", "长安", "上汽"]),
    ("食品饮料", ["伊利", "双汇", "海天", "中炬"]),
    ("电子", ["电子", "海康", "大华", "京东方", "立讯"]),
    ("半导体", ["半导体", "芯片", "中芯", "华虹", "兆易"]),
    ("新能源", ["宁德", "隆基", "通威", "阳光", "天合"]),
    ("军工", ["军工", "航天", "航空", "中航", "中国船舶"]),
    ("钢铁", ["钢铁", "宝钢", "鞍钢", "首钢"]),
    ("煤炭", ["煤炭", "神华", "陕煤", "兖矿"]),
    ("电力", ["电力", "华能", "国电", "大唐", "长江电力"]),
    ("通信", ["移动", "联通", "电信", "中兴"]),
    ("计算机", ["软件", "计算机", "用友", "金山", "科大讯飞"]),
    ("家电", ["美的", "格力", "海尔", "海信"]),
    ("建筑", ["建筑", "基建", "中铁", "铁建", "交建", "中建"]),
    ("农业", ["牧原", "温氏", "新希望"]),
    ("化工", ["化工", "化学", "万华"]),
    ("有色", ["有色", "黄金", "铜", "铝业", "稀土"]),
    ("机械", ["机械", "装备", "三一", "中联"]),
    ("环保", ["环保", "环境", "碧水源"]),
    ("传媒", ["传媒", "文化", "光线", "分众"]),
]


def classify_sector(name: str) -> str:
    value = str(name or "")
    for sector, keywords in SECTOR_KEYWORDS:
        if any(keyword in value for keyword in keywords):
            return sector
    return "其他"


def empty_market_state() -> Dict[str, Any]:
    return {
        "sh_1d_pct": 0.0,
        "sh_5d_pct": 0.0,
        "sh_20d_pct": 0.0,
        "advance_ratio": 0.5,
        "market_mean_signal_return": 0.0,
        "market_equal_weight_pct": 0.0,
        "market_median_pct": 0.0,
        "market_mean_gap": 0.0,
        "regime_score": -1.0,
        "quote_coverage": 0.0,
        "fresh_quote_coverage": 0.0,
        "snapshot_complete": False,
        "data_valid": False,
        "composite": 0.0,
        "mode_label": "unavailable",
        "observed_mode_label": "unavailable",
        "expected_codes": 0,
        "observed_codes": 0,
        "fresh_codes": 0,
        "rise_count": 0,
        "fall_count": 0,
        "flat_count": 0,
        "limit_up_count": 0,
        "limit_down_count": 0,
        "limit_threshold_method": "unavailable",
        "rise_gt_5_count": 0,
        "fall_gt_5_count": 0,
        "rise_2_5_count": 0,
        "fall_2_5_count": 0,
        "market_total_amount_yi": 0.0,
        "amount_coverage": 0.0,
        "as_of": "",
        "data_source": "V4无可用全市场快照",
        "metric_definition": "无数据时禁止推断市场状态",
        "analytics_version": MARKET_ANALYTICS_VERSION,
    }


def _normalise_quotes(snapshot: MarketSnapshotV1) -> pd.DataFrame:
    quotes = snapshot_frame(snapshot)
    if quotes.empty:
        return pd.DataFrame()
    required = {"code", "price", "quote_time"}
    if not required.issubset(quotes.columns):
        return pd.DataFrame()
    frame = quotes.copy()
    frame["code"] = frame["code"].astype(str).str.zfill(6)
    frame = frame[frame["code"].map(is_eligible_a_share)].copy()
    frame["price"] = pd.to_numeric(frame["price"], errors="coerce")
    frame = frame[frame["price"].gt(0)].drop_duplicates("code", keep="last")
    if frame.empty:
        return frame
    parsed = pd.to_datetime(frame["quote_time"], errors="coerce")
    if parsed.notna().any():
        latest = parsed.max()
        same_session = parsed.dt.date.eq(latest.date())
        frame = frame.loc[same_session].copy()
    return frame


def build_market_state(snapshot: MarketSnapshotV1) -> MarketStateV1:
    """Build the canonical V4 market state from a full-market quote frame."""

    frame = _normalise_quotes(snapshot)
    expected_codes = snapshot.quality.expected_codes
    if frame.empty or not {"prev_close", "open"}.issubset(frame.columns):
        return MarketStateV1.build(snapshot, mode="unavailable", data_valid=False, metrics=empty_market_state(), analytics_version=MARKET_ANALYTICS_VERSION)
    pct = pd.to_numeric(
        frame.get("change_pct", frame.get("pct_chg")), errors="coerce"
    )
    valid = pct.notna()
    frame = frame.loc[valid].copy()
    pct = pct.loc[valid]
    if frame.empty:
        return MarketStateV1.build(snapshot, mode="unavailable", data_valid=False, metrics=empty_market_state(), analytics_version=MARKET_ANALYTICS_VERSION)
    parsed_time = pd.to_datetime(frame["quote_time"], errors="coerce")
    latest_time = parsed_time.max() if parsed_time.notna().any() else None
    fresh_mask = frame["quote_time"].map(TradingClock.quote_is_fresh)
    fresh_codes = int(frame.loc[fresh_mask, "code"].nunique())
    previous = pd.to_numeric(frame["prev_close"], errors="coerce")
    opened = pd.to_numeric(frame["open"], errors="coerce")
    breadth = float((pct > 0).mean())
    market_return = float(pct.mean() / 100.0)
    gap = (opened / previous - 1.0).replace([math.inf, -math.inf], float("nan"))
    market_gap = float(gap.dropna().mean()) if gap.notna().any() else 0.0
    expected = max(0, int(expected_codes or 0))
    coverage = min(1.0, len(frame) / expected) if expected else 0.0
    fresh_coverage = min(1.0, fresh_codes / expected) if expected else 0.0
    regime = market_regime_score(breadth, market_return, market_gap)
    observed_mode = (
        "risk_off"
        if market_is_risk_off(breadth, market_return, market_gap)
        else ("risk_on" if regime >= 0.35 else "neutral")
    )
    data_valid = bool(expected and fresh_coverage >= 0.95)
    amount = (
        pd.to_numeric(frame["amount"], errors="coerce")
        if "amount" in frame.columns
        else pd.Series(float("nan"), index=frame.index)
    )
    amount_valid = amount.gt(0)
    names = frame.get("name", pd.Series("", index=frame.index)).astype(str)
    limit_threshold = pd.Series(9.5, index=frame.index, dtype=float)
    limit_threshold.loc[frame["code"].str.startswith("30")] = 19.5
    limit_threshold.loc[names.str.contains("ST", case=False, na=False)] = 4.8
    metrics = {
        # Retained compatibility fields are explicitly equal-weight metrics.
        "sh_1d_pct": market_return * 100.0,
        "sh_5d_pct": 0.0,
        "sh_20d_pct": 0.0,
        "composite": regime * 3.0,
        "advance_ratio": breadth,
        "market_mean_signal_return": market_return,
        "market_equal_weight_pct": market_return * 100.0,
        "market_median_pct": float(pct.median()),
        "market_mean_gap": market_gap,
        "regime_score": regime,
        "quote_coverage": coverage,
        "fresh_quote_coverage": fresh_coverage,
        "snapshot_complete": bool(expected and coverage >= 0.95),
        "data_valid": data_valid,
        "mode_label": observed_mode if data_valid else "unavailable",
        "observed_mode_label": observed_mode,
        "expected_codes": expected,
        "observed_codes": int(len(frame)),
        "fresh_codes": fresh_codes,
        "rise_count": int((pct > 0).sum()),
        "fall_count": int((pct < 0).sum()),
        "flat_count": int((pct == 0).sum()),
        "limit_up_count": int((pct >= limit_threshold).sum()),
        "limit_down_count": int((pct <= -limit_threshold).sum()),
        "limit_threshold_method": "board_aware_proxy",
        "rise_gt_5_count": int((pct >= 5.0).sum()),
        "fall_gt_5_count": int((pct <= -5.0).sum()),
        "rise_2_5_count": int(((pct >= 2.0) & (pct < 5.0)).sum()),
        "fall_2_5_count": int(((pct <= -2.0) & (pct > -5.0)).sum()),
        "market_total_amount_yi": (
            float(amount[amount_valid].sum() / 1e8) if amount_valid.any() else 0.0
        ),
        "amount_coverage": float(amount_valid.mean()) if len(amount_valid) else 0.0,
        "as_of": latest_time.isoformat() if latest_time is not None else "",
        "earliest_quote_time": (
            parsed_time.min().isoformat() if parsed_time.notna().any() else ""
        ),
        "latest_quote_time": latest_time.isoformat() if latest_time is not None else "",
        "data_source": "V4新浪全市场批量行情快照",
        "metric_definition": "沪深主板及创业板可用样本；涨跌均值为全市场等权口径",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "analytics_version": MARKET_ANALYTICS_VERSION,
    }
    return MarketStateV1.build(
        snapshot, mode=metrics["mode_label"], data_valid=metrics["data_valid"],
        metrics=metrics, analytics_version=MARKET_ANALYTICS_VERSION,
    )


def build_sentiment(snapshot: MarketSnapshotV1) -> Dict[str, Any]:
    frame = _normalise_quotes(snapshot)
    if frame.empty:
        return {
            "limit_up": 0,
            "limit_down": 0,
            "up_ratio": 0.5,
            "avg_change": 0.0,
            "score": 5,
            "label": "不可用",
            "as_of": "",
            "source": "V4无可用全市场快照",
        }
    pct = pd.to_numeric(
        frame.get("change_pct", frame.get("pct_chg")), errors="coerce"
    )
    frame = frame.loc[pct.notna()].copy()
    pct = pct.loc[pct.notna()]
    if frame.empty:
        return {"limit_up": 0, "limit_down": 0, "up_ratio": 0.5, "avg_change": 0.0, "score": 5, "label": "不可用", "as_of": "", "source": "V4无可用全市场快照"}
    thresholds = pd.Series(9.5, index=frame.index, dtype=float)
    thresholds.loc[frame["code"].str.startswith("30")] = 19.5
    names = frame.get("name", pd.Series("", index=frame.index)).astype(str)
    thresholds.loc[names.str.contains("ST", case=False, na=False)] = 4.8
    limit_up = int((pct >= thresholds).sum())
    limit_down = int((pct <= -thresholds).sum())
    up_ratio = float((pct > 0).mean())
    avg_change = float(pct.mean())
    score = 5
    score += 2 if limit_up > 80 else (1 if limit_up > 50 else (-2 if limit_up < 10 else (-1 if limit_up < 20 else 0)))
    score -= 2 if limit_down > 30 else (1 if limit_down > 15 else 0)
    score += 1 if up_ratio > 0.7 else (-1 if up_ratio < 0.3 else 0)
    score += 1 if avg_change > 1.0 else (-1 if avg_change < -1.0 else 0)
    score = max(0, min(10, score))
    labels = {0: "恐慌", 2: "偏弱", 4: "中性", 6: "偏强", 8: "亢奋"}
    parsed = pd.to_datetime(frame["quote_time"], errors="coerce")
    return {
        "limit_up": limit_up,
        "limit_down": limit_down,
        "up_ratio": round(up_ratio, 4),
        "avg_change": round(avg_change, 3),
        "score": score,
        "label": labels.get(score - score % 2, "中性"),
        "as_of": parsed.max().isoformat() if parsed.notna().any() else "",
        "source": "V4全市场行情快照",
    }


def build_sector_ranks(snapshot: MarketSnapshotV1) -> Dict[str, Any]:
    frame = _normalise_quotes(snapshot)
    if frame.empty or "name" not in frame.columns:
        return {
            "top": [], "bottom": [], "activity_top": [], "time": "", "as_of": "",
            "total_sectors": 0, "classified_coverage": 0.0,
            "classification_reliable": False, "classification": "V4名称关键词代理行业",
            "market_total_amount_yi": 0.0, "observed_codes": 0,
        }
    pct_column = "change_pct" if "change_pct" in frame.columns else "pct_chg"
    frame[pct_column] = pd.to_numeric(frame[pct_column], errors="coerce")
    frame = frame.dropna(subset=[pct_column]).copy()
    frame["_sector"] = frame["name"].map(classify_sector)
    classified_coverage = float(frame["_sector"].ne("其他").mean()) if len(frame) else 0.0
    rankings = {}
    for sector, group in frame.groupby("_sector"):
        if len(group) < 3:
            continue
        amount = (
            pd.to_numeric(group["amount"], errors="coerce").fillna(0.0).sum()
            if "amount" in group.columns else 0.0
        )
        rankings[sector] = {
            "name": sector,
            "count": int(len(group)),
            "avg_pct": round(float(group[pct_column].mean()), 2),
            "up_ratio": round(float((group[pct_column] > 0).mean()), 4),
            "total_amount": round(float(amount) / 1e8, 1),
        }
    ordered = sorted(rankings.items(), key=lambda item: item[1]["avg_pct"], reverse=True)
    for rank, (_, info) in enumerate(ordered, start=1):
        info["rank"] = rank
    ordered_map = dict(ordered)
    named = [sector for sector, _ in ordered if sector != "其他"]
    reliable = bool(classified_coverage >= 0.60 and len(ordered_map) >= 15)
    parsed = pd.to_datetime(frame["quote_time"], errors="coerce")
    as_of = parsed.max().isoformat() if parsed.notna().any() else ""
    top = [
        {"sector": sector, **ordered_map[sector]} for sector in named[:5]
    ]
    bottom = [
        {"sector": sector, **ordered_map[sector]} for sector in reversed(named[-3:])
    ]
    activity_names = sorted(
        named,
        key=lambda sector: float(ordered_map[sector].get("total_amount", 0.0)),
        reverse=True,
    )[:5]
    return {
        "top": top,
        "bottom": bottom,
        "activity_top": [
            {"sector": sector, **ordered_map[sector]} for sector in activity_names
        ],
        "time": as_of,
        "as_of": as_of,
        "total_sectors": len(named),
        "classified_coverage": round(classified_coverage, 4),
        "classification_reliable": reliable,
        "classification": "V4名称关键词代理行业",
        "market_total_amount_yi": round(
            sum(float(item.get("total_amount", 0.0)) for item in ordered_map.values()), 1
        ),
        "observed_codes": int(len(frame)),
    }


def analyze_market(snapshot: MarketSnapshotV1) -> Dict[str, Any]:
    market_state = build_market_state(snapshot)
    payload = {
        "market_state": market_state.to_projection(),
        "sentiment": build_sentiment(snapshot),
        "sector_ranks": build_sector_ranks(snapshot),
        "analytics_version": MARKET_ANALYTICS_VERSION,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
    }
    MARKET_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary = MARKET_CACHE_PATH.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    temporary.replace(MARKET_CACHE_PATH)
    return payload


def load_market_cache() -> Dict[str, Any]:
    try:
        value = json.loads(MARKET_CACHE_PATH.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, TypeError, ValueError):
        return {}
