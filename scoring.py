"""
科学打分模型 v3.0 (Phase 3)
因子归一化、自适应权重、置信度评估
"""

import numpy as np
from collections import defaultdict

from config import SCORING_WEIGHTS, TECHNICAL_FILTERS


# ============================================================
# 因子归一化 (Min-Max / 百分位)
# ============================================================

def normalize(values, method="minmax"):
    """
    将一组值归一化到 0~100
    method: minmax / percentile
    """
    values = np.array(values, dtype=float)
    if len(values) == 0:
        return values
    
    if method == "minmax":
        mn, mx = np.min(values), np.max(values)
        if mx - mn == 0:
            return np.full_like(values, 50)
        return (values - mn) / (mx - mn) * 100
    
    elif method == "percentile":
        # 百分位排名
        ranks = np.argsort(np.argsort(values))
        return ranks / (len(values) - 1) * 100 if len(values) > 1 else np.array([50])
    
    return values


# ============================================================
# 综合因子打分 (Phase 3 advanced)
# ============================================================

class StockScorer:
    """
    选股评分器
    对所有候选股进行统一的因子计算、归一化、加权
    """
    
    def __init__(self):
        self.weights = SCORING_WEIGHTS
        self.candidates = []  # 原始数据
        self.scores = []      # 评分结果
    
    def add_candidates(self, stock_list):
        """
        添加候选股数据
        stock_list: [{
            code, name, price, change_pct, close_position,
            tech_score, capital_score, main_net, main_ratio,
            ma_bullish, macd_golden, candle_body_pct, amount, ...
        }, ...]
        """
        self.candidates = stock_list
    
    def _compute_factor_scores(self, stocks):
        """
        对一组股票计算所有因子的归一化得分
        返回 [{
            code, name,
            f_tech,        # 技术面 0~100
            f_capital,     # 资金流 0~100
            f_position,    # 日内位置 0~100
            f_momentum,    # 动量 0~100
            f_volume,      # 量能 0~100
            f_ma,          # 均线 0/50/100 (是否多头)
            f_macd,        # MACD 0/50/100
            total_score,   # 加权总分
            confidence,    # 置信度 0~100
        }, ...]
        """
        n = len(stocks)
        if n == 0:
            return []
        
        # 1. 提取原始值
        tech_vals = np.array([s.get("tech_score", 0) for s in stocks], dtype=float)
        cap_vals = np.array([s.get("capital_score", 0) for s in stocks], dtype=float)
        pos_vals = np.array([s.get("close_position", 0.5) for s in stocks], dtype=float)
        mom_vals = np.array([abs(s.get("change_pct", 0)) for s in stocks], dtype=float)
        vol_vals = np.array([s.get("amount", 0) for s in stocks], dtype=float)
        body_vals = np.array([s.get("candle_body_pct", 0) for s in stocks], dtype=float)
        main_vals = np.array([s.get("main_net", 0) for s in stocks], dtype=float)
        
        # 2. 归一化 (百分位排名)
        # 有些因子可能缺失(比如资金流), 缺失的用中位数填充
        tech_norm = normalize(tech_vals, "percentile")
        cap_norm = normalize(cap_vals, "percentile")
        pos_norm = normalize(pos_vals * 100, "percentile")
        mom_norm = normalize(mom_vals, "percentile")
        vol_norm = normalize(vol_vals, "percentile")
        body_norm = normalize(body_vals, "percentile")
        
        # 资金流另外做加权（主力净流入绝对值大的加分）
        main_effect = np.clip(main_vals / 5000, -1, 1) * 50 + 50  # -1~1 -> 0~100
        
        # 3. 离散因子转换
        ma_scores = np.array([80 if s.get("ma_bullish") else 20 for s in stocks])
        macd_scores = np.array([80 if s.get("macd_golden") else 30 for s in stocks])
        
        # 4. 因子加权综合
        w = self.weights
        total_scores = (
            pos_norm * w.get("close_position", 0.35) +
            mom_norm * w.get("change_pct", 0.20) +
            tech_norm * w.get("tech_score", 0.20) +
            cap_norm * w.get("capital_score", 0.10) * 0.6 + main_effect * 0.4 +
            ma_scores * w.get("ma_bonus", 0.08) +
            macd_scores * w.get("macd_bonus", 0.07)
        )
        
        # 5. 置信度计算
        # 基于: 因子数量、数值极端程度
        confidences = []
        for i in range(n):
            s = stocks[i]
            factors_available = 0
            if s.get("tech_score", 0) > 0: factors_available += 1
            if s.get("capital_score", 0) > 0: factors_available += 1
            if s.get("main_net", 0) != 0: factors_available += 1
            
            # 因子一致性：多个因子方向一致则置信度高
            agreement = 0
            if s.get("ma_bullish"): agreement += 1
            if s.get("macd_golden"): agreement += 1
            if s.get("capital_score", 0) > 50: agreement += 1
            
            confidence = min(100, factors_available * 20 + agreement * 15)
            confidences.append(confidence)
        
        # 构建结果
        results = []
        for i, s in enumerate(stocks):
            results.append({
                "code": s.get("code", ""),
                "name": s.get("name", ""),
                "price": s.get("price", 0),
                "change_pct": s.get("change_pct", 0),
                "f_tech": round(tech_norm[i], 1),
                "f_capital": round(cap_norm[i], 1),
                "f_position": round(pos_norm[i], 1),
                "f_momentum": round(mom_norm[i], 1),
                "f_volume": round(vol_norm[i], 1),
                "f_ma": round(ma_scores[i], 0),
                "f_macd": round(macd_scores[i], 0),
                "total_score": round(total_scores[i], 2),
                "confidence": round(confidences[i], 0),
                "main_net": s.get("main_net", 0),
                "tech_score": s.get("tech_score", 0),
                "capital_score": s.get("capital_score", 0),
                "ma_bullish": s.get("ma_bullish", False),
                "macd_golden": s.get("macd_golden", False),
            })
        
        # 排序
        results.sort(key=lambda r: r["total_score"], reverse=True)
        self.scores = results
        return results
    
    def get_top(self, n=5, min_confidence=30):
        """获取前 N 名"""
        if not self.scores:
            return []
        filtered = [s for s in self.scores if s["confidence"] >= min_confidence]
        return filtered[:n] if filtered else self.scores[:n]
    
    def print_ranking(self, top_n=15):
        """打印排名"""
        if not self.scores:
            print("  无评分数据")
            return
        
        print(f"\n{'='*100}")
        print(f"  📊 综合评分排名 (Phase 3 科学打分)")
        print(f"{'='*100}")
        print(f"{'#':>3} {'代码':>8} {'名称':<8} {'涨幅':>7} {'技术':>6} {'资金':>6} {'位置':>6} {'动量':>6} {'均线':>5} {'MACD':>5} {'总分':>7} {'置信':>5}")
        print(f"{'-'*3} {'-':-<8} {'-':-<8} {'-':-<7} {'-':-<6} {'-':-<6} {'-':-<6} {'-':-<6} {'-':-<5} {'-':-<5} {'-':-<7} {'-':-<5}")
        
        for i, s in enumerate(self.scores[:top_n]):
            ma_icon = "✅" if s["ma_bullish"] else "❌"
            macd_icon = "✅" if s["macd_golden"] else "❌"
            print(f"{i+1:>3} {s['code']:>8} {s['name']:<8} "
                  f"{s['change_pct']:>+7.2f}% "
                  f"{s['f_tech']:>6.0f} {s['f_capital']:>6.0f} "
                  f"{s['f_position']:>6.0f} {s['f_momentum']:>6.0f} "
                  f"{ma_icon:>4} {macd_icon:>4} "
                  f"{s['total_score']:>7.2f} {s['confidence']:>5.0f}")
        
        print(f"{'='*100}")
        print(f"  💡 置信度>50: 高确定性 | 40-50: 中等 | <40: 谨慎参与")


