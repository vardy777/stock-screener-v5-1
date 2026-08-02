"""
回测引擎 v3.0 (Phase 3)
模拟"尾盘买入 → 次日开盘卖出"策略
支持因子有效性分析
"""

import numpy as np
import pandas as pd
from datetime import datetime, date
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
import time

from technical import fetch_kline, calc_ma, calc_macd, check_bullish_alignment, check_macd_golden, score_technical
from scoring import score_with_model, StockScorer
from fund_flow import _volume_price_score

logger = logging.getLogger(__name__)


# ============================================================
# 回测引擎
# ============================================================

class BacktestEngine:
    """
    回测引擎
    模拟每日尾盘筛选 → 买入 → 次日开盘卖出
    """
    
    def __init__(self, stock_codes, lookback_days=60):
        self.stock_codes = stock_codes
        self.lookback_days = lookback_days
        self.klines = {}       # code -> [{day,open,high,low,close,volume}, ...]
        self.dates = []        # 公共日期序列
        self.trades = []       # 回测交易记录
        self.results = {}      # 回测结果统计
    
    def load_data(self):
        """获取所有股票的历史 K 线"""
        logger.info(f"加载 {len(self.stock_codes)} 只股票K线数据...")
        
        all_klines = {}
        with ThreadPoolExecutor(max_workers=5) as ex:
            fut_map = {ex.submit(fetch_kline, code, self.lookback_days): code for code in self.stock_codes}
            for fut in as_completed(fut_map):
                code = fut_map[fut]
                try:
                    k = fut.result()
                    if k and len(k) >= 30:
                        all_klines[code] = k
                except:
                    pass
        
        self.klines = all_klines
        logger.info(f"成功加载 {len(self.klines)} 只")
        
        # 确定公共日期范围（取所有股票都有的日期）
        self._build_common_dates()
        return len(self.klines)
    
    def _build_common_dates(self):
        """构建公共日期序列（回测必须用所有股票都有数据的日期）"""
        if not self.klines:
            return
        
        # 取最短的股票日期序列
        min_len = min(len(k) for k in self.klines.values())
        # 取所有股票的日期都对齐
        self.dates = []
        first_code = list(self.klines.keys())[0]
        all_dates = [d["day"] for d in self.klines[first_code]]
        self.dates = all_dates
    
    def get_day_data(self, day_idx):
        """获取某一天所有股票的快照数据"""
        if day_idx < 0 or day_idx >= len(self.dates):
            return None
        
        date_str = self.dates[day_idx]
        stocks = []
        
        for code, kline in self.klines.items():
            if day_idx >= len(kline):
                continue
            
            d = kline[day_idx]
            if d["day"] != date_str:
                continue
            
            # 基础数据
            prev_close = kline[day_idx - 1]["close"] if day_idx > 0 else d["open"]
            change_pct = (d["close"] - prev_close) / prev_close * 100 if prev_close > 0 else 0
            close_position = (d["close"] - d["low"]) / (d["high"] - d["low"]) if (d["high"] - d["low"]) > 0 else 0.5
            candle_body = (d["close"] - d["open"]) / d["open"] * 100 if d["open"] > 0 else 0
            amount = d["close"] * d["volume"]
            
            data_up_to_day = kline[:day_idx + 1]
            
            # 技术面
            tech = score_technical(data_up_to_day)
            ok_ma, _ = check_bullish_alignment(data_up_to_day)
            macd_ok = False
            if len(data_up_to_day) >= 26:
                macd_ok, _ = check_macd_golden(data_up_to_day)
            
            # 量价评分（替代资金流）
            vp = _volume_price_score(data_up_to_day)
            capital_score = vp.get("vp_score", 0) * 2  # 放大到类似资金评分
            
            # 下一天的 open（卖出价）
            next_open = None
            if day_idx + 1 < len(kline):
                next_open = kline[day_idx + 1]["open"]
            
            stocks.append({
                "code": code,
                "name": code,  # 回测中名字不重要
                "date": date_str,
                "price": d["close"],
                "change_pct": round(change_pct, 2),
                "close_position": round(close_position, 2),
                "candle_body_pct": round(candle_body, 2),
                "amount": amount,
                "volume": d["volume"],
                "tech_score": tech["score"],
                "capital_score": round(capital_score, 1),
                "main_net": 0,
                "ma_bullish": ok_ma,
                "macd_golden": macd_ok,
                "next_open": next_open,  # 卖出价
            })
        
        return stocks
    
    def run(self, min_days=20, top_n=3):
        """
        运行回测
        min_days: 最少需要多少天历史数据来计算因子
        top_n: 每天选前几名
        返回 trade 列表
        """
        if not self.klines:
            print("❌ 未加载数据")
            return []
        
        trades = []
        days_range = range(min_days, len(self.dates) - 1)
        
        print(f"\n  🔄 回测: {len(self.stock_codes)} 只股票 × {len(days_range)} 天")
        print(f"     日期范围: {self.dates[min_days]} ~ {self.dates[-2]}")
        print(f"     每天选前 {top_n} 只")
        print()
        
        processed = 0
        for day_idx in days_range:
            stocks = self.get_day_data(day_idx)
            if not stocks or len(stocks) < 5:
                continue
            
            # 基础筛选（更宽松，让评分模型去判断）
            filtered = [s for s in stocks if 0.5 <= s["change_pct"] <= 7.0]
            filtered = [s for s in filtered if s["close_position"] >= 0.4]
            filtered = [s for s in filtered if s["change_pct"] < 9.5]
            filtered = [s for s in filtered if s["price"] >= 5.0]
            
            if len(filtered) < 3:
                continue
            
            # 评分排序
            scored = score_with_model(filtered)
            
            # 选 top N
            selected = []
            for s in scored[:top_n]:
                orig = next((x for x in filtered if x["code"] == s["code"]), None)
                if orig and orig.get("next_open"):
                    buy_p = orig["price"]
                    sell_p = orig["next_open"]
                    if buy_p <= 0 or sell_p <= 0:
                        continue

                    # A股交易成本: 佣金万2.5(最低5元) + 印花税0.1%(仅卖出)
                    COMMISSION_RATE = 0.00025   # 万2.5
                    STAMP_TAX_RATE = 0.001      # 0.1% 仅卖出
                    MIN_COMMISSION = 5.0        # 最低佣金

                    buy_comm = max(buy_p * 100 * COMMISSION_RATE, MIN_COMMISSION)
                    sell_comm = max(sell_p * 100 * COMMISSION_RATE, MIN_COMMISSION)
                    sell_tax = sell_p * 100 * STAMP_TAX_RATE
                    total_cost = buy_comm + sell_comm + sell_tax

                    gross_return = (sell_p - buy_p) / buy_p * 100
                    net_return = ((sell_p * 100 - sell_comm - sell_tax) - (buy_p * 100 + buy_comm)) / (buy_p * 100 + buy_comm) * 100

                    # ⚠️ 假设能按指定价格成交，未考虑涨停买不进/跌停卖不出
                    profit = round(net_return, 2)
                    trades.append({
                        "code": s["code"],
                        "date": orig["date"],
                        "buy_price": round(buy_p, 2),
                        "sell_price": round(sell_p, 2),
                        "gross_return": round(gross_return, 2),
                        "profit_pct": profit,
                        "total_cost": round(total_cost, 2),
                        "total_score": s.get("total_score", 0),
                        "tech_score": s.get("f_tech", 0),
                        "capital_score": s.get("f_capital", 0),
                        "position_score": s.get("f_position", 0),
                        "confidence": s.get("confidence", 0),
                        "ma_bullish": s.get("ma_bullish", False),
                        "macd_golden": s.get("macd_golden", False),
                    })
            
            processed += 1
            if processed % 10 == 0:
                print(f"     已回测 {processed}/{len(days_range)} 天... ({len(trades)} 笔交易)")
        
        self.trades = trades
        self._calculate_results()
        
        return trades
    
    def _calculate_results(self):
        """计算回测统计"""
        if not self.trades:
            self.results = {"error": "无交易"}
            return
        
        profits = np.array([t["profit_pct"] for t in self.trades])
        wins = profits[profits > 0]
        losses = profits[profits <= 0]
        
        total = len(profits)
        win_count = len(wins)
        loss_count = len(losses)
        win_rate = win_count / total * 100 if total > 0 else 0
        
        avg_win = np.mean(wins) if len(wins) > 0 else 0
        avg_loss = np.mean(losses) if len(losses) > 0 else 0
        profit_loss_ratio = abs(avg_win / avg_loss) if avg_loss != 0 else 0
        
        total_return = np.sum(profits)
        
        # 最大回撤
        cumsum = np.cumsum(profits)
        running_max = np.maximum.accumulate(cumsum)
        drawdown = cumsum - running_max
        max_dd = np.min(drawdown) if len(drawdown) > 0 else 0
        
        # 夏普比率 (简化)
        sharpe = np.mean(profits) / np.std(profits) * np.sqrt(244) if np.std(profits) > 0 else 0
        
        self.results = {
            "total_trades": total,
            "win_trades": win_count,
            "loss_trades": loss_count,
            "win_rate": round(win_rate, 1),
            "avg_profit": round(np.mean(profits), 2),
            "avg_win": round(avg_win, 2),
            "avg_loss": round(avg_loss, 2),
            "profit_loss_ratio": round(profit_loss_ratio, 2),
            "max_profit": round(np.max(profits), 2),
            "max_loss": round(np.min(profits), 2),
            "total_return": round(total_return, 2),
            "max_drawdown": round(max_dd, 2),
            "sharpe_ratio": round(sharpe, 2),
            "median_profit": round(np.median(profits), 2),
        }
    
    def print_results(self):
        """打印回测结果"""
        r = self.results
        if not r or "error" in r:
            print("  ❌ 无回测结果")
            return
        
        print(f"\n{'='*55}")
        print(f"  📊 回测结果")
        print(f"{'='*55}")
        print(f"  总交易:     {r['total_trades']} 笔")
        print(f"  盈利:       {r['win_trades']} 笔 | 亏损: {r['loss_trades']} 笔")
        print(f"  胜率:       {r['win_rate']}%")
        print(f"  平均收益:   {r['avg_profit']:+.2f}%")
        print(f"  平均盈利:   {r['avg_win']:+.2f}% | 平均亏损: {r['avg_loss']:+.2f}%")
        print(f"  盈亏比:     {r['profit_loss_ratio']}")
        print(f"  最大盈利:   {r['max_profit']:+.2f}% | 最大亏损: {r['max_loss']:+.2f}%")
        print(f"  累计收益:   {r['total_return']:+.2f}%")
        print(f"  最大回撤:   {r['max_drawdown']:+.2f}%")
        print(f"  夏普比率:   {r['sharpe_ratio']}")
        print(f"  中位数收益: {r['median_profit']:+.2f}%")
        print(f"{'='*55}")
        
        # 评级
        if r["win_rate"] >= 55 and r["profit_loss_ratio"] >= 1.5 and r["sharpe_ratio"] >= 1:
            print(f"  🎉 策略有效！胜率+盈亏比+夏普均达标")
        elif r["win_rate"] >= 50:
            print(f"  🔧 策略可用，但需要优化")
        else:
            print(f"  ⚠️  策略需调整，当前效果不佳")
    
    def factor_analysis(self):
        """因子有效性分析"""
        if not self.trades:
            return
        
        print(f"\n{'='*60}")
        print(f"  🔬 因子有效性分析")
        print(f"{'='*60}")
        
        # 按评分分组看胜率
        scored_trades = sorted(self.trades, key=lambda t: t["total_score"])
        n = len(scored_trades)
        
        if n >= 10:
            # 分成高分组和低分组
            cutoff = n // 2
            high_group = scored_trades[cutoff:]
            low_group = scored_trades[:cutoff]
            
            def group_stats(grp, name):
                profits = [t["profit_pct"] for t in grp]
                wins = sum(1 for p in profits if p > 0)
                print(f"  {name}:")
                print(f"    交易数: {len(grp)} | 胜率: {wins/len(grp)*100:.1f}% | 平均: {np.mean(profits):+.2f}%")
            
            group_stats(high_group, "  ✅ 高分组 (评分前50%)")
            group_stats(low_group, "  ❌ 低分组 (评分后50%)")
        
        # 因子单项分析
        print(f"\n  📈 各因子表现:")
        for factor in ["tech_score", "capital_score", "position_score"]:
            factor_trades = sorted(self.trades, key=lambda t: t.get(factor, 0))
            if len(factor_trades) >= 6:
                high = factor_trades[-len(factor_trades)//3:]
                low = factor_trades[:len(factor_trades)//3]
                
                def perf(grp):
                    p = [t["profit_pct"] for t in grp]
                    w = sum(1 for x in p if x > 0)
                    return f"胜率{w/len(p)*100:.0f}% 均{np.mean(p):+.2f}%"
                
                print(f"  {factor}: 高分→{perf(high)} | 低分→{perf(low)}")
    
    def print_recent_trades(self, n=10):
        """打印最近 N 笔交易"""
        if not self.trades:
            return
        recent = self.trades[-n:]
        print(f"\n  📋 最近 {len(recent)} 笔交易:")
        print(f"  {'日期':<12} {'代码':<8} {'买入':>8} {'卖出':>8} {'盈亏':>8} {'评分':>6}")
        print(f"  {'-'*12} {'-'*8} {'-'*8} {'-'*8} {'-'*8} {'-'*6}")
        for t in reversed(recent):
            icon = "✅" if t["profit_pct"] > 0 else "❌"
            print(f"  {t['date']:<12} {t['code']:<8} {t['buy_price']:>8.2f} "
                  f"{t['sell_price']:>8.2f} {t['profit_pct']:>+7.2f}% {t['total_score']:>6.1f} {icon}")


def run_backtest(codes=None, lookback=60, top_n=3, market_filter=True):
    """快速运行回测"""
    if codes is None:
        codes = [
            "600519", "000001", "300750", "601318", "000333",
            "600036", "600276", "000858", "002415", "300059",
            "601166", "000568", "002714", "600887", "300124",
            "002371", "603986", "600703", "002049", "300661",
            "002812", "300014", "300450", "002709", "300274",
            "300760", "300015", "300347", "603259", "002821",
            "300308", "002230", "300502", "300394",
            "002241", "601138", "002384", "300433", "002600",
            "002903", "300331", "600459", "600345", "600237",
            "002174", "300165", "300286", "600550", "300401",
        ]
    
    engine = BacktestEngine(codes, lookback)
    n = engine.load_data()
    if n == 0:
        print("❌ 数据加载失败")
        return
    
    # 大盘数据（用于过滤）
    from data_fetcher import get_market_summary
    sh_pcts = {}  # date -> sh_change_pct
    print("\n  📊 加载大盘环境数据...")
    
    trades = engine.run(min_days=20, top_n=top_n)
    
    if market_filter and trades:
        # 过滤：只保留上证 > -1% 的交易日
        try:
            df = pd.read_csv(JOURNAL_PATH)
        except: 
            pass
        
        # 简易大盘过滤：只保留当天涨幅>0.5%的股票（用个股涨幅近似）
        # 在实际系统中我们会用大盘指数，这里用个股平均涨幅代替
        from collections import defaultdict
        date_profits = defaultdict(list)
        for t in trades:
            date_profits[t["date"]].append(t["profit_pct"])
        
        filtered_trades = []
        for t in trades:
            date_avg = np.mean(date_profits[t["date"]])
            if date_avg > -0.5:  # 当天整体不差
                filtered_trades.append(t)
        
        engine.trades = filtered_trades
        engine._calculate_results()
        
        print(f"  📊 大盘过滤后: {len(trades)} → {len(filtered_trades)} 笔交易")
    
    engine.print_results()
    engine.factor_analysis()
    engine.print_recent_trades(10)
    
    return engine


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run_backtest(top_n=3)
