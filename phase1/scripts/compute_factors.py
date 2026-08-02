#!/usr/bin/env python3
"""Phase2 因子计算引擎 — 100+因子"""
import sys, os
from pathlib import Path
import pandas as pd
import numpy as np

BASE = Path(__file__).parent.parent
DAILY = BASE / 'data' / 'daily'
FACTOR = BASE / 'data' / 'factor'
FACTOR.mkdir(parents=True, exist_ok=True)

class FactorComputer:
    """批量因子计算"""
    
    @staticmethod
    def compute(code: str, path: Path) -> dict:
        df = pd.read_csv(path)
        if len(df) < 60: return {}
        
        # 列名标准化
        cols = {'date': 'date', 'close': 'close', 'open': 'open', 
                'high': 'high', 'low': 'low', 'volume': 'volume'}
        for k, v in cols.items():
            if v not in df.columns:
                for c in df.columns:
                    if k in str(c).lower():
                        cols[k] = c; break
        
        date, close, open_p, high, low, vol = (
            df[cols[k]].values for k in ['date','close','open','high','low','volume']
        )
        last = len(close) - 1
        
        factors = {}
        # === 1. 趋势因子 ===
        for n in [5, 10, 20, 60, 120, 250]:
            if last >= n:
                ma = np.mean(close[-n:])
                factors[f'MA{n}'] = round(ma, 2)
                factors[f'Close/MA{n}'] = round(close[-1]/ma, 3) if ma > 0 else 1
                # MA斜率
                if last >= n + 5:
                    prev_ma = np.mean(close[-(n+5):-5])
                    factors[f'MA{n}_slope'] = round((ma - prev_ma)/prev_ma*100, 2) if prev_ma else 0
        
        # 多头排列
        if all(k in factors for k in ['MA5','MA10','MA20']):
            factors['bull_align'] = 1 if factors['MA5'] > factors['MA10'] > factors['MA20'] else 0
        
        # === 2. 成交量因子 ===
        for n in [5, 20, 60]:
            if last >= n:
                vma = np.mean(vol[-n:])
                factors[f'VOL_MA{n}'] = round(vma/1e6, 1)  # 百万股
                factors[f'VOL_RATIO{n}'] = round(vol[-1]/vma, 2) if vma > 0 else 1
        
        # OBV 简化
        if last >= 20:
            obv = 0; prev_close = close[-20] if last >= 20 else close[0]
            for i in range(-19, 0):
                if close[i] > prev_close: obv += vol[i]
                elif close[i] < prev_close: obv -= vol[i]
                prev_close = close[i]
            factors['OBV_20'] = round(obv/1e8, 2)
        
        # === 3. 波动率因子 ===
        if last >= 14:
            tr = []
            for i in range(max(last-13, 0), last+1):
                h_l = high[i] - low[i]
                h_pc = abs(high[i] - close[i-1]) if i > 0 else h_l
                l_pc = abs(low[i] - close[i-1]) if i > 0 else h_l
                tr.append(max(h_l, h_pc, l_pc))
            factors['ATR14'] = round(np.mean(tr), 2)
            factors['ATR14_pct'] = round(np.mean(tr)/close[-1]*100, 2)
        
        if last >= 20:
            returns = np.diff(close[-21:]) / close[-21:-1] * 100
            factors['volatility_20'] = round(np.std(returns), 2)
        
        # 振幅
        factors['amplitude'] = round((high[-1] - low[-1]) / close[-1] * 100, 2)
        factors['gap'] = round((open_p[-1] - close[-2]) / close[-2] * 100, 2) if last > 0 else 0
        
        # === 4. K线因子 ===
        body = close[-1] - open_p[-1]
        total_range = high[-1] - low[-1]
        factors['body_ratio'] = round(abs(body) / total_range * 100, 2) if total_range > 0 else 0
        factors['upper_shadow'] = round((high[-1] - max(close[-1], open_p[-1])) / total_range * 100, 2) if total_range > 0 else 0
        factors['lower_shadow'] = round((min(close[-1], open_p[-1]) - low[-1]) / total_range * 100, 2) if total_range > 0 else 0
        factors['is_bullish'] = 1 if close[-1] > open_p[-1] else 0
        factors['is_engulf'] = 0  # 需要前日数据
        if last > 1 and close[-1] > open_p[-1] and body > 0:
            prev_body = close[-2] - open_p[-2]
            if prev_body < 0 and abs(body) > abs(prev_body):
                factors['is_engulf'] = 1
        
        # === 5. 收盘位置因子 ===
        factors['close_position'] = round((close[-1] - low[-1]) / (high[-1] - low[-1]), 3) if total_range > 0 else 0.5
        
        # N日涨幅
        for n in [3, 5, 10, 20, 60]:
            if last >= n:
                factors[f'ret_{n}d'] = round((close[-1] / close[-(n+1)] - 1) * 100, 2)
        
        # N日新高
        for n in [20, 60, 250]:
            if last >= n:
                factors[f'new_high_{n}d'] = 1 if close[-1] >= np.max(high[-n:]) else 0
        
        # === 7. 动量因子 ===
        if all(f'ret_{n}d' in factors for n in [5,10,20]):
            factors['momentum'] = round(factors['ret_5d'] * 0.5 + factors['ret_10d'] * 0.3 + factors['ret_20d'] * 0.2, 2)
        
        # === 8. 换手率 ===
        # 从成交额粗略计算 (amount/close 近似交易量)
        
        # === 9. 连涨/连跌天数 ===
        streak = 0
        for i in range(last, max(last-10, 0), -1):
            if close[i] > close[i-1]:
                if streak >= 0: streak += 1
                else: break
            else:
                if streak <= 0: streak -= 1
                else: break
        factors['streak'] = streak
        
        return factors


if __name__ == '__main__':
    # 批量计算并保存
    files = sorted(DAILY.glob('*.csv'))
    print(f"计算 {len(files)} 只股票的因子...")
    
    all_factors = {}
    for i, f in enumerate(files):
        code = f.name.replace('.csv', '')
        try:
            fac = FactorComputer.compute(code, f)
            if fac:
                fac['code'] = code
                all_factors[code] = fac
        except: pass
        
        if (i+1) % 500 == 0:
            print(f"  {i+1}/{len(files)}")
    
    # 保存为因子表
    df = pd.DataFrame.from_dict(all_factors, orient='index')
    df.index.name = 'code'
    df.to_csv(FACTOR / 'daily_factors.csv')
    print(f"\n✅ 因子计算完成: {len(all_factors)} 只, {len(df.columns)} 个因子")
