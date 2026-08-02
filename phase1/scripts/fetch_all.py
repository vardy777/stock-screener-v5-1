#!/usr/bin/env python3
"""Phase1 数据平台 — 新浪60分钟K线 + AKShare股票列表。

注意：历史目录沿用 daily 名称，但内容是60分钟K线，不能精确代表14:50。
"""
import sys, os, json, time, sqlite3
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, r'C:\Users\lisha\stock-screener')
from v3.data import DataFetcher

BASE = Path(__file__).parent.parent
DATA = BASE / 'data'
DAILY = DATA / 'daily'
INDEX = DATA / 'index'
SENTIMENT = DATA / 'sentiment'

for d in [DAILY, INDEX, SENTIMENT]:
    d.mkdir(parents=True, exist_ok=True)

# ═══ 1. 股票列表 (AKShare) ═══
print("[1/4] 股票列表...")
import akshare as ak
stocks = ak.stock_info_a_code_name()
stocks = stocks[~stocks['name'].str.contains('ST|退', na=False)]
print(f"  {len(stocks)} 只 (排除ST/退市)")

# ═══ 2. 60分钟K线 (新浪 fetch_kline) ═══
print("[2/4] 60分钟K线数据 (不是日线)...")
df = DataFetcher()
total = 0
errors = 0

for i, row in stocks.iterrows():
    code = row['code']
    name = row['name']
    cache_file = DAILY / f'{code}.csv'
    
    if cache_file.exists():
        total += 1
        continue
    
    try:
        # 新浪60分钟K线；2500根约为625个完整交易日，并非10年日线。
        kline = df.fetch_kline(str(code), days=2500, scale=60)
        if kline is not None and len(kline) > 10:
            kline.to_csv(cache_file, index=False)
            total += 1
        time.sleep(0.15)  # 限流
    except:
        errors += 1
    
    if total % 500 == 0 and total > 0:
        print(f"  {total}/{len(stocks)} ({total/len(stocks)*100:.0f}%)", flush=True)

print(f"  完成: {total} 只 (错误: {errors})")

# ═══ 3. 指数 (新浪) ═══
print("[3/4] 指数...")
indices = {
    'sh000001': '上证指数',
    'sz399001': '深证成指',
    'sz399006': '创业板指',
}
for code, name in indices.items():
    try:
        kline = df.fetch_kline(code, days=1500)
        if kline is not None and len(kline) > 10:
            kline.to_csv(INDEX / f'{code}.csv', index=False)
            print(f"  {name}: {len(kline)} 天")
    except Exception as e:
        print(f"  {name}: {e}")

# ═══ 4. 情绪数据 ═══
print("[4/4] 情绪...")
try:
    import pandas as pd
    files = sorted(DAILY.glob('*.csv'))[:1000]
    all_rows = []
    
    for f in files:
        df = pd.read_csv(f)
        if 'date' not in df.columns:
            continue
        dates = df['date'].values[-120:]  # 最近120天
        for d in dates:
            day_str = str(d)[:10]
            row = df[df['date'].astype(str).str.startswith(day_str)]
            if row.empty: continue
            r = row.iloc[-1]
            pct = float(r.get('pct_chg', r.get('change_pct', 0)))
            all_rows.append({
                'date': day_str, 'code': f.name.split('.')[0],
                'pct_chg': pct
            })
    
    sentiment = pd.DataFrame(all_rows)
    agg = sentiment.groupby('date').agg(
        up_count=('pct_chg', lambda x: (x > 0).sum()),
        down_count=('pct_chg', lambda x: (x < 0).sum()),
        limit_up=('pct_chg', lambda x: (x >= 9.8).sum()),
        limit_down=('pct_chg', lambda x: (x <= -9.8).sum()),
        total=('pct_chg', 'count'),
    ).reset_index()
    agg = agg.sort_values('date')
    agg.to_csv(SENTIMENT / 'daily.csv', index=False)
    print(f"  情绪: {len(agg)} 天")
except Exception as e:
    print(f"  跳过情绪: {e}")

print("\n✅ Phase1 完成")