def score_with_model(stocks):
    """快捷接口：传入股票列表，返回排序后的评分结果"""
    scorer = StockScorer()
    scorer.add_candidates(stocks)
    return scorer._compute_factor_scores(stocks)


if __name__ == "__main__":
    # 测试
    test_stocks = [
        {"code": "300331", "name": "苏大维格", "price": 71.74, "change_pct": 6.55,
         "tech_score": 90, "capital_score": 21, "main_net": 7817, "close_position": 0.85,
         "ma_bullish": True, "macd_golden": True, "amount": 2e9, "candle_body_pct": 3.2},
        {"code": "600459", "name": "贵研铂业", "price": 27.68, "change_pct": 6.50,
         "tech_score": 90, "capital_score": 7, "main_net": -625, "close_position": 0.78,
         "ma_bullish": True, "macd_golden": True, "amount": 2.6e9, "candle_body_pct": 2.8},
        {"code": "002174", "name": "游族网络", "price": 11.82, "change_pct": 6.58,
         "tech_score": 32, "capital_score": 18, "main_net": 500, "close_position": 0.65,
         "ma_bullish": True, "macd_golden": False, "amount": 9.3e8, "candle_body_pct": 1.5},
    ]
    
    results = score_with_model(test_stocks)
    scorer = StockScorer()
    scorer.scores = results
    scorer.print_ranking()
    
    print(f"\nTop 1: {results[0]['code']} {results[0]['name']} 总分{results[0]['total_score']}")
